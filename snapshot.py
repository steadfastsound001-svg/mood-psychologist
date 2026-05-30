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

def compute_score(s: dict) -> tuple[int, dict]:
    """На входе — оценки шкал от модели. На выходе — детерминированный score 0-100 + breakdown."""
    phq9 = max(0, min(27, float(s.get("phq9", 0) or 0)))
    gad7 = max(0, min(21, float(s.get("gad7", 0) or 0)))
    k10  = max(10, min(50, float(s.get("k10", 10) or 10)))
    who5 = max(0, min(100, float(s.get("wellbeing", 50) or 50)))
    scs  = max(1.0, min(5.0, float(s.get("self_compassion", 3.0) or 3.0)))

    # нормализуем «плохие» шкалы в 0-100 (100 = максимально плохо)
    phq_norm = phq9 / 27 * 100
    gad_norm = gad7 / 21 * 100
    k10_norm = (k10 - 10) / 40 * 100

    # composite distress (взвешенный) — больше веса депрессии
    distress = phq_norm * 0.40 + gad_norm * 0.30 + k10_norm * 0.30

    # инверсия + бонусы за ресурсы (но не выше +12)
    base = 100 - distress
    wellbeing_bonus = (who5 - 50) * 0.10           # ±5
    compassion_bonus = (scs - 3.0) * 4             # ±8

    raw = base + wellbeing_bonus + compassion_bonus
    score = round(max(0, min(100, raw)))
    return score, {
        "phq9": round(phq9, 1),
        "gad7": round(gad7, 1),
        "k10": round(k10, 1),
        "wellbeing": round(who5, 1),
        "self_compassion": round(scs, 1),
        "distress_index": round(distress, 1),
        "formula": "100 - (PHQ9·0.40 + GAD7·0.30 + K10·0.30) + WHO5_bonus + SCS_bonus",
    }


SCORE_ALGORITHM_RULES = """SCORE НЕ ВЫДАВАЙ. оцени 5 валидированных шкал по симптомам в записях, score посчитает код.

шкалы:
— PHQ-9 (0-27, депрессия): 9 симптомов × 0-3 (0=нет, 1=несколько дней, 2=более половины дней, 3=почти каждый день). симптомы: ангедония, тоска, сон, усталость, аппетит, вина/самооценка, концентрация, психомоторика, суицидальные мысли.
— GAD-7 (0-21, тревога): беспокойство, неконтрол. мысли, страх, раздраж., напряжение, бессонница, утомляемость × 0-3.
— K10 (10-50, дистресс): шкала Кесслера, низ=10, верх=50.
— WHO-5 (0-100, благополучие).
— SCS-SF (1-5, самосострадание Neff).

объективно, без льсти и драматизации. только из записей."""

NOW_PROMPT = """ты делаешь психологический слепок NOW по дневниковым записям вани за последние 30 дней. видишь его базовый профиль и историю предыдущих NOW-слепков.

""" + SCORE_ALGORITHM_RULES + """

верни СТРОГО JSON. никакого markdown, никаких ```, никаких преамбул. только объект:

{
  "phq9": <число 0-27>,
  "gad7": <число 0-21>,
  "k10": <число 10-50>,
  "wellbeing": <число 0-100>,
  "self_compassion": <число 1-5, можно дробное>,
  "label": "<короткая фраза-метка состояния>",
  "summary": "<2-3 фразы про текущее состояние>",
  "emotions": [{"name":"тревога","weight":<int>}, ...],
  "themes": ["..."],
  "patterns": ["..."],
  "risks": ["..."],
  "strengths": ["..."],
  "trend": [{"date":"YYYY-MM-DD","score":<int 0-100>}, ...],
  "shift": "<куда движется относительно предыдущих слепков, 1 фраза>",
  "recommendations": ["..."],
  "key_quotes": ["..."]
}

— emotions: 4-6 штук, сумма weight ≈ 100
— themes: 3-5
— patterns: 2-4
— risks: 0-3
— strengths: 2-3
— trend: суб-оценки по дням только там где реально были записи
— recommendations: 2-3, конкретные шаги с привязкой к ване (его профиль смотри), не общие
— key_quotes: 1-3, реально из текста вани, не пересказ

если предыдущих слепков нет — в shift напиши "первый замер".
не льсти, не драматизируй. шкалы — клинически точно по симптомам в записях."""

HERO_PROMPT = """ты делаешь HERO-слепок — лайфтайм психопортрет вани. видишь базовый профиль, всю историю дневника и всю историю NOW-слепков.

это глубокая характеристика человека, не отчёт за неделю. сделай как написал бы зрелый клинический психолог о клиенте после долгой работы — плотно, без воды, без шаблонов.

""" + SCORE_ALGORITHM_RULES + """
для HERO шкалы оцениваешь УСРЕДНЁННО за всю наблюдаемую жизнь (тренд, базовая линия).

верни СТРОГО JSON. никакого markdown, без ```:

{
  "phq9": <число 0-27>,
  "gad7": <число 0-21>,
  "k10": <число 10-50>,
  "wellbeing": <число 0-100>,
  "self_compassion": <число 1-5>,
  "label": "<тип личности одной фразой>",
  "portrait": "<психопортрет 4-7 плотных абзацев через \\n\\n. кто этот человек, как устроен, чем дышит, где болит. образно где режет точнее.>",
  "traits": [{"name":"перфекционизм","strength":<int 0-100>}, ...],
  "core_values": ["..."],
  "deep_themes": ["..."],
  "life_patterns": ["..."],
  "defense_mechanisms": ["..."],
  "recurring_distortions": ["..."],
  "key_relationships": ["..."],
  "growth_arc": "<откуда шёл → куда пришёл → куда движется, 2-3 фразы>",
  "strengths": ["..."],
  "vulnerabilities": ["..."],
  "long_recommendations": ["..."]
}

score НЕ выдавай — его посчитает код по формуле.
— traits: 5-7 черт
— core_values: 3-5
— deep_themes: 3-5
— life_patterns: 3-5
— defense_mechanisms: 2-4
— recurring_distortions: 2-4
— key_relationships: 2-4
— strengths: 3-5
— vulnerabilities: 2-4
— long_recommendations: 3-5, системные на годы, не на завтра

не дублируй пункты между блоками. каждое поле несёт свой смысл."""


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
            {"type": "text", "text": NOW_PROMPT},
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
            {"type": "text", "text": HERO_PROMPT},
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
