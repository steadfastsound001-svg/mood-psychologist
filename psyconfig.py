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
    # кризисные номера подставляются из variables.json, а не лежат в тексте слоя:
    # слой кэшируется и уехал бы одним списком всем, включая клиентов не из этой страны.
    subst["crisis_numbers"] = (variables.get("crisis") or {}).get("numbers", "")

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
    # safety-файлы кладём как есть: это данные для кода (лексикон детектора), не текст промпта
    for key, rel in (manifest.get("safety") or {}).items():
        vals[key] = _read(rel)

    # номера отдаём и отдельным ключом: safety.guarantee сверяет по ним ответ модели
    vals["crisis_numbers"] = subst["crisis_numbers"]

    # ручки характера: описание шкал отдаём панели, выбранные уровни — промпту.
    # значения уровней живут в agent_config (их крутят из панели), поэтому
    # сам текст собирается в dials_text() и подмешивается в system_base.
    dials_rel = manifest.get("dials")
    if dials_rel:
        vals["dials_spec"] = _read(dials_rel)
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


def dials() -> list[dict]:
    """Описание ручек характера (для панели). Пустой список — ручек нет."""
    try:
        return json.loads(get("dials_spec") or "{}").get("dials", [])
    except json.JSONDecodeError:
        return []


def dials_text(chosen: dict[str, int]) -> str:
    """Выбранные уровни → блок инструкций. Уровень «ровно» ничего не добавляет,
    чтобы не спорить с базовыми слоями."""
    lines = []
    for d in dials():
        lvls = d.get("levels") or []
        i = chosen.get(d["key"], d.get("default", 2))
        if not isinstance(i, int) or not (0 <= i < len(lvls)):
            continue
        t = (lvls[i].get("text") or "").strip()
        if t:
            lines.append(f"— {t}")
    if not lines:
        return ""
    return ("═ НАСТРОЙКА ХАРАКТЕРА — перекрывает общие правила голоса выше, "
            "но НИКОГДА не отменяет безопасность, правду и кризис-протокол\n\n" + "\n".join(lines))


def version() -> str:
    _ensure()
    return _meta.get("version", "0")


def info() -> dict:
    _ensure()
    return dict(_meta)


REQUIRED = ("soul", "system_base", "humanizer_prompt", "compile_prompt")
MIN_LEN = 200          # слой короче — почти наверняка обрезан/пустой файл
RUNTIME_PLACEHOLDERS = {"keys"}   # подставляются кодом в момент вызова (skill_router)


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

    # нерезолвнутый плейсхолдер уехал бы клиенту как «{crisis_numbers}» посреди кризиса.
    # RUNTIME_PLACEHOLDERS подставляет код в момент вызова — их пропускаем.
    import re
    for key, text in vals.items():
        for ph in set(re.findall(r"\{([a-z_]{3,30})\}", text or "")):
            if ph not in RUNTIME_PLACEHOLDERS:
                problems.append(f"в {key} остался неподставленный плейсхолдер {{{ph}}}")

    # кризисный слой обязан нести хотя бы один номер
    scope = vals.get("system_base") or ""
    if "КРИЗИС" in scope and not re.search(r"\b(112|8-800|911|999)\b", scope):
        problems.append("в кризисном слое нет ни одного телефона экстренной помощи")
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
