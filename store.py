"""Multi-tenant хранилище. Два бэкенда:
  - Turso (облачный SQLite по HTTP) — если заданы TURSO_DATABASE_URL + TURSO_AUTH_TOKEN (прод/Render)
  - локальный sqlite3 — иначе (разработка на Mac)

Единый интерфейс: query(sql, params)->list[dict], execute(sql, params)->lastrowid.
"""
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "app.db"

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()


def _turso_on() -> bool:
    return bool(TURSO_URL and TURSO_TOKEN)


def _turso_http(url: str) -> str:
    return url.replace("libsql://", "https://").replace("wss://", "https://").rstrip("/")


def _to_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _from_val(cell):
    t = cell.get("type")
    if t == "null":
        return None
    v = cell.get("value")
    if t == "integer":
        return int(v)
    if t == "float":
        return float(v)
    return v


def _turso_exec(sql: str, params: tuple = ()):  # → (rows_as_dicts, last_insert_rowid)
    import httpx
    stmt = {"sql": sql, "args": [_to_arg(p) for p in params]}
    body = {"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]}
    headers = {"Authorization": "Bearer " + TURSO_TOKEN}
    with httpx.Client(timeout=30) as cli:
        r = cli.post(_turso_http(TURSO_URL) + "/v2/pipeline", json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    res = data["results"][0]
    if res.get("type") != "ok":
        raise RuntimeError("turso: " + str(res))
    result = res["response"]["result"]
    cols = [c["name"] for c in result.get("cols", [])]
    rows = []
    for row in result.get("rows", []):
        rows.append({cols[i]: _from_val(cell) for i, cell in enumerate(row)})
    last_id = result.get("last_insert_rowid")
    last_id = int(last_id) if last_id not in (None, "") else None
    return rows, last_id


# ───────────── локальный sqlite ─────────────

def _local_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def query(sql: str, params: tuple = ()) -> list[dict]:
    if _turso_on():
        rows, _ = _turso_exec(sql, params)
        return rows
    with _local_conn() as c:
        cur = c.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def execute(sql: str, params: tuple = ()) -> int | None:
    if _turso_on():
        _, last = _turso_exec(sql, params)
        return last
    with _local_conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


# ───────────── схема ─────────────

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL, name TEXT DEFAULT '',
      pass_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at REAL)""",
    """CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at REAL)""",
    """CREATE TABLE IF NOT EXISTS profiles(
      user_id INTEGER PRIMARY KEY, raw_info TEXT DEFAULT '',
      test_answers TEXT DEFAULT '', compiled TEXT DEFAULT '',
      onboarded INTEGER DEFAULT 0, updated_at REAL)""",
    """CREATE TABLE IF NOT EXISTS messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      role TEXT NOT NULL, content TEXT NOT NULL, ts REAL)""",
    """CREATE TABLE IF NOT EXISTS documents(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      name TEXT NOT NULL, content TEXT NOT NULL, size INTEGER DEFAULT 0, ts REAL)""",
    """CREATE TABLE IF NOT EXISTS mood_logs(
      user_id INTEGER NOT NULL, day INTEGER NOT NULL, score INTEGER NOT NULL,
      source TEXT DEFAULT 'pulse', ts REAL, PRIMARY KEY(user_id, day))""",
    """CREATE TABLE IF NOT EXISTS diary_entries(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      text TEXT NOT NULL, raw TEXT DEFAULT '', ts REAL)""",
]


def init_db() -> None:
    for stmt in _SCHEMA:
        execute(stmt)
    # миграция: доп-тесты (JSON) в профиле. ADD COLUMN идемпотентно через try.
    try:
        execute("ALTER TABLE profiles ADD COLUMN extra_tests TEXT DEFAULT ''")
    except Exception:
        pass
    # миграция: динамичный MOOD (настрой за 10 дней из дневника) — кэш JSON.
    try:
        execute("ALTER TABLE profiles ADD COLUMN dyn_mood TEXT DEFAULT ''")
    except Exception:
        pass


# ───────────── auth ─────────────

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


def create_user(email: str, password: str, name: str = "") -> dict | None:
    email = email.strip().lower()
    if query("SELECT id FROM users WHERE email=?", (email,)):
        return None
    salt = secrets.token_hex(16)
    uid = execute(
        "INSERT INTO users(email, name, pass_hash, salt, created_at) VALUES(?,?,?,?,?)",
        (email, name, _hash(password, salt), salt, time.time()),
    )
    if uid is None:
        row = query("SELECT id FROM users WHERE email=?", (email,))
        uid = row[0]["id"] if row else None
    execute("INSERT INTO profiles(user_id, updated_at) VALUES(?,?)", (uid, time.time()))
    return {"id": uid, "email": email, "name": name}


def get_or_create_oauth_user(email: str, name: str = "") -> dict:
    email = email.strip().lower()
    rows = query("SELECT id, email, name FROM users WHERE email=?", (email,))
    if rows:
        return rows[0]
    uid = execute(
        "INSERT INTO users(email, name, pass_hash, salt, created_at) VALUES(?,?,?,?,?)",
        (email, name, "oauth-google", "", time.time()),
    )
    if uid is None:
        r = query("SELECT id FROM users WHERE email=?", (email,))
        uid = r[0]["id"] if r else None
    execute("INSERT INTO profiles(user_id, updated_at) VALUES(?,?)", (uid, time.time()))
    return {"id": uid, "email": email, "name": name}


def verify_user(email: str, password: str) -> dict | None:
    email = email.strip().lower()
    rows = query("SELECT * FROM users WHERE email=?", (email,))
    if not rows:
        return None
    u = rows[0]
    if _hash(password, u["salt"]) != u["pass_hash"]:
        return None
    return {"id": u["id"], "email": u["email"], "name": u["name"]}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    execute("INSERT INTO sessions(token, user_id, created_at) VALUES(?,?,?)", (token, user_id, time.time()))
    return token


def user_by_token(token: str) -> dict | None:
    if not token:
        return None
    rows = query(
        "SELECT u.id as id, u.email as email, u.name as name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,),
    )
    return rows[0] if rows else None


# ───────────── profile ─────────────

def get_profile(user_id: int) -> dict:
    rows = query("SELECT * FROM profiles WHERE user_id=?", (user_id,))
    if not rows:
        return {"raw_info": "", "test_answers": "", "compiled": "", "onboarded": 0}
    return rows[0]


def save_raw_info(user_id: int, text: str) -> None:
    execute("UPDATE profiles SET raw_info=?, updated_at=? WHERE user_id=?", (text, time.time(), user_id))


def save_test_answers(user_id: int, answers: dict) -> None:
    import json
    execute("UPDATE profiles SET test_answers=?, updated_at=? WHERE user_id=?",
            (json.dumps(answers, ensure_ascii=False), time.time(), user_id))


def set_compiled(user_id: int, compiled: str) -> None:
    execute("UPDATE profiles SET compiled=?, onboarded=1, updated_at=? WHERE user_id=?",
            (compiled, time.time(), user_id))


def save_extra_tests(user_id: int, data: dict) -> None:
    import json
    execute("UPDATE profiles SET extra_tests=?, updated_at=? WHERE user_id=?",
            (json.dumps(data, ensure_ascii=False), time.time(), user_id))


def get_extra_tests(user_id: int) -> dict:
    import json
    rows = query("SELECT extra_tests FROM profiles WHERE user_id=?", (user_id,))
    if not rows:
        return {}
    try:
        return json.loads(rows[0].get("extra_tests") or "{}")
    except Exception:
        return {}


# ───────────── documents (досье) ─────────────

def add_document(user_id: int, name: str, content: str) -> int | None:
    size = len(content.encode("utf-8"))
    return execute("INSERT INTO documents(user_id, name, content, size, ts) VALUES(?,?,?,?,?)",
                   (user_id, name, content, size, time.time()))


def list_documents(user_id: int) -> list[dict]:
    return query("SELECT id, name, size, ts FROM documents WHERE user_id=? ORDER BY id DESC", (user_id,))


def delete_document(user_id: int, doc_id: int) -> None:
    execute("DELETE FROM documents WHERE id=? AND user_id=?", (doc_id, user_id))


def documents_total(user_id: int) -> int:
    rows = query("SELECT COALESCE(SUM(size),0) AS s FROM documents WHERE user_id=?", (user_id,))
    return int(rows[0]["s"]) if rows else 0


def documents_text(user_id: int, cap: int = 60000) -> str:
    rows = query("SELECT name, content FROM documents WHERE user_id=? ORDER BY id", (user_id,))
    out, total = [], 0
    for r in rows:
        chunk = f"[файл: {r['name']}]\n{r['content']}"
        if total + len(chunk) > cap:
            out.append(chunk[: max(0, cap - total)])
            break
        out.append(chunk)
        total += len(chunk)
    return "\n\n".join(out)


# ───────────── mood-логи (ежедневный пульс / снимки) ─────────────

def log_mood(user_id: int, score: int, source: str = "pulse") -> None:
    """Один снимок настроения на календарный день (upsert)."""
    day = int(time.time() // 86400)
    score = max(0, min(100, int(score)))
    execute(
        "INSERT INTO mood_logs(user_id, day, score, source, ts) VALUES(?,?,?,?,?) "
        "ON CONFLICT(user_id, day) DO UPDATE SET score=excluded.score, source=excluded.source, ts=excluded.ts",
        (user_id, day, score, source, time.time()),
    )


def mood_history(user_id: int, limit: int = 30) -> list[dict]:
    rows = query(
        "SELECT day, score FROM mood_logs WHERE user_id=? ORDER BY day DESC LIMIT ?",
        (user_id, limit),
    )
    return list(reversed(rows))


def mood_today(user_id: int) -> int | None:
    day = int(time.time() // 86400)
    rows = query("SELECT score FROM mood_logs WHERE user_id=? AND day=?", (user_id, day))
    return int(rows[0]["score"]) if rows else None


def _streak_from_days(days: set[int]) -> int:
    """Сколько календарных дней подряд активности, заканчивая сегодня или вчера."""
    if not days:
        return 0
    today = int(time.time() // 86400)
    if today not in days and (today - 1) not in days:
        return 0
    cur = today if today in days else today - 1
    n = 0
    while cur in days:
        n += 1
        cur -= 1
    return n


# ───────────── дневник ─────────────

def add_diary_entry(user_id: int, text: str, raw: str = "") -> dict:
    ts = time.time()
    eid = execute(
        "INSERT INTO diary_entries(user_id, text, raw, ts) VALUES(?,?,?,?)",
        (user_id, text, raw, ts),
    )
    if eid is None:
        row = query("SELECT id FROM diary_entries WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        eid = row[0]["id"] if row else None
    return {"id": eid, "text": text, "ts": ts}


def diary_since(user_id: int, since_ts: float) -> list[dict]:
    """Записи дневника за период (ts >= since_ts), от старых к новым."""
    rows = query(
        "SELECT text, ts FROM diary_entries WHERE user_id=? AND ts>=? ORDER BY ts",
        (user_id, since_ts),
    )
    return [{"text": r["text"], "ts": r["ts"]} for r in rows]


def get_dyn_mood(user_id: int) -> dict | None:
    import json
    rows = query("SELECT dyn_mood FROM profiles WHERE user_id=?", (user_id,))
    if not rows:
        return None
    try:
        return json.loads(rows[0].get("dyn_mood") or "") or None
    except Exception:
        return None


def set_dyn_mood(user_id: int, data: dict) -> None:
    import json
    execute("UPDATE profiles SET dyn_mood=? WHERE user_id=?",
            (json.dumps(data, ensure_ascii=False), user_id))


def list_diary_entries(user_id: int, limit: int = 100) -> list[dict]:
    rows = query(
        "SELECT id, text, ts FROM diary_entries WHERE user_id=? ORDER BY ts DESC LIMIT ?",
        (user_id, limit),
    )
    return [{"id": r["id"], "text": r["text"], "ts": r["ts"]} for r in rows]


def delete_diary_entry(user_id: int, entry_id: int) -> None:
    execute("DELETE FROM diary_entries WHERE id=? AND user_id=?", (entry_id, user_id))


def update_diary_text(user_id: int, entry_id: int, text: str) -> None:
    execute("UPDATE diary_entries SET text=? WHERE id=? AND user_id=?", (text, entry_id, user_id))


# ───────────── stats (сеансы / возраст аккаунта) ─────────────

def chat_stats(user_id: int) -> dict:
    rows = query("SELECT ts FROM messages WHERE user_id=? AND role='user'", (user_id,))
    ts = sorted(r["ts"] for r in rows if r.get("ts"))
    urow = query("SELECT created_at FROM users WHERE id=?", (user_id,))
    created = urow[0].get("created_at") if urow else None
    now = time.time()
    msg_days = {int(t // 86400) for t in ts}
    sessions = len(msg_days)  # сеанс = календарный день с сообщением
    # активные дни для стрика = дни с сообщением ИЛИ с отметкой пульса
    pulse_rows = query("SELECT day FROM mood_logs WHERE user_id=?", (user_id,))
    active_days = msg_days | {int(r["day"]) for r in pulse_rows if r.get("day") is not None}
    days_since_reg = ((now - created) / 86400) if created else 0
    return {"user_msgs": len(ts), "sessions": sessions,
            "days_since_reg": days_since_reg, "streak": _streak_from_days(active_days)}


# ───────────── messages ─────────────

def add_message(user_id: int, role: str, content: str) -> None:
    execute("INSERT INTO messages(user_id, role, content, ts) VALUES(?,?,?,?)",
            (user_id, role, content, time.time()))


def recent_messages(user_id: int, limit: int = 30) -> list[dict]:
    rows = query("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))
