"""Личность психолога из файлов config/psychologist/ — единственный источник правды.

Ни один промпт не живёт в коде: текст правится в .md/.json и подхватывается на лету
(hot reload по mtime, без рестарта и пересборки). Значения отдаются через
agent_config.cfg(), поэтому оверрайд из техпанели по-прежнему главнее файла.

Слои:
  soul.md                — голос/характер (высший приоритет)
  system/*.md            — ядро, склеивается в system_base в порядке manifest
  prompts/*.md           — вторичные промпты (портрет, итоги, редактор, дневник…)
  filters/*.md           — анти-почерк конкретных моделей
  manifest.json          — версия + карта ключ→файл + порядок слоёв
  variables.json         — модели, лимиты, тумблеры, подстановка {client}

Роль процесса задаёт обращение к человеку: у бота — по имени, у вебаппа — обезличенно.
  PSY_ROLE=bot | webapp   (по умолчанию webapp)
"""
import json
import os
import pathlib
import threading

DIR = pathlib.Path(__file__).resolve().parent / "config" / "psychologist"
ROLE = os.environ.get("PSY_ROLE", "webapp").strip() or "webapp"

_lock = threading.Lock()
_cache: dict[str, str] = {}
_meta: dict = {}
_stamp: tuple | None = None


def _files() -> list[pathlib.Path]:
    return sorted(DIR.rglob("*.md")) + sorted(DIR.rglob("*.json"))


def _fingerprint() -> tuple:
    """Отпечаток состояния каталога — меняется при любой правке/добавлении файла."""
    try:
        return tuple((str(p), p.stat().st_mtime_ns) for p in _files())
    except OSError:
        return ()


def _read(rel: str) -> str:
    p = DIR / rel
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _build() -> tuple[dict, dict]:
    """Читает каталог целиком → (значения по ключам, метаданные)."""
    manifest = json.loads((DIR / "manifest.json").read_text(encoding="utf-8"))
    variables = json.loads((DIR / "variables.json").read_text(encoding="utf-8"))

    who = (variables.get("client") or {}).get(ROLE) or "клиент"
    subst = {"client": who, "client_name": who}

    def fill(t: str) -> str:
        for k, v in subst.items():
            t = t.replace("{" + k + "}", v)
        return t

    prompts = manifest.get("prompts") or {}
    # анти-ИИ фильтр живёт в одном файле и подставляется в промпты по {anti_ai}
    subst["anti_ai"] = fill(_read(prompts.get("anti_ai", "prompts/anti_ai.md")))

    vals: dict[str, str] = {}
    vals["soul"] = fill(_read(manifest.get("soul", "soul.md")))
    layers = [_read(rel) for rel in manifest.get("system_layers", [])]
    vals["system_base"] = fill("\n\n".join(x for x in layers if x))
    for key, rel in prompts.items():
        vals[key] = fill(_read(rel))
    for key, rel in (manifest.get("filters") or {}).items():
        vals[key] = fill(_read(rel))

    vals["layer_order"] = ",".join(manifest.get("layer_order") or ["soul", "system_base"])
    for k, v in (variables.get("models") or {}).items():
        if v:
            vals[k] = str(v)
    for k, v in (variables.get("limits") or {}).items():
        vals[k] = str(v)
    for k, v in (variables.get("toggles") or {}).items():
        vals[k] = str(v)

    meta = {"version": manifest.get("version", "0"), "role": ROLE,
            "files": len(_files()), "keys": len(vals)}
    return vals, meta


def _ensure() -> dict:
    """Отдаёт свежие значения: перечитывает каталог, только если он изменился."""
    global _cache, _meta, _stamp
    fp = _fingerprint()
    if fp != _stamp:
        with _lock:
            if fp != _stamp:                      # повторная проверка под замком
                try:
                    _cache, _meta = _build()
                    _stamp = fp
                except Exception as e:            # битый конфиг не должен ронять прод
                    print(f"[psyconfig] не перечитал конфиг ({e}) — работаю на прежнем", flush=True)
                    _stamp = fp
    return _cache


def get(key: str):
    """Значение ключа из файлов (свежее). None — ключа нет, решает вызывающий."""
    return _ensure().get(key)


def version() -> str:
    _ensure()
    return _meta.get("version", "0")


def info() -> dict:
    _ensure()
    return dict(_meta)


REQUIRED = ("soul", "system_base", "humanizer_prompt", "compile_prompt")
MIN_LEN = 200          # слой короче — почти наверняка обрезан/пустой файл


def validate() -> list[str]:
    """Проверка целостности конфига. Пустой список = всё в порядке."""
    problems: list[str] = []
    if not DIR.exists():
        return [f"нет каталога конфига: {DIR}"]
    for name in ("manifest.json", "variables.json"):
        if not (DIR / name).exists():
            problems.append(f"нет {name}")
    if problems:
        return problems
    try:
        manifest = json.loads((DIR / "manifest.json").read_text(encoding="utf-8"))
        json.loads((DIR / "variables.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"битый JSON: {e}"]

    v = str(manifest.get("version", ""))
    if len(v.split(".")) != 3:
        problems.append(f"версия должна быть вида X.Y.Z, а не {v!r}")

    refs = list(manifest.get("system_layers") or [])
    refs += list((manifest.get("prompts") or {}).values())
    refs += list((manifest.get("filters") or {}).values())
    refs.append(manifest.get("soul", "soul.md"))
    for rel in refs:
        p = DIR / rel
        if not p.exists():
            problems.append(f"manifest ссылается на несуществующий файл: {rel}")
        elif not p.read_text(encoding="utf-8").strip():
            problems.append(f"пустой файл конфига: {rel}")

    vals = _ensure()
    for key in REQUIRED:
        if len(vals.get(key) or "") < MIN_LEN:
            problems.append(f"ключ {key} подозрительно короткий ({len(vals.get(key) or '')} симв.)")
    return problems


def install() -> None:
    """Подключить файлы как источник дефолтов для agent_config + проверить их."""
    import agent_config
    agent_config.set_default_provider(get)
    problems = validate()
    if problems:
        for p in problems:
            print(f"[psyconfig] ПРОБЛЕМА: {p}", flush=True)
    else:
        m = info()
        print(f"[psyconfig] конфиг v{m['version']} ok — {m['keys']} ключей "
              f"из {m['files']} файлов, роль {m['role']}", flush=True)


if __name__ == "__main__":
    bad = validate()
    print("\n".join(bad) if bad else f"конфиг v{version()} валиден: {info()}")
