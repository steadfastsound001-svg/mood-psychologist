"""Импорт старых дневниковых записей из Apple Journal HTML в Apple Notes (папка «Психолог»).

Каждая запись:
1. Парсится из HTML → дата + сырой текст.
2. Прогоняется через Sonnet: чистит орфографию (сохраняя голос Вани) + добавляет разбор психолога в новом тоне.
3. Создаётся отдельная заметка в Apple Notes («Психолог — YYYY-MM-DD»).

Запуск: python3 import_old_entries.py
"""
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

ROOT = Path(__file__).parent
ENTRIES_DIR = Path("/Users/johny/Downloads/AppleJournalEntries/Entries")
MASTER_PROFILE = (ROOT / "master_profile.md").read_text()
MODEL = "claude-sonnet-4-6"
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PSYCHOLOGIST_VOICE = """ты — психолог и наставник вани. зрелый, проработанный человек.

тон: спокойный, плотный, без суеты. строчными. без подкола. без терапевтической ванильности. без AI-tells (ключевой/является/важно отметить/конечно/безусловно/тонкости/нюансы/деепричастные пустышки/отрицательные параллелизмы/тройки идей/шаблонные позитивные концовки). без мата у тебя (ваня материт — ты нет). по делу, прямо, тепло где уместно.

у тебя свой голос — не копируй смягчители вани (вроде/типо/походу) пачками, это его подпись. иногда уместно — ок.

образный когда нужно: можешь дать метафору из киноязыка, света, монтажа — ваня режиссёр, ему ложится. но образ один, не три.

подход: кпт + работа с самооценкой + связь с целями. без терминов в лоб."""

PROMPT_TEMPLATE = """{voice}

вот старая дневниковая запись вани от {date}.

твоя задача:
1. почистить орфографию и опечатки, но сохранить ЕГО голос — строчные, смягчители (вроде/типо/походу/как раз), рваный ритм, ёмкие фразы, мат если был. не превращай в литературный текст. не цензурируй откровенное. это ЕГО запись, твоя работа — снять опечатки и шероховатости, не переписать.
2. ниже отдельным блоком (через `---`) дай свой разбор: что видишь как психолог. эмоции, искажения если есть, связь с самооценкой/целями, один конкретный шаг или наблюдение. связной прозой, без формы. учитывая что прошло время — можешь говорить о паттернах, не претендуя на текущее состояние.

ВАЖНО: это историческая запись, твой разбор — ретроспективный, не «давай сделай завтра X», а «вот что я вижу сейчас глядя на эту запись».

═══ ИСХОДНАЯ ЗАПИСЬ ═══
{title_line}{body}

═══

выдай результат строго в формате:

[почищенный текст вани]

---

[твой разбор]

ничего больше — никаких преамбул, никаких заголовков типа «Запись:» или «Анализ:»."""


def parse_html(path: Path) -> tuple[str, str, str]:
    """Возвращает (date_str, title, body_text)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    header = soup.find("div", class_="pageHeader")
    date_str = header.get_text(strip=True) if header else ""
    title_div = soup.find("div", class_="title")
    title = title_div.get_text(strip=True) if title_div else ""
    body_div = soup.find("div", class_="bodyText")
    paragraphs = []
    if body_div:
        for p in body_div.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
    if not paragraphs:
        for p in soup.find_all("p", class_=re.compile("p[2-9]")):
            text = p.get_text(" ", strip=True)
            if text and "<div" not in text:
                paragraphs.append(text)
    body = "\n".join(paragraphs).strip()
    return date_str, title, body


def parse_date(date_str: str, fallback_filename: str) -> str:
    """Возвращает YYYY-MM-DD."""
    months = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12",
    }
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_str)
    if m:
        day, month, year = m.groups()
        if month in months:
            return f"{year}-{months[month]}-{day.zfill(2)}"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", fallback_filename)
    if m:
        return m.group(1)
    return "1970-01-01"


def call_claude(date_iso: str, title: str, body: str) -> str:
    title_line = f"# {title}\n\n" if title else ""
    prompt = PROMPT_TEMPLATE.format(
        voice=PSYCHOLOGIST_VOICE,
        date=date_iso,
        title_line=title_line,
        body=body,
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[{
            "type": "text",
            "text": f"<глубокий_профиль_Вани>\n{MASTER_PROFILE}\n</глубокий_профиль_Вани>",
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def write_apple_notes(date_iso: str, title: str, content: str) -> None:
    """Создаёт НОВУЮ заметку в папке «Психолог»."""
    note_title = f"Психолог — {date_iso}" + (f" — {title}" if title else "")

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "<br>")

    # Делю на «текст» / «разбор» по ---
    if "\n---\n" in content:
        entry_part, analysis_part = content.split("\n---\n", 1)
    else:
        entry_part, analysis_part = content, ""
    entry_part = entry_part.strip()
    analysis_part = analysis_part.strip()

    body_html = f"<h2>Запись</h2><p>{esc(entry_part)}</p>"
    if analysis_part:
        body_html += f"<h2>Разбор</h2><p>{esc(analysis_part)}</p>"

    title_safe = note_title.replace('"', '\\"')
    script = f'''
    tell application "Notes"
        set theFolder to missing value
        repeat with f in folders
            if name of f is "Психолог" then set theFolder to f
        end repeat
        if theFolder is missing value then set theFolder to make new folder with properties {{name:"Психолог"}}
        make new note at theFolder with properties {{name:"{title_safe}", body:"<h1>{title_safe}</h1>" & "{body_html}"}}
    end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ! osascript: {result.stderr.strip()}")


def main() -> None:
    files = sorted(ENTRIES_DIR.glob("*.html"))
    print(f"найдено файлов: {len(files)}")
    for i, f in enumerate(files, 1):
        try:
            raw_date, title, body = parse_html(f)
            date_iso = parse_date(raw_date, f.name)
            if not body or len(body) < 5:
                print(f"[{i}/{len(files)}] {f.name}: пустая запись, пропуск")
                continue
            print(f"[{i}/{len(files)}] {date_iso} — {title or '(без заголовка)'} ({len(body)} символов)")
            content = call_claude(date_iso, title, body)
            write_apple_notes(date_iso, title, content)
            time.sleep(0.5)  # лёгкий троттл
        except Exception as e:
            print(f"  ! ошибка: {e}")
    print("готово")


if __name__ == "__main__":
    main()
