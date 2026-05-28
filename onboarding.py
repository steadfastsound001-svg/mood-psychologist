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


COMPILE_PROMPT = """ты клинический психолог. на входе — ответы нового клиента на онбординг-тест (шкалы 1-5 и открытые ответы).

сделай компактный рабочий профиль клиента (плотный markdown, 1500-3000 символов), который позволит другому психологу мгновенно понять с кем он имеет дело.

структура:
## кто
имя, возраст, занятие, запрос (зачем пришёл).

## личность
интерпретируй Big Five (extraversion/agreeableness/conscientiousness/neuroticism/openness — где 1 низко, 5 высоко). тип привязанности (по attachment_secure/anxious). самооценка (self_esteem, self_worth_conditional). стиль регуляции (regulation_avoidant). без терминов-аббревиатур — человеческим языком.

## на что обратить внимание
2-4 гипотезы: вероятные болевые точки, защиты, паттерны. осторожно, как гипотезы.

## как с ним работать
2-3 пункта: что заходит, чего избегать, какой тон.

правила:
— строчные буквы, плотно, без воды
— только из ответов, не выдумывай
— это рабочая заметка психолога, не отчёт клиенту
— без markdown-bold, без заголовков глубже ##

выдай только профиль."""


def compile_profile(answers: dict, raw_info: str = "") -> str:
    """answers: {question_id: value}. Возвращает скомпилированный профиль."""
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
    blob = "\n".join(lines)
    if raw_info.strip():
        blob += f"\n\n[дополнительно о себе]\n{raw_info.strip()}"

    resp = client.messages.create(
        max_tokens=2000,
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
