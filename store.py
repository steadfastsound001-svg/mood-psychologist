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
]


def init_db() -> None:
    for stmt in _SCHEMA:
        execute(stmt)


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


# ───────────── messages ─────────────

def add_message(user_id: int, role: str, content: str) -> None:
    execute("INSERT INTO messages(user_id, role, content, ts) VALUES(?,?,?,?)",
            (user_id, role, content, time.time()))


def recent_messages(user_id: int, limit: int = 30) -> list[dict]:
    rows = query("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))
