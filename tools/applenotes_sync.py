"""Локальный мост Apple Notes ↔ веб-приложение MOOD.

Веб-модель живёт на Render и НЕ имеет доступа к Apple Notes (у Notes нет облачного API).
Единственный путь — AppleScript на этом Mac. Этот скрипт:

  pull  — читает все заметки из папки «Психолог» → грузит в досье аккаунта
          (через /api/documents), чтобы модель узнала о тебе больше.
  push  — берёт записи дневника из веб-приложения (/api/diary) и пишет их
          обратно в Apple Notes (папка «Психолог»), по заметке на день.
  sync  — pull + push.

Запуск (нужен токен сессии веб-приложения):
  MOOD_TOKEN=... python3 tools/applenotes_sync.py pull
  MOOD_TOKEN=... python3 tools/applenotes_sync.py sync

Токен берётся из env MOOD_TOKEN или из файла tools/.notes_token (gitignored).
Папку можно сменить через env NOTES_FOLDER (по умолчанию «Психолог»).
"""
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("MOOD_BASE", "https://moodmind-32at.onrender.com").rstrip("/")
FOLDER = os.environ.get("NOTES_FOLDER", "Психолог")
STATE = ROOT / "tools" / ".notes_sync_state.json"
CTX = ssl._create_unverified_context()

PER_NOTE_CAP = 200_000   # символов на заметку при импорте


def _token() -> str:
    t = os.environ.get("MOOD_TOKEN", "").strip()
    if not t:
        f = ROOT / "tools" / ".notes_token"
        if f.exists():
            t = f.read_text(encoding="utf-8").strip()
    if not t:
        print("!! нет токена. задай MOOD_TOKEN=... или положи в tools/.notes_token"); sys.exit(1)
    return t


def _api(path, data=None, method=None, timeout=60):
    h = {"Authorization": "Bearer " + _token()}
    body = None
    if data is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, headers=h, data=body, method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode() or "{}")


def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("osascript: " + r.stderr.strip())
    return r.stdout


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|h[1-6]|li)>", "\n", html)
    txt = re.sub(r"(?s)<[^>]+>", "", html)
    txt = (txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
              .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"'))
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", txt).strip()


def read_notes() -> list[dict]:
    """[{name, body(text)}] из папки FOLDER."""
    script = f'''
    tell application "Notes"
        set theFolder to missing value
        repeat with f in folders
            if name of f is "{FOLDER}" then set theFolder to f
        end repeat
        if theFolder is missing value then return ""
        set out to ""
        repeat with n in notes of theFolder
            set out to out & "@@@N@@@" & (name of n) & "@@@B@@@" & (body of n) & "@@@E@@@"
        end repeat
        return out
    end tell
    '''
    raw = _osascript(script)
    notes = []
    for chunk in raw.split("@@@N@@@"):
        if "@@@B@@@" not in chunk:
            continue
        name, rest = chunk.split("@@@B@@@", 1)
        body = rest.split("@@@E@@@", 1)[0]
        notes.append({"name": name.strip(), "body": _html_to_text(body)})
    return notes


def write_note(title: str, text_html: str) -> None:
    """Создать/дополнить заметку title в папке FOLDER (как в bot.py)."""
    t = title.replace('"', "'")
    b = text_html.replace('"', "'").replace("\n", "<br>")
    script = f'''
    tell application "Notes"
        set theFolder to missing value
        repeat with f in folders
            if name of f is "{FOLDER}" then set theFolder to f
        end repeat
        if theFolder is missing value then set theFolder to make new folder with properties {{name:"{FOLDER}"}}
        set theNote to missing value
        repeat with n in notes of theFolder
            if name of n is "{t}" then set theNote to n
        end repeat
        if theNote is missing value then
            make new note at theFolder with properties {{name:"{t}", body:"<h1>{t}</h1>{b}"}}
        else
            set body of theNote to (body of theNote) & "<br>{b}"
        end if
    end tell
    '''
    _osascript(script)


def cmd_pull():
    notes = read_notes()
    print(f"в папке «{FOLDER}»: {len(notes)} заметок")
    existing = {d["name"] for d in _api("/api/documents").get("documents", [])}
    added = skipped = 0
    for n in notes:
        body = (n["body"] or "").strip()
        if not body:
            skipped += 1; continue
        name = ("[заметка] " + (n["name"] or "без названия"))[:120]
        if name in existing:
            skipped += 1; continue
        content = body[:PER_NOTE_CAP]
        try:
            _api("/api/documents", data={"name": name, "content": content})
            added += 1
            print(f"  + {name} ({len(content)}b)")
        except urllib.error.HTTPError as e:
            print(f"  ! {name}: HTTP {e.code} ({e.read().decode()[:80]}) — стоп"); break
        time.sleep(0.2)
    print(f"импортировано: {added}, пропущено (пусто/дубль): {skipped}")


def cmd_push():
    state = {}
    if STATE.exists():
        try: state = json.loads(STATE.read_text())
        except Exception: state = {}
    done = set(state.get("pushed_ids", []))
    entries = _api("/api/diary").get("entries", [])
    wrote = 0
    for e in entries:
        eid = str(e.get("id"))
        if eid in done:
            continue
        ts = e.get("ts") or time.time()
        day = time.strftime("%d.%m.%Y", time.localtime(ts))
        write_note(f"MOOD дневник — {day}", e.get("text", ""))
        done.add(eid); wrote += 1
        time.sleep(0.2)
    state["pushed_ids"] = sorted(done)
    STATE.write_text(json.dumps(state, ensure_ascii=False))
    print(f"записано в Apple Notes: {wrote} новых записей")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "pull": cmd_pull()
    elif cmd == "push": cmd_push()
    elif cmd == "sync": cmd_pull(); cmd_push()
    else: print("usage: applenotes_sync.py [pull|push|sync]")


if __name__ == "__main__":
    main()
