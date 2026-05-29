"""Загружает «жирную базу обо мне» (папка АНАЛИЗ МЕНЯ) в профиль аккаунта id=1
(steadfast.sound001@gmail.com) на ПРОДЕ.

Что делает:
  - compiled (живое знание агента, кэшируется в system) ← психопортрет;
  - raw_info (питает пересборку портрета) ← стиль общения;
  - досье (documents) ← все аналитические файлы (полная глубина, видно в UI).

Безопасность: dry-run по умолчанию; перед записью полный бэкап БД; никаких удалений.

  python tools/ingest_profile.py            # dry-run
  python tools/ingest_profile.py --apply    # запись (с бэкапом)
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)
import store

SRC = Path("/Users/johny/Desktop/CLAUDE/ДАННЫЕ ОБО МНЕ/АНАЛИЗ МЕНЯ")
TARGET_EMAIL = "steadfast.sound001@gmail.com"


def clean_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    txt = (txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
              .replace("&nbsp;", " ").replace("&mdash;", "—").replace("&#39;", "'"))
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*\n+", "\n\n", txt)
    return txt.strip()


def read_md(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8", errors="ignore").strip()


def read_html(name: str) -> str:
    return clean_html((SRC / name).read_text(encoding="utf-8", errors="ignore"))


def build():
    compiled = read_md("02_psychoportrait.md")
    raw_info = read_md("01_style.md")
    docs = [
        ("[архив] психопортрет (9 лет переписок).md", compiled),
        ("[архив] стиль общения.md", raw_info),
        ("[архив] геном-досье.txt", read_html("genome_dossier.html")),
        ("[архив] здоровье.txt", read_html("health_dashboard.html")),
        ("[архив] вкус в музыке.txt", read_html("music-taste.html")),
        ("[архив] вкус в кино.txt", read_html("cinematic-taste.html")),
    ]
    return compiled, raw_info, docs


def backup():
    dump = {"_meta": {"ts": time.time()}}
    for t in ["users", "profiles", "documents", "messages", "mood_logs", "diary_entries", "sessions"]:
        try:
            dump[t] = store.query(f"SELECT * FROM {t}", ())
        except Exception as e:
            dump[t] = {"_error": str(e)}
    out = ROOT / "backups" / f"db_backup_{int(time.time())}.json"
    out.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"бэкап → {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    backend = "TURSO (ПРОД)" if store._turso_on() else "local sqlite (dev)"
    print(f"\n=== БД: {backend} ===")
    rows = store.query("SELECT id, email FROM users WHERE email=?", (TARGET_EMAIL,))
    if not rows:
        print(f"!! аккаунт {TARGET_EMAIL} не найден"); sys.exit(1)
    uid = rows[0]["id"]
    compiled, raw_info, docs = build()

    print(f"\nЦЕЛЬ: id={uid} {TARGET_EMAIL}")
    print(f"  compiled (портрет → агент, кэш): {len(compiled)} символов")
    print(f"  raw_info (стиль → пересборка):   {len(raw_info)} символов")
    print(f"  досье ({len(docs)} файлов):")
    existing = {d["name"] for d in store.list_documents(uid)}
    for name, content in docs:
        mark = "уже есть, пропущу" if name in existing else "добавлю"
        print(f"    • {name:<42} {len(content):>6}b  [{mark}]")

    if not args.apply:
        print("\n[DRY-RUN] ничего не записано. Применить → --apply\n")
        return

    backup()
    print("\n>>> ПРИМЕНЯЮ...")
    store.save_raw_info(uid, raw_info)
    store.set_compiled(uid, compiled)  # ставит compiled и onboarded=1
    added = 0
    for name, content in docs:
        if name in existing:
            continue
        store.add_document(uid, name, content)
        added += 1
    print(f">>> ГОТОВО. compiled+raw_info обновлены, досье добавлено: {added} файлов")
    print(f"    итог досье: {len(store.list_documents(uid))} файлов, {store.documents_total(uid)} байт\n")


if __name__ == "__main__":
    main()
