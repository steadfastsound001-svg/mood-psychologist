"""Онбординг-тест: быстро даёт агенту портрет нового клиента.

Микс валидированных коротких шкал (Big Five BFI-10, attachment, самооценка,
регуляция) + открытые вопросы (запрос, биография). После прохождения LLM
компилирует персональный профиль, который подаётся агенту в system.
"""
import json
import os

from llm import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# Каждый вопрос: id, тип (scale|text|choice), текст, опции.
# Шкалы — Likert 1-5. reverse=True означает обратный скоринг.
QUESTIONS = [
    {"id": "name", "type": "text", "q": "как тебя зовут? как к тебе обращаться?", "short": True},
    {"id": "age", "type": "text", "q": "сколько тебе лет и чем занимаешься?", "short": True},
    {"id": "request", "type": "text", "q": "что привело тебя сюда? что хочешь понять или изменить в себе?"},
    {"id": "life", "type": "text", "q": "расскажи коротко о себе: что важное происходит в жизни сейчас, кто рядом."},

    {"id": "extra", "type": "scale", "q": "легко завязываю разговор, заряжаюсь от людей", "trait": "extraversion"},
    {"id": "agree", "type": "scale", "q": "доверяю людям, легко прощаю", "trait": "agreeableness"},
    {"id": "consc", "type": "scale", "q": "довожу дела до конца, дисциплинирован", "trait": "conscientiousness"},
    {"id": "neuro", "type": "scale", "q": "часто тревожусь, трудно успокоиться", "trait": "neuroticism"},
    {"id": "open", "type": "scale", "q": "люблю новые идеи, эксперименты, необычное", "trait": "openness"},

    {"id": "attach_close", "type": "scale", "q": "мне легко быть близким и открытым с людьми", "trait": "attachment_secure"},
    {"id": "attach_fear", "type": "scale", "q": "боюсь, что меня бросят или отвергнут", "trait": "attachment_anxious"},

    {"id": "esteem_compare", "type": "scale", "q": "часто сравниваю себя с другими, и не в свою пользу", "trait": "self_esteem"},
    {"id": "esteem_achieve", "type": "scale", "q": "моя ценность сильно зависит от достижений и результата", "trait": "self_worth_conditional"},

    {"id": "reg_withdraw", "type": "scale", "q": "когда плохо — закрываюсь и ухожу в себя", "trait": "regulation_avoidant"},

    {"id": "free", "type": "text", "q": "что ещё психологу важно знать о тебе, чтобы понять тебя быстрее?"},
]

SCALE_LABELS = ["совсем не про меня", "скорее нет", "когда как", "скорее да", "точно про меня"]


# ───────────── доп-тесты (раскрывают человека с разных сторон) ─────────────
# mood: вклад в индекс MOOD (+1 выше=лучше, -1 выше=хуже, 0 — не учитывается).
EXTRA_TESTS = [
    {
        "id": "values", "title": "ценности", "emoji": "🧭",
        "achievement": {"icon": "🧭", "label": "ценности раскрыты"},
        "questions": [
            {"id": "val_growth", "q": "развитие и новый опыт важнее стабильности", "mood": 0},
            {"id": "val_connect", "q": "близкие отношения — главное в жизни", "mood": 0},
            {"id": "val_achieve", "q": "хочу признания и весомых достижений", "mood": 0},
            {"id": "val_freedom", "q": "свобода и независимость превыше всего", "mood": 0},
            {"id": "val_meaning", "q": "ищу смысл, а не просто комфорт", "mood": 0},
        ],
    },
    {
        "id": "stress", "title": "стресс и опора", "emoji": "🛡",
        "achievement": {"icon": "🛡", "label": "карта стресса"},
        "questions": [
            {"id": "str_overwhelm", "q": "часто чувствую, что не справляюсь", "mood": -1},
            {"id": "str_control", "q": "могу влиять на то, что со мной происходит", "mood": 1},
            {"id": "str_body", "q": "стресс бьёт по сну и телу", "mood": -1},
            {"id": "str_recover", "q": "быстро восстанавливаюсь после трудностей", "mood": 1},
            {"id": "str_avoid", "q": "откладываю проблемы вместо решения", "mood": -1},
        ],
    },
    {
        "id": "emotions", "title": "эмоции", "emoji": "❤️",
        "achievement": {"icon": "❤️", "label": "эмоциональный профиль"},
        "questions": [
            {"id": "emo_aware", "q": "хорошо понимаю, что именно чувствую", "mood": 1},
            {"id": "emo_express", "q": "могу открыто выражать эмоции", "mood": 1},
            {"id": "emo_flood", "q": "эмоции часто захватывают меня целиком", "mood": -1},
            {"id": "emo_calm", "q": "умею себя успокоить, когда накрывает", "mood": 1},
            {"id": "emo_empathy", "q": "легко считываю чувства других людей", "mood": 0},
        ],
    },
]

