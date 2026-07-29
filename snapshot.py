import agent_config
"""Психологический слепок — NOW и HERO.

- NOW: за 30 дней. Кэш 1 час. История пишется в snapshots_history.jsonl.
- HERO: лайфтайм-психопортрет. Кэш 10 дней. Сохраняется в hero.json.

NOW учитывает master_profile + последние 30 дней дневника + предыдущие слепки → даёт
рекомендации с привязкой к ване и видит сдвиг от среднего.
HERO опирается на весь дневник + всю историю NOW-слепков → даёт глубокий портрет.
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from llm import Anthropic  # OpenRouter-обёртка (DeepSeek free)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
LOG_PATH = DATA_DIR / "log.jsonl"
HISTORY_PATH = DATA_DIR / "snapshots_history.jsonl"
HERO_PATH = DATA_DIR / "hero.json"
MASTER_PROFILE_PATH = ROOT / "master_profile.md"

MODEL = "claude-sonnet-4-6"
NOW_TTL = timedelta(days=5)
HERO_TTL = timedelta(days=10)


# ───────────── единый алгоритм оценки ─────────────
# Объективность достигается за счёт того что score СЧИТАЕТСЯ КОДОМ, а не моделью.
# Модель оценивает только клинические шкалы (PHQ-9, GAD-7, K10, WHO-5, SCS-SF),
# а формула детерминированно сводит их в один score 0-100.
#
# Источники:
# - PHQ-9: Kroenke et al., 2001 — депрессия, 0-27 (>= 10 умеренная, >= 15 средне-тяжёлая)
# - GAD-7: Spitzer et al., 2006 — тревога, 0-21 (>= 10 умеренная, >= 15 тяжёлая)
# - K10: Kessler et al., 2002 — психологический дистресс, 10-50 (>= 30 высокий)
# - WHO-5: WHO 1998 — благополучие, 0-100 (< 50 признак риска)
# - SCS-SF: Raes et al., 2011 — самосострадание, 1-5 (>= 3.5 высокое)



# ───────────── чтение данных ─────────────

def read_recent_entries(days: int = 30) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for line in LOG_PATH.read_text().splitlines():
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"])
            if ts >= cutoff:
                out.append(rec)
        except Exception:
            pass
    return out


def read_all_entries() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def read_snapshots_history(limit: int | None = None) -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text().strip().splitlines()
    if limit is not None:
        lines = lines[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def _append_snapshot_full(snap: dict) -> None:
    """Лёгкая запись (без вложенного full) + полный кеш — в одну строку."""
    DATA_DIR.mkdir(exist_ok=True)
    light = {
        "ts": datetime.now().isoformat(),
        "score": snap.get("score"),
        "label": snap.get("label"),
        "summary": snap.get("summary"),
        "shift": snap.get("shift"),
        "emotions": (snap.get("emotions") or [])[:3],
        "themes": (snap.get("themes") or [])[:3],
        "full": snap,
    }
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(light, ensure_ascii=False) + "\n")


def _light(h: dict) -> dict:
    return {k: h.get(k) for k in ("ts", "score", "label", "summary", "shift", "emotions", "themes") if k in h}


def avg_score(history: list[dict]) -> int | None:
    scores = [h.get("score") for h in history if isinstance(h.get("score"), (int, float))]
    if not scores:
        return None
    return round(sum(scores) / len(scores))


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"error": "no_json", "raw": raw[:300]}
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        return {"error": f"json_parse: {e}", "raw": m.group()[:300]}


def _master_profile() -> str:
    # компактный профиль приоритетнее — он сжат для быстрых моделей
    compact = ROOT / "profile_compact.md"
    if compact.exists():
        return compact.read_text()
    try:
        return MASTER_PROFILE_PATH.read_text()
    except Exception:
        return ""


# ───────────── NOW ─────────────

def build_now_snapshot(client: Anthropic, force: bool = False) -> dict:
    history = read_snapshots_history()
    if not force and history:
        last = history[-1]
        try:
            last_ts = datetime.fromisoformat(last["ts"])
            if datetime.now() - last_ts < NOW_TTL and isinstance(last.get("full"), dict):
                cached = last["full"]
                cached.setdefault("meta", {})["from_cache"] = True
                return cached
        except Exception:
            pass

    entries = read_recent_entries(days=30)
    if not entries:
        return {"error": "записей за 30 дней нет — попиши боту хоть несколько дней, потом возвращайся"}

    feed_parts = []
    for r in entries:
        date = r.get("ts", "")[:10]
        feed_parts.append(f"--- {date} ---\nваня: {r.get('entry','')}\nпсихолог: {r.get('reply','')}")
    blob = "\n\n".join(feed_parts)

    profile = _master_profile()
    prior = [_light(h) for h in read_snapshots_history(limit=8)]
    prior_blob = json.dumps(prior, ensure_ascii=False, indent=2) if prior else "(нет)"

    user_msg = (
        f"<предыдущие_now_слепки>\n{prior_blob}\n</предыдущие_now_слепки>\n\n"
        f"<записи_за_30_дней>\n{blob}\n</записи_за_30_дней>"
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=[
            {"type": "text", "text": agent_config.cfg("snapshot_now_prompt")},
            {
                "type": "text",
                "text": f"<базовый_профиль_вани>\n{profile}\n</базовый_профиль_вани>",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{"role": "user", "content": user_msg}],
        task="analysis",
    )
    data = parse_json(resp.content[0].text)
    if "error" in data:
        return data

    # детерминированный score из клинических шкал
    score, breakdown = compute_score(data)
    data["score"] = score
    data["score_breakdown"] = breakdown

    full_history = read_snapshots_history()
    data["avg_score"] = avg_score([_light(h) for h in full_history] + [data])
    data["meta"] = {
        "mode": "now",
        "days": 30,
        "ttl_days": 5,
        "entries_count": len(entries),
        "history_count": len(full_history),
        "generated_at": datetime.now().isoformat(),
        "next_refresh": (datetime.now() + NOW_TTL).isoformat(),
        "from_cache": False,
    }
    _append_snapshot_full(data)
    return data


# ───────────── HERO ─────────────

def build_hero_snapshot(client: Anthropic, force: bool = False) -> dict:
    if not force and HERO_PATH.exists():
        try:
            cached = json.loads(HERO_PATH.read_text())
            gen_at_s = (cached.get("meta") or {}).get("generated_at", "1970-01-01")
            gen_at = datetime.fromisoformat(gen_at_s)
            if datetime.now() - gen_at < HERO_TTL:
                cached.setdefault("meta", {})["from_cache"] = True
                return cached
        except Exception:
            pass

    entries = read_all_entries()
    history = read_snapshots_history()

    feed_parts = []
    for r in entries:
        date = r.get("ts", "")[:10]
        feed_parts.append(f"--- {date} ---\nваня: {r.get('entry','')}\nпсихолог: {r.get('reply','')}")
    blob = "\n\n".join(feed_parts) if feed_parts else "(дневник пуст)"

    profile = _master_profile()
    hist_light = [_light(h) for h in history]
    hist_blob = json.dumps(hist_light, ensure_ascii=False, indent=2) if hist_light else "(нет)"

    user_msg = (
        f"<история_now_слепков>\n{hist_blob}\n</история_now_слепков>\n\n"
        f"<весь_дневник>\n{blob}\n</весь_дневник>"
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[
            {"type": "text", "text": agent_config.cfg("snapshot_hero_prompt")},
            {
                "type": "text",
                "text": f"<базовый_профиль_вани>\n{profile}\n</базовый_профиль_вани>",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{"role": "user", "content": user_msg}],
        task="analysis",
    )
    data = parse_json(resp.content[0].text)
    if "error" in data:
        return data

    score, breakdown = compute_score(data)
    data["score"] = score
    data["score_breakdown"] = breakdown

    data["meta"] = {
        "mode": "hero",
        "ttl_days": 10,
        "entries_count": len(entries),
        "history_count": len(history),
        "generated_at": datetime.now().isoformat(),
        "next_refresh": (datetime.now() + HERO_TTL).isoformat(),
        "from_cache": False,
    }
    DATA_DIR.mkdir(exist_ok=True)
    HERO_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data
