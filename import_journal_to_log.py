"""Импорт исторических HTML-записей Apple Journal в data/log.jsonl.

Записи помечаются kind='historical', чтобы HERO-снимок их учитывал.
Не создаёт дубликаты: по уникальному (date, body[:60]).

Источник: /Users/johny/Desktop/CLAUDE/ДАННЫЕ ОБО МНЕ/Мой дневник/Entries/*.html
"""
import json
import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
ENTRIES_DIR = Path("/Users/johny/Desktop/CLAUDE/ДАННЫЕ ОБО МНЕ/Мой дневник/Entries")
LOG_PATH = ROOT / "data" / "log.jsonl"

MONTHS = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}


def parse_html(path: Path) -> tuple[str, str, str]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    header = soup.find("div", class_="pageHeader")
    date_str = header.get_text(strip=True) if header else ""
    title_div = soup.find("div", class_="title")
    title = title_div.get_text(strip=True) if title_div else ""
    body_div = soup.find("div", class_="bodyText")
    paras = []
    if body_div:
        for p in body_div.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t:
                paras.append(t)
    if not paras:
        for p in soup.find_all("p", class_=re.compile("p[2-9]")):
            t = p.get_text(" ", strip=True)
            if t and "<div" not in t:
                paras.append(t)
    body = "\n".join(paras).strip()
    return date_str, title, body


def parse_date(date_str: str, fname: str) -> str:
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_str)
    if m:
        d, mo, y = m.groups()
        if mo in MONTHS:
            return f"{y}-{MONTHS[mo]}-{d.zfill(2)}"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", fname)
    if m:
        return m.group(1)
    return "1970-01-01"


def existing_keys() -> set[tuple[str, str]]:
    if not LOG_PATH.exists():
        return set()
    keys = set()
    for line in LOG_PATH.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get("kind") == "historical":
                keys.add((r["ts"][:10], (r.get("entry") or "")[:60]))
        except Exception:
            pass
    return keys


def main() -> None:
    if not ENTRIES_DIR.exists():
        print(f"нет {ENTRIES_DIR}")
        return
    files = sorted(ENTRIES_DIR.glob("*.html"))
    print(f"найдено: {len(files)}")
    existing = existing_keys()
    LOG_PATH.parent.mkdir(exist_ok=True)
    added = 0
    skipped = 0
    with LOG_PATH.open("a", encoding="utf-8") as f:
        for path in files:
            try:
                date_str, title, body = parse_html(path)
                if not body or len(body) < 5:
                    skipped += 1
                    continue
                date_iso = parse_date(date_str, path.name)
                key = (date_iso, body[:60])
                if key in existing:
                    skipped += 1
                    continue
                entry_text = f"{title}\n\n{body}".strip() if title else body
                rec = {
                    "ts": f"{date_iso}T12:00:00",
                    "kind": "historical",
                    "entry": entry_text,
                    "reply": "",
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += 1
            except Exception as e:
                print(f"err {path.name}: {e}")
                skipped += 1
    print(f"добавлено: {added}  пропущено: {skipped}")


if __name__ == "__main__":
    main()