# карта вклада онбординг-шкал в MOOD
_ONB_MOOD = {
    "neuro": -1, "attach_close": 1, "attach_fear": -1,
    "esteem_compare": -1, "esteem_achieve": -1, "reg_withdraw": -1,
}
_EXTRA_MOOD = {q["id"]: q["mood"] for t in EXTRA_TESTS for q in t["questions"]}


def compute_mood(answers: dict, extra: dict | None = None) -> int | None:
    """Детерминированный индекс 0-100 из валидированных шкал. None если данных мало."""
    flat = dict(answers or {})
    for tid, tans in (extra or {}).items():
        flat.update(tans or {})
    vals = []
    for qid, sign in {**_ONB_MOOD, **_EXTRA_MOOD}.items():
        if sign == 0:
            continue
        v = flat.get(qid)
        try:
            n = int(v)
        except Exception:
            continue
        norm = (n - 1) / 4.0  # 0..1
        vals.append(norm if sign > 0 else (1 - norm))
    if len(vals) < 4:
        return None
    return round(sum(vals) / len(vals) * 100)


COMPILE_PROMPT = """ты — психолог, который пишет человеку его портрет. это читает сам клиент, не коллега.

на входе — ответы на тесты (шкалы 1-5 и открытые) + при наличии его дополнительные материалы.

напиши тёплый, но честный портрет «зеркало» — обращайся на «ты». человек должен узнать себя и почувствовать, что его поняли глубоко, без лести и без диагнозов.

формат (markdown, 1500-3500 знаков):
— каждый блок начинай с эмодзи и **жирного заголовка** в одну строку, например: 🧭 **кто ты**
— блоки: кто ты · как ты устроен · сильные стороны · что тебя цепляет (уязвимые места, мягко, как наблюдение) · что тебе поможет
— внутри блоков — короткие абзацы или строки, легко читать
— **жирным** выделяй 1-2 ключевых слова в абзаце

правила:
— строчные буквы (заголовки тоже), живой человеческий язык, без жаргона и терминов
— только из данных, не выдумывай факты
— НЕ давай инструкций «как с тобой работать» — это портрет для тебя, не методичка
— не используй символы ## или другой markdown кроме **жирного** и эмодзи-заголовков
— тон: спокойный наставник, который видит тебя насквозь, но на твоей стороне

выдай только портрет."""


def _answers_blob(answers: dict, raw_info: str, extra: dict | None, documents: str) -> str:
    lines = []
    for qd in QUESTIONS:
        qid = qd["id"]
        val = answers.get(qid)
        if val is None or val == "":
            continue
        if qd["type"] == "scale":
            try:
                n = int(val)
                label = SCALE_LABELS[max(0, min(4, n - 1))]
                lines.append(f"[{qd.get('trait', qid)}] «{qd['q']}» → {n}/5 ({label})")
            except Exception:
                lines.append(f"[{qid}] {val}")
        else:
            lines.append(f"[{qid}] «{qd['q']}»\n{val}")
    # доп-тесты
    qmap = {q["id"]: q["q"] for t in EXTRA_TESTS for q in t["questions"]}
    for tid, tans in (extra or {}).items():
        for qid, v in (tans or {}).items():
            try:
                n = int(v)
                lines.append(f"[{tid}:{qid}] «{qmap.get(qid, qid)}» → {n}/5 ({SCALE_LABELS[max(0,min(4,n-1))]})")
            except Exception:
                pass
    blob = "\n".join(lines)
    if (raw_info or "").strip():
        blob += f"\n\n[дополнительно о себе]\n{raw_info.strip()}"
    if (documents or "").strip():
        blob += f"\n\n[материалы клиента — досье]\n{documents.strip()[:50000]}"
    return blob


def compile_profile(answers: dict, raw_info: str = "", extra: dict | None = None, documents: str = "") -> str:
    """answers: {question_id: value}. Возвращает клиентский портрет."""
    blob = _answers_blob(answers, raw_info, extra, documents)
    resp = client.messages.create(
        max_tokens=2200,
        system=COMPILE_PROMPT,
        messages=[{"role": "user", "content": blob}],
        task="analysis",
    )
    return resp.content[0].text.strip()


def questions_public() -> list[dict]:
    """Версия вопросов для фронта (без trait/служебных полей)."""
    out = []
    for q in QUESTIONS:
        item = {"id": q["id"], "type": q["type"], "q": q["q"]}
        if q["type"] == "scale":
            item["labels"] = SCALE_LABELS
        if q.get("short"):
            item["short"] = True
        out.append(item)
    return out


def extra_tests_public() -> list[dict]:
    """Доп-тесты для фронта."""
    out = []
    for t in EXTRA_TESTS:
        out.append({
            "id": t["id"], "title": t["title"], "emoji": t["emoji"],
            "questions": [{"id": q["id"], "q": q["q"]} for q in t["questions"]],
            "labels": SCALE_LABELS,
        })
    return out
