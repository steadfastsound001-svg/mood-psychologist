"""Ядро агента: системный промпт + форматирование. Общее для bot.py (Telegram) и server.py (SaaS).

Тексты личности НЕ живут здесь — они в config/psychologist/ (см. psyconfig.py),
правятся на лету без пересборки. Здесь только сборка слоёв и форматирование.
Не тянет тяжёлых зависимостей (нет telegram/whisper) — безопасно импортировать на хостинге.
"""
import re

import agent_config
import psyconfig
from agent_config import cfg

psyconfig.install()          # файлы конфига = источник дефолтов + валидация на старте

SOUL = psyconfig.get("soul") or ""
SYSTEM_BASE = psyconfig.get("system_base") or ""
ANTI_AI = psyconfig.get("anti_ai") or ""


# ───────────── регистрация редактируемых промптов (админка может менять) ─────────────
agent_config.register("soul", SOUL, "Душа — кто он", "Голос и характер высшего приоритета (config/psychologist/soul.md).", "prompt", 1)
agent_config.register("system_base", SYSTEM_BASE, "Характер, методы, правила", "Главный системный промпт: склейка config/psychologist/system/*.md — инструментарий, голос, длина, запреты.", "prompt", 2)
agent_config.register("anti_ai", ANTI_AI, "Анти-ИИ фильтр", "Подмешивается в портрет, итоги, настрой (config/psychologist/prompts/anti_ai.md).", "prompt", 3)
agent_config.register("layer_order", "soul,system_base",
                      "Порядок слоёв в промпте чата",
                      "Через запятую. Перетасуй — меняешь хронологию подачи. Доступно: soul, system_base. Фильтр модели всегда идёт первым.",
                      "order", 0)
agent_config.register("dials", "", "Ручки характера",
                      "JSON вида {\"warmth\": 3}: выбранные уровни шкал из config/psychologist/dials.json. "
                      "Крутится из центра управления, подмешивается отдельным слоем после базовых.", "setting", 2)
agent_config.register("chat_max_tokens", "700", "Потолок длины ответа (токены)",
                      "ПОТОЛОК-предохранитель, не цель. Короткость задаёт характер (1-2 строки), "
                      "а не обрезка. Слишком мало → ответ обрывается на полуслове; у reasoning-моделей "
                      "(deepseek-v4-pro) часть бюджета съедает размышление. 700 = с запасом.", "setting", 0)


def _dials_block() -> str:
    """Выбранные в панели уровни ручек → текст. Значения лежат в agent_config
    (ключ dials, JSON вида {"warmth": 3, ...}), поэтому меняются на лету."""
    import json
    try:
        chosen = json.loads(cfg("dials", "") or "{}")
    except Exception:
        chosen = {}
    try:
        return psyconfig.dials_text(chosen if isinstance(chosen, dict) else {})
    except Exception:
        return ""


def user_system(compiled_profile: str, insights: str = "") -> list:
    """Душа + ядро + персональный профиль + живые инсайты. Порядок слоёв и тексты — из конфига."""
    parts = {"soul": cfg("soul", SOUL), "system_base": cfg("system_base", SYSTEM_BASE)}
    order = [x.strip() for x in str(cfg("layer_order", "soul,system_base")).split(",") if x.strip()]
    blocks = []
    used = set()
    for name in order:
        if name == "model_filter":
            continue                       # фильтр модели вставляет llm.py (всегда первым)
        t = parts.get(name)
        if t and name not in used:
            blocks.append({"type": "text", "text": t}); used.add(name)
    for name in ("soul", "system_base"):   # на случай если в order чего-то нет
        if name not in used and parts.get(name):
            blocks.append({"type": "text", "text": parts[name]}); used.add(name)
    # ручки характера идут ПОСЛЕ базовых слоёв: они их подстраивают, а не спорят.
    # ставим отдельным блоком — так видно в логах, чем именно личность отличается от базовой.
    tuned = _dials_block()
    if tuned:
        blocks.append({"type": "text", "text": tuned})
    cp = (compiled_profile or "").strip()
    if cp:
        blocks.append({
            "type": "text",
            "text": f"<профиль_клиента>\n{cp}\n</профиль_клиента>",
            "cache_control": {"type": "ephemeral"},
        })
    else:
        blocks.append({
            "type": "text",
            "text": "<профиль_клиента>клиент ещё не прошёл онбординг. узнавай его в диалоге, мягко.</профиль_клиента>",
        })
    ins = (insights or "").strip()
    if ins:
        blocks.append({
            "type": "text",
            "text": ("<что_узнал_в_работе>\n" + ins +
                     "\n</что_узнал_в_работе>\n"
                     "это твои живые наблюдения за этим человеком из прошлых сессий. "
                     "опирайся на них, давай более точные и персональные ходы. не зачитывай их вслух."),
            "cache_control": {"type": "ephemeral"},
        })
    return blocks


# ───────────── markdown → текст ─────────────
_BOLD_RE = re.compile(r"\*\*([^*\n]{1,80}?)\*\*", re.DOTALL)
_FENCE_RE = re.compile(r"```[a-zA-Z0-9]*\n?(.*?)```", re.DOTALL)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def htmlify(text: str) -> str:
    if not text:
        return text
    text = _FENCE_RE.sub(lambda m: m.group(1), text)
    placeholders = []

    def _bold(m):
        idx = len(placeholders)
        placeholders.append(_escape_html(m.group(1).strip()))
        return f"\x00B{idx}\x00"

    text = _BOLD_RE.sub(_bold, text)
    text = re.sub(r"\*\*\*", "", text)
    text = re.sub(r"\*([^*\n]+?)\*", r"\1", text)
    text = re.sub(r"__([^_\n]+?)__", r"\1", text)
    text = re.sub(r"`([^`\n]+?)`", r"\1", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*+", "", text)
    text = _escape_html(text)
    for idx, content in enumerate(placeholders):
        text = text.replace(f"\x00B{idx}\x00", f"<b>{content}</b>")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_plain(html: str) -> str:
    if not html:
        return html
    txt = re.sub(r"<[^>]+>", "", html)
    return txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
