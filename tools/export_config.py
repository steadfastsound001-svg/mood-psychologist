#!/usr/bin/env python3
"""Экспорт конфига психолога в exports/psychologist-config/ (и в ~/Downloads по флагу).

Копия — не свалка: файлы лежат ровно той же структурой, что в config/psychologist/,
поэтому отредактированную папку можно вернуть обратно целиком:

    python3 tools/export_config.py            # выгрузить в exports/
    python3 tools/export_config.py --downloads # + копия в ~/Downloads
    python3 tools/export_config.py --import ~/Downloads/psychologist-config
                                              # вернуть правки в проект (с валидацией)
"""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRC = ROOT / "config" / "psychologist"
DST = ROOT / "exports" / "psychologist-config"

README = """# Конфигурация психолога soul

Это ЖИВЫЕ настройки личности. Поведение психолога определяется только этими файлами —
в коде промптов нет. Правь текст, клади папку обратно, изменения подхватятся на лету
(hot reload по времени изменения файла, без перезапуска и пересборки).

## Что где

| Файл | За что отвечает |
|---|---|
| `soul.md` | голос и характер. Высший приоритет — перекрывает всё остальное |
| `system/00-intro.md` | кто он: роль, чем работает |
| `system/01-identity.md` | язык ответа, канон великих, цель работы |
| `system/02-therapy.md` | методы, принцип выбора техники, конкретные ходы |
| `system/03-voice.md` | голос, такт (тонкость вместо резкости), живая речь, афоризмы |
| `system/04-behavior.md` | ритм диалога, вопросы, режимы, длина, формат |
| `system/05-boundaries.md` | запреты, простой язык, кризис-протокол |
| `prompts/editor.md` | 2-й агент: редактор-голос, доводит черновик до финала |
| `prompts/portrait.md` | портрет-зеркало, который читает клиент |
| `prompts/weekly.md` · `dynmood.md` | итоги недели, настрой за 10 дней |
| `prompts/diary_*.md` | отклик на запись и бережная чистка дневника |
| `prompts/insight.md` · `insights_notes.md` | что агент выносит и запоминает о клиенте |
| `prompts/extractor.md` · `compact.md` | ведение и сжатие профиля |
| `prompts/skill_router.md` | подбор техники под запрос |
| `prompts/snapshot_now.md` · `snapshot_hero.md` | психологические слепки NOW / HERO |
| `prompts/anti_ai.md` | анти-ИИ фильтр, подставляется в промпты по `{anti_ai}` |
| `filters/*.md` | гасят почерк конкретных моделей (Gemini, GPT, DeepSeek…) |
| `manifest.json` | версия, порядок слоёв, карта ключ → файл |
| `variables.json` | модели, лимиты токенов, тумблеры, обращение к человеку |

## Подстановки в текстах

- `{client}` — как психолог обращается к человеку. В Telegram подставляется имя,
  в вебаппе — обезличенное «клиент» (задаётся в `variables.json → client`).
- `{anti_ai}` — вставляет содержимое `prompts/anti_ai.md`. Правишь фильтр в одном
  месте — меняется во всех промптах сразу.

## Как вернуть правки в проект

    python3 tools/export_config.py --import <путь к отредактированной папке>

Импорт сначала прогоняет валидацию (версия, наличие и непустота всех файлов из
manifest) и НЕ перезапишет рабочий конфиг, если что-то сломано.

## Версия

Меняешь смысл — подними `version` в `manifest.json` (X.Y.Z). Версия видна в логах
при старте, по ней понятно, какая личность реально крутится в проде.
"""


def export(also_downloads: bool = False) -> None:
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    (DST / "README.md").write_text(README, encoding="utf-8")
    files = sorted(p for p in DST.rglob("*") if p.is_file())
    print(f"выгружено {len(files)} файлов → {DST}")
    for p in files:
        print(f"  {p.relative_to(DST)}")
    if also_downloads:
        home = pathlib.Path.home() / "Downloads" / "psychologist-config"
        if home.exists():
            shutil.rmtree(home)
        shutil.copytree(DST, home)
        print(f"копия → {home}")


def import_back(src: str) -> None:
    p = pathlib.Path(src).expanduser()
    if not (p / "manifest.json").exists():
        print(f"!! в {p} нет manifest.json — это не папка конфига"); sys.exit(1)

    staging = ROOT / "config" / ".psychologist_incoming"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(p, staging)
    (staging / "README.md").unlink(missing_ok=True)

    import psyconfig                      # валидируем ВХОДЯЩИЙ конфиг до подмены
    real_dir = psyconfig.DIR
    psyconfig.DIR = staging
    psyconfig._stamp = None
    problems = psyconfig.validate()
    psyconfig.DIR = real_dir
    psyconfig._stamp = None

    if problems:
        shutil.rmtree(staging)
        print("!! конфиг НЕ принят, рабочая версия не тронута:")
        for x in problems:
            print(f"   - {x}")
        sys.exit(1)

    backup = ROOT / "config" / "psychologist.backup"
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(SRC, backup)
    shutil.rmtree(SRC)
    shutil.move(str(staging), str(SRC))
    print(f"конфиг принят и применён. прежний сохранён в {backup}")
    print(f"версия: {psyconfig.version()}")


if __name__ == "__main__":
    if "--import" in sys.argv:
        i = sys.argv.index("--import")
        if i + 1 >= len(sys.argv):
            print("укажи папку: --import <путь>"); sys.exit(1)
        import_back(sys.argv[i + 1])
    else:
        export(also_downloads="--downloads" in sys.argv)
