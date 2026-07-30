"""Личный психолог-бот Вани. КПТ + самооценка + цели/мечты.

- Глубокий профиль закэширован через prompt caching (master_profile.md).
- Самообучение в learned_profile.md (фоновый Haiku-extractor).
- Все данные локальные (data/log.jsonl). Никакого Obsidian Vault.
- Каждая запись/диалог — НОВАЯ заметка в Apple Notes (папка «Психолог»).
- Голосовые → whisper → текст.
- Команды: /start /week /month /goals /evening.
- Ежедневный пинг в 22:00.
"""
import asyncio
import json
import mimetypes
import os
import shutil
import ssl
import subprocess
import threading
import time as _time
from datetime import datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

import certifi
from dotenv import load_dotenv

from llm import (Anthropic, stream_completion, stream_completion_sync,
                 trim_incomplete, humanize_text)  # OpenRouter-обёртка
os.environ.setdefault("PSY_ROLE", "bot")   # в TG психолог обращается по имени
import psyconfig
import safety
import agent_config
from agent_core import htmlify, html_to_plain
import agent_core  # noqa: F401 — регистрирует промпты (душа/редактор) в agent_config
from retriever import retrieve_context  # BM25 RAG по дневнику
import store  # multi-tenant SQLite (веб/PWA)
import onboarding  # онбординг-тест + компиляция профиля
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from snapshot import build_hero_snapshot, build_now_snapshot

# SSL для скачивания whisper-моделей и проч.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# launchd стартует с минимальным PATH — homebrew туда не входит.
# Дописываем, чтобы ffmpeg (для whisper) находился.
_extra_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
_path = os.environ.get("PATH", "")
for _p in _extra_paths:
    if _p not in _path:
        _path = f"{_p}:{_path}" if _path else _p
os.environ["PATH"] = _path

# Резолвим ffmpeg один раз при старте — используем абсолютный путь в subprocess,
# чтобы не зависеть от PATH в дочерних процессах.
FFMPEG_BIN = (
    shutil.which("ffmpeg")
    or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None)
    or ("/usr/local/bin/ffmpeg" if Path("/usr/local/bin/ffmpeg").exists() else None)
)
print(f"[boot] PATH={os.environ['PATH']}", flush=True)
print(f"[boot] FFMPEG_BIN={FFMPEG_BIN}", flush=True)

load_dotenv(Path(__file__).parent / ".env", override=True)

TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
USER_ID = int(os.environ["TELEGRAM_USER_ID"])
# почта владельца = ключ синхронизации: TG-бот и веб/PWA пишут в один store-аккаунт
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "steadfast.sound001@gmail.com").strip().lower()
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_OWNER_UID = None
def owner_uid() -> int:
    """store-uid владельца (по OWNER_EMAIL). Кэшируется. Через него идёт синк TG↔веб."""
    global _OWNER_UID
    if _OWNER_UID is None:
        _OWNER_UID = store.get_or_create_oauth_user(OWNER_EMAIL, "telegram")["id"]
    return _OWNER_UID

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
LOG_PATH = DATA_DIR / "log.jsonl"
VOICE_DIR = DATA_DIR / "voice"
WEBAPP_DIR = ROOT / "webapp"
DATA_DIR.mkdir(exist_ok=True)
VOICE_DIR.mkdir(exist_ok=True)

WEB_PORT = int(os.environ.get("WEB_PORT", "8765"))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
TUNNEL_LOG = Path("/tmp/psychologist-tunnel.log")


def detect_webapp_url() -> str:
    """Сначала смотрит в лог cloudflared (актуальный URL), потом в .env."""
    if TUNNEL_LOG.exists():
        try:
            import re as _re
            text = TUNNEL_LOG.read_text(errors="ignore")
            matches = _re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
            if matches:
                return matches[-1]
        except Exception:
            pass
    return os.environ.get("WEBAPP_URL", "").strip()


WEBAPP_URL = detect_webapp_url()
# URL мини-аппа = ПРОД (Render). Telegram инжектит initData в WebApp ТОЛЬКО если
# приложение открыто кнопкой-меню/WebApp с этого origin. Туннель WEBAPP_URL для
# локального «слепка», для входа в мини-апп нужен постоянный публичный адрес.
MINIAPP_URL = os.environ.get("MINIAPP_URL", "").strip() or "https://moodmind-32at.onrender.com"

MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5"
WHISPER_MODEL_NAME = "small"

COMPACT_PATH = ROOT / "profile_compact.md"
MASTER_PATH = ROOT / "master_profile.md"
# Профиль: компактный если есть (для быстрых моделей), иначе master.
if COMPACT_PATH.exists():
    MASTER_PROFILE = COMPACT_PATH.read_text()
else:
    MASTER_PROFILE = MASTER_PATH.read_text()
LEARNED_PATH = ROOT / "learned_profile.md"
LEARNED_COMPACT_THRESHOLD = 30_000
INSIGHTS_PATH = DATA_DIR / "insights.jsonl"
MOOD_PATH = DATA_DIR / "mood.jsonl"

# Whisper-модель загружается лениво.
_whisper_model = None

DIALOG_HISTORY: dict[int, list[dict]] = {}
DIALOG_LIMIT = 30

SYSTEM_BASE = psyconfig.get("system_base") or ""   # текст: config/psychologist/system/*.md


# ───────────── helpers ─────────────

def read_learned() -> str:
    return LEARNED_PATH.read_text() if LEARNED_PATH.exists() else ""


def cached_system() -> list[dict]:
    blocks = [
        {"type": "text", "text": SYSTEM_BASE},
        {
            "type": "text",
            "text": f"<глубокий_профиль_Вани>\n{MASTER_PROFILE}\n</глубокий_профиль_Вани>",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    learned = read_learned().strip()
    if learned:
        blocks.append({
            "type": "text",
            "text": f"<наблюдения_из_живых_диалогов>\n{learned}\n</наблюдения_из_живых_диалогов>",
        })
    return blocks


def read_recent_log(limit: int = 15) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text().strip().splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def has_entry_today() -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    for rec in read_recent_log(50):
        if rec.get("ts", "").startswith(today):
            return True
    return False


def load_recent_context() -> str:
    """Контекст для Claude: последние записи Вани и ответы психолога."""
    records = read_recent_log(10)
    if not records:
        return ""
    parts = ["=== последние записи и обмены ==="]
    for r in records:
        ts = r.get("ts", "")[:16].replace("T", " ")
        parts.append(f"--- {ts} ---")
        parts.append(f"ваня: {r.get('entry', '')}")
        parts.append(f"я: {r.get('reply', '')}")
    return "\n".join(parts)


def write_jsonl(user_text: str, reply: str, kind: str = "text") -> None:
    record = {
        "ts": datetime.now().isoformat(),
        "kind": kind,
        "entry": user_text,
        "reply": reply,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _mark_diary_pushed(entry_id) -> None:
    """Помечаем запись дневника как уже выгруженную в Apple Notes (бот пишет её сам,
    с разбором), чтобы applenotes_sync push не создал дубль."""
    state_path = ROOT / "tools" / ".notes_sync_state.json"
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except Exception:
        state = {}
    ids = set(state.get("pushed_ids", []))
    ids.add(str(entry_id))
    state["pushed_ids"] = sorted(ids)
    state_path.write_text(json.dumps(state, ensure_ascii=False))


def write_apple_notes(user_text: str, reply: str) -> None:
    """Одна заметка на день. Если существует — дополнить. Если нет — создать."""
    now = datetime.now(MOSCOW_TZ)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    title = f"Психолог — {date_str}"

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "<br>")

    block_html = (
        f"<h2>{time_str} · запись</h2><p>{esc(user_text)}</p>"
        f"<h2>{time_str} · разбор</h2><p>{esc(reply)}</p>"
        f"<p>---</p>"
    )
    title_safe = title.replace('"', '\\"')
    script = f'''
    tell application "Notes"
        set theFolder to missing value
        repeat with f in folders
            if name of f is "Психолог" then set theFolder to f
        end repeat
        if theFolder is missing value then set theFolder to make new folder with properties {{name:"Психолог"}}
        set theNote to missing value
        repeat with n in notes of theFolder
            if name of n is "{title_safe}" then set theNote to n
        end repeat
        if theNote is missing value then
            make new note at theFolder with properties {{name:"{title_safe}", body:"<h1>{title_safe}</h1>" & "{block_html}"}}
        else
            set body of theNote to (body of theNote) & "{block_html}"
        end if
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")



# ───────────── streaming reply (SSE → edit_message) ─────────────

STREAM_EDIT_INTERVAL = 0.7   # секунд между edit_message_text (TG лимит ~30/мин/чат)
STREAM_EDIT_MIN_CHARS = 20   # или минимум новых символов перед edit


def _prepare_messages(user_text: str, mode: str, user_id: int) -> tuple[list[dict], str]:
    """Готовит messages с RAG-обвеской: модель видит хронологию + тематически релевантные записи."""
    history = DIALOG_HISTORY.setdefault(user_id, [])

    if mode == "entry":
        user_msg = user_text
    elif mode == "week":
        user_msg = "сделай разбор последней недели по моим записям: эмоции, искажения, динамика самооценки, прогресс по целям, что закрепить, что менять. связно, без формы."
    elif mode == "month":
        user_msg = "разбор последнего месяца по моим записям: тренды, паттерны, что застряло. связно."
    elif mode == "goals":
        user_msg = user_text or "что у меня сейчас по целям и мечтам, по последним записям."
    elif mode == "ask":
        user_msg = user_text  # глубокий вопрос пользователя
    else:
        user_msg = user_text

    # RAG: тематически релевантные записи из дневника/инсайтов
    # — для первого сообщения сессии и для длинных запросов (> 40 chars)
    rag_block = ""
    if (not history) or len(user_text) > 40 or mode in {"week", "month", "goals", "ask"}:
        try:
            top_k = 8 if mode in {"week", "month", "ask"} else 5
            rag_block = retrieve_context(user_msg, top_k=top_k, max_chars=2200)
        except Exception:
            rag_block = ""

    if not history:
        context_recent = load_recent_context()
        bits = []
        if context_recent:
            bits.append(f"<последние_записи_по_порядку>\n{context_recent}\n</последние_записи_по_порядку>")
        if rag_block:
            bits.append(f"<релевантные_записи_по_теме>\n{rag_block}\n</релевантные_записи_по_теме>")
        first = ("\n\n".join(bits) + f"\n\n{user_msg}") if bits else user_msg
        messages = [{"role": "user", "content": first}]
    else:
        if rag_block:
            content = f"<релевантные_записи_по_теме>\n{rag_block}\n</релевантные_записи_по_теме>\n\n{user_msg}"
        else:
            content = user_msg
        messages = history + [{"role": "user", "content": content}]
    return messages, user_msg


async def stream_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_text: str,
    mode: str = "entry",
    max_tokens: int = 460,
    task: str = "dialog",
) -> str | None:
    """Стримит ответ модели в Telegram, обновляя одно сообщение. Возвращает финальный текст."""
    user_id = update.effective_user.id
    messages, user_msg = _prepare_messages(user_text, mode, user_id)
    # риск считаем в коде: у бота потолок вдвое ниже, и кризисный протокол
    # без подъёма лимита обрывается на полуслове.
    tier = safety.detect(user_text) if mode in ("entry", "ask") else None
    if tier:
        max_tokens = safety.policy_for(tier, max_tokens)["max_tokens"]

    placeholder = await update.message.reply_text("…")
    chat_id = placeholder.chat.id
    msg_id = placeholder.message_id

    full = ""
    last_edit_at = 0.0
    last_edited_text = ""

    async def push(text: str, final: bool = False) -> None:
        nonlocal last_edited_text
        if not text:
            return
        # Промежуточные edit'ы шлём как plain (без HTML), чтобы стрим не сломал parse_mode.
        # Финальный edit — с HTML и жирным.
        if final:
            html = htmlify(text)
            if not html:
                return
            if html == last_edited_text:
                return
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=html, parse_mode="HTML"
                )
                last_edited_text = html
                return
            except Exception:
                # Если parse_mode ругнулся — отправляем без тегов
                plain = html_to_plain(html) or "…"
                try:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=plain)
                    last_edited_text = plain
                except Exception:
                    pass
        else:
            plain = html_to_plain(htmlify(text)) or "…"
            if plain == last_edited_text:
                return
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=plain)
                last_edited_text = plain
            except Exception:
                pass

    try:
        async for delta in stream_completion(
            system=cached_system(),
            messages=messages,
            max_tokens=max_tokens,
            task=task,
        ):
            full += delta
            now = _time.monotonic()
            if (now - last_edit_at) >= STREAM_EDIT_INTERVAL and len(full) - len(last_edited_text) >= STREAM_EDIT_MIN_CHARS:
                await push(full)
                last_edit_at = now
        # финал: недописанный хвост (упёрся в max_tokens) срезаем до целого предложения
        full = trim_incomplete(full)
        # 2-й агент (Sonnet-редактор): тот же путь, что на вебаппе — смягчает тон, чинит
        # кальки/машинность, доводит до голоса. только живой диалог (entry/ask), не разборы.
        if mode in ("entry", "ask") and full.strip():
            try:
                loop = asyncio.get_event_loop()
                edited = await loop.run_in_executor(
                    None, lambda: humanize_text(full, user_msg, max_tokens + 200))
                if edited and edited.strip():
                    full = trim_incomplete(edited)
            except Exception:
                pass  # редактор не ответил → оставляем черновик
        full = safety.guarantee(full, tier)   # в кризисе телефон обязан быть
        await push(full, final=True)
    except Exception as e:
        await push(full + f"\n\n[обрыв стрима: {e}]" if full else f"сломалось: {e}")
        return full or None

    final_html = htmlify(full)
    if not final_html:
        return None
    final_plain = html_to_plain(final_html)

    # обновляем dialog history (plain — модель не должна тащить теги в свои следующие ответы)
    hist = DIALOG_HISTORY.setdefault(user_id, [])
    hist.append({"role": "user", "content": user_msg})
    hist.append({"role": "assistant", "content": final_plain})
    if len(hist) > DIALOG_LIMIT:
        DIALOG_HISTORY[user_id] = hist[-DIALOG_LIMIT:]

    return final_plain


# ───────────── ask claude (sync, fallback / служебные вызовы) ─────────────

# ───────────── кризис-детектор ─────────────

CRISIS_KEYWORDS = [
    "не хочу жить", "не хочется жить", "нет смысла жить", "хочу умереть",
    "лучше бы меня не было", "себе вред", "наложить на себя",
    "не справляюсь больше", "не могу больше", "панические атаки",
    "панику не отпускает", "галлюцинации", "слышу голоса",
    "запил", "запой", "сорвался опять",
]


def detect_crisis(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in CRISIS_KEYWORDS)


# ───────────── библиотека техник ─────────────

SKILLS_LIB = {
    "грounding": (
        "5-4-3-2-1 — заземление при тревоге/диссоциации.\n\n"
        "назови: 5 что видишь · 4 что слышишь · 3 что ощущаешь телом · 2 запаха · 1 вкус.\n"
        "медленно, вслух или в заметках. цель — вернуть внимание в настоящее."
    ),
    "tipp": (
        "TIPP — обрубить острый аффект за 60 сек (DBT).\n\n"
        "T — temperature: холодная вода на лицо / лёд 30 сек\n"
        "I — intense exercise: бёрпи / прыжки 30-60 сек\n"
        "P — paced breathing: 4-7-8 (вдох 4, задержка 7, выдох 8) ×4\n"
        "P — paired muscle relaxation: напряг-расслабь группы мышц"
    ),
    "breath": (
        "Дыхание 4-7-8 — для остановки симпатической петли.\n\n"
        "вдох носом 4 сек · задержка 7 сек · выдох ртом 8 сек.\n"
        "4 цикла. помогает переключить НС в ventral vagal."
    ),
    "thought": (
        "Thought record — разбор автоматической мысли (CBT).\n\n"
        "1. ситуация (факт, без интерпретации)\n"
        "2. эмоция (название + интенсивность 0-100)\n"
        "3. автоматическая мысль (без цензуры)\n"
        "4. доказательства ЗА мысль\n"
        "5. доказательства ПРОТИВ\n"
        "6. альтернативная мысль (не позитивная — реалистичная)\n"
        "7. эмоция теперь"
    ),
    "defusion": (
        "Cognitive defusion — расцепление с мыслью (ACT).\n\n"
        "вместо «я неудачник» → «я замечаю мысль что я неудачник»\n"
        "вместо «всё плохо» → «у меня сейчас есть мысль что всё плохо»\n"
        "цель — увидеть мысль как событие в сознании, а не правду"
    ),
    "urge": (
        "Urge surfing — серфинг по импульсу (MBCT).\n\n"
        "когда тянет к компульсии (соцсети, бухло, скрол) — не подавляй и не делай.\n"
        "сядь. где в теле этот импульс? наблюдай 5-10 мин.\n"
        "урж приходит волной и уходит, если ему не сопротивляться"
    ),
    "opposite": (
        "Opposite action — противоположное действие (DBT).\n\n"
        "когда эмоция не соответствует факту (страх безопасной встречи; стыд за норм поступок) —\n"
        "сделай противоположное полному импульсу: подойди вместо убежать, расскажи вместо спрятать.\n"
        "целиком, не наполовину."
    ),
    "values": (
        "Values clarification (ACT).\n\n"
        "не цели, а направления. цель достигается и заканчивается. ценность — компас.\n"
        "вопрос: «каким человеком я хочу быть в работе/отношениях/себе?»\n"
        "потом: «что я сделаю в ближайшие 24 часа в эту сторону?»"
    ),
    "compassion": (
        "Self-compassion break (Neff).\n\n"
        "1. «это момент страдания» (mindfulness)\n"
        "2. «страдание — часть человеческой жизни, я не один» (common humanity)\n"
        "3. рука на сердце: «пусть я буду добр к себе сейчас» (self-kindness)\n"
        "30-60 сек. не сюсюканье — переключение системы аффекта в soothing"
    ),
    "behav": (
        "Behavioral experiment (CBT).\n\n"
        "берёшь конкретное убеждение («если я скажу нет — обидятся и уйдут»).\n"
        "придумываешь мини-тест на 24-72 ч (один отказ).\n"
        "записываешь предсказание ДО и результат ПОСЛЕ.\n"
        "учёт расхождения — единственный способ переписать схему"
    ),
}




# ───────────── редактирование записи ─────────────



def edit_entry(text: str) -> str:
    """Лёгкая правка отчёта через Haiku. Возвращает текст. На ошибке — исходный."""
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1500,
            system=agent_config.cfg("bot_diary_polish_prompt"),
            messages=[{"role": "user", "content": text}],
        )
        out = resp.content[0].text.strip()
        return out or text
    except Exception:
        return text


# ───────────── learning ─────────────



def extract_learning(user_text: str, reply: str) -> str | None:
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=400,
            system=agent_config.cfg("extractor_prompt"),
            messages=[{
                "role": "user",
                "content": f"<сообщение_вани>\n{user_text}\n</сообщение_вани>\n\n<ответ_психолога>\n{reply}\n</ответ_психолога>",
            }],
        )
        text = resp.content[0].text.strip()
        if text in ("—", "-", ""):
            return None
        lines = [l.strip() for l in text.split("\n") if l.strip().startswith("-")]
        return "\n".join(lines) if lines else None
    except Exception:
        return None


def append_learning(facts: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    block = f"\n## {today}\n{facts}\n"
    with LEARNED_PATH.open("a") as f:
        f.write(block)




def compact_learned() -> None:
    raw = read_learned()
    if len(raw) < LEARNED_COMPACT_THRESHOLD:
        return
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=agent_config.cfg("compact_prompt"),
            messages=[{"role": "user", "content": raw}],
        )
        compacted = resp.content[0].text.strip()
        backup = ROOT / f"learned_profile.backup.{datetime.now():%Y%m%d_%H%M%S}.md"
        backup.write_text(raw)
        LEARNED_PATH.write_text(
            f"<!-- last compact: {datetime.now():%Y-%m-%d %H:%M} -->\n\n{compacted}\n"
        )
    except Exception as e:
        print(f"compact failed: {e}")


# ───────────── voice → text ─────────────

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
    return _whisper_model


def transcribe_voice(ogg_path: Path) -> str:
    """Конвертирует .ogg в .wav через ffmpeg, прогоняет через whisper."""
    if not FFMPEG_BIN:
        raise RuntimeError("ffmpeg не найден ни в PATH, ни в /opt/homebrew/bin, ни в /usr/local/bin")
    wav_path = ogg_path.with_suffix(".wav")
    proc = subprocess.run(
        [FFMPEG_BIN, "-y", "-i", str(ogg_path), "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg вернул {proc.returncode}: {proc.stderr[-300:]}")
    model = get_whisper()
    result = model.transcribe(str(wav_path), language="ru", fp16=False)
    text = (result.get("text") or "").strip()
    try:
        wav_path.unlink()
    except Exception:
        pass
    return text


# ───────────── web сервер (Mini App API + статика) ─────────────

class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # тихо
        return

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _base_url(self) -> str:
        return (detect_webapp_url() or f"http://localhost:{WEB_PORT}").rstrip("/")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _google_redirect(self) -> None:
        if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
            self._send_json(400, {"error": "google не настроен"})
            return
        redirect_uri = self._base_url() + "/api/auth/google/callback"
        params = urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account",
        })
        self._redirect("https://accounts.google.com/o/oauth2/v2/auth?" + params)

    def _google_callback(self, url) -> None:
        import httpx
        qs = parse_qs(url.query)
        code = qs.get("code", [""])[0]
        base = self._base_url()
        if not code:
            self._redirect(base + "/?auth_error=1")
            return
        redirect_uri = base + "/api/auth/google/callback"
        try:
            with httpx.Client(timeout=30) as cli:
                tok = cli.post("https://oauth2.googleapis.com/token", data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }).json()
                access = tok.get("access_token")
                if not access:
                    self._redirect(base + "/?auth_error=token")
                    return
                info = cli.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": "Bearer " + access},
                ).json()
            email = info.get("email")
            name = info.get("name") or info.get("given_name") or ""
            if not email:
                self._redirect(base + "/?auth_error=email")
                return
            user = store.get_or_create_oauth_user(email, name)
            token = store.create_session(user["id"])
            prof = store.get_profile(user["id"])
            onb = 1 if prof.get("onboarded") else 0
            self._redirect(base + f"/?token={token}&onb={onb}")
        except Exception as e:
            print(f"[google] callback error: {e}", flush=True)
            self._redirect(base + "/?auth_error=server")

    def _bearer(self) -> str:
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.startswith("Bearer ") else ""

    def _is_owner(self) -> bool:
        """Центр управления виден только владельцу — по почте из токена сессии."""
        user = store.user_by_token(self._bearer())
        return bool(user and (user.get("email") or "").strip().lower() == OWNER_EMAIL)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except Exception:
            length = 0
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        body = self._read_body()
        try:
            if url.path == "/api/auth/register":
                email = (body.get("email") or "").strip().lower()
                pw = body.get("password") or ""
                name = (body.get("name") or "").strip()
                if not email or len(pw) < 4:
                    self._send_json(400, {"error": "нужен email и пароль от 4 символов"})
                    return
                u = store.create_user(email, pw, name)
                if not u:
                    self._send_json(409, {"error": "email уже занят"})
                    return
                token = store.create_session(u["id"])
                self._send_json(200, {"token": token, "user": u})
                return

            if url.path == "/api/auth/login":
                email = (body.get("email") or "").strip().lower()
                pw = body.get("password") or ""
                u = store.verify_user(email, pw)
                if not u:
                    self._send_json(401, {"error": "неверный email или пароль"})
                    return
                token = store.create_session(u["id"])
                prof = store.get_profile(u["id"])
                self._send_json(200, {"token": token, "user": u, "onboarded": bool(prof.get("onboarded"))})
                return

            # дальше — только авторизованные
            user = store.user_by_token(self._bearer())
            if not user:
                self._send_json(401, {"error": "unauthorized"})
                return
            uid = user["id"]

            if url.path == "/api/onboarding/submit":
                answers = body.get("answers") or {}
                raw_info = body.get("raw_info") or ""
                store.save_test_answers(uid, answers)
                if raw_info:
                    store.save_raw_info(uid, raw_info)
                # помечаем онбординг пройденным сразу (пустой compiled), компиляция — в фоне
                store.set_compiled(uid, "")

                def _compile_bg():
                    try:
                        compiled = onboarding.compile_profile(answers, raw_info)
                        store.set_compiled(uid, compiled)
                        print(f"[onboard] профиль uid={uid} готов ({len(compiled)} симв)", flush=True)
                    except Exception as e:
                        print(f"[onboard] compile failed uid={uid}: {e}", flush=True)

                threading.Thread(target=_compile_bg, daemon=True).start()
                self._send_json(200, {"ok": True})
                return

            if url.path == "/api/profile/info":
                raw_info = body.get("raw_info") or ""
                store.save_raw_info(uid, raw_info)
                prof = store.get_profile(uid)
                try:
                    answers = json.loads(prof.get("test_answers") or "{}")
                except Exception:
                    answers = {}

                def _recompile_bg():
                    try:
                        compiled = onboarding.compile_profile(answers, raw_info)
                        store.set_compiled(uid, compiled)
                    except Exception as e:
                        print(f"[profile] recompile failed uid={uid}: {e}", flush=True)

                threading.Thread(target=_recompile_bg, daemon=True).start()
                self._send_json(200, {"ok": True})
                return

            # ── центр управления: правка промптов и проба голоса ──
            if url.path in ("/api/admin/config", "/api/admin/test-chat"):
                if not self._is_owner():
                    self._send_json(403, {"error": "forbidden"})
                    return
                if url.path == "/api/admin/config":
                    key = (body.get("key") or "").strip()
                    if not key:
                        self._send_json(400, {"error": "no key"})
                        return
                    agent_config.set_item(key, body.get("value") or "")
                    self._send_json(200, {"ok": True})
                    return
                # проба: тот же промпт и модели, но без записи в историю клиента
                q = (body.get("q") or "").strip()
                if not q:
                    self._send_json(400, {"error": "empty"})
                    return
                msgs = [{"role": "user" if m.get("role") == "user" else "assistant",
                         "content": (m.get("content") or "").strip()}
                        for m in (body.get("history") or [])[-20:] if (m.get("content") or "").strip()]
                msgs.append({"role": "user", "content": q})
                tier = safety.detect(q)
                cap = safety.policy_for(tier, agent_config.cfg_int("chat_max_tokens", 700))["max_tokens"]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    draft = trim_incomplete("".join(stream_completion_sync(
                        system=cached_system(), messages=msgs, max_tokens=cap, task="dialog")).strip())
                    final = safety.guarantee(
                        trim_incomplete(humanize_text(draft, q, cap + 200)) or draft, tier)
                    self.wfile.write(final.encode("utf-8"))
                except Exception as e:
                    self.wfile.write(f"сломалось: {e}".encode("utf-8"))
                return

            if url.path == "/api/v2/chat":
                text = (body.get("q") or "").strip()
                if not text:
                    self._send_json(400, {"error": "empty"})
                    return
                prof = store.get_profile(uid)
                history = store.recent_messages(uid, 20)
                messages = history + [{"role": "user", "content": text}]
                resp = client.messages.create(
                    system=user_system(prof.get("compiled", "")),
                    messages=messages,
                    max_tokens=320,
                    task="dialog",
                )
                reply = trim_incomplete(resp.content[0].text)
                store.add_message(uid, "user", text)
                store.add_message(uid, "assistant", reply)
                self._send_json(200, {"reply": reply})
                return

            self._send_json(404, {"error": "not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_chat_stream(self, url) -> None:
        qs = parse_qs(url.query)
        text = (qs.get("q", [""])[0] or "").strip()
        if not text:
            self._send_json(400, {"error": "empty query"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def emit(obj: dict) -> None:
            try:
                line = "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        messages, user_msg = _prepare_messages(text, "entry", USER_ID)
        full = ""

        async def runner() -> None:
            nonlocal full
            try:
                async for delta in stream_completion(
                    system=cached_system(),
                    messages=messages,
                    max_tokens=320,
                    task="dialog",
                ):
                    full += delta
                    emit({"d": delta})
            except Exception as e:
                emit({"error": str(e)})

        try:
            asyncio.run(runner())
        except RuntimeError:
            # уже есть event loop в этом потоке — крайне маловероятно для thread-server
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(runner())
            finally:
                loop.close()

        # обновляем dialog history (общая с TG)
        hist = DIALOG_HISTORY.setdefault(USER_ID, [])
        hist.append({"role": "user", "content": user_msg})
        hist.append({"role": "assistant", "content": full})
        if len(hist) > DIALOG_LIMIT:
            DIALOG_HISTORY[USER_ID] = hist[-DIALOG_LIMIT:]

        # сохраняем в общий лог (HERO/NOW будут это учитывать)
        try:
            write_jsonl(text, full, kind="pwa")
        except Exception:
            pass

        emit({"done": True})

    def _send_file(self, path: Path) -> None:
        ct, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".json":
            ct = "application/manifest+json" if path.name == "manifest.json" else "application/json"
        elif path.suffix == ".js":
            ct = "application/javascript; charset=utf-8"
        elif path.suffix == ".svg":
            ct = "image/svg+xml"
        ct = ct or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        # Агрессивно запрещаем кэш на всех уровнях (браузер + CF edge) — никакого залипания
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("CDN-Cache-Control", "no-store")
        if path.name == "sw.js":
            self.send_header("Service-Worker-Allowed", "/")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/api/now", "/api/hero"):
            try:
                qs = parse_qs(url.query)
                force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
                if url.path == "/api/now":
                    data = build_now_snapshot(client, force=force)
                else:
                    data = build_hero_snapshot(client, force=force)
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return
        if url.path == "/api/chat/stream":
            try:
                self._handle_chat_stream(url)
            except Exception as e:
                try:
                    self._send_json(500, {"error": str(e)})
                except Exception:
                    pass
            return
        if url.path == "/api/chat":
            try:
                qs = parse_qs(url.query)
                text = (qs.get("q", [""])[0] or "").strip()
                if not text:
                    self._send_json(400, {"error": "empty"})
                    return
                messages, user_msg = _prepare_messages(text, "entry", USER_ID)
                resp = client.messages.create(
                    system=cached_system(),
                    messages=messages,
                    max_tokens=320,
                    task="dialog",
                )
                reply = trim_incomplete(resp.content[0].text)
                hist = DIALOG_HISTORY.setdefault(USER_ID, [])
                hist.append({"role": "user", "content": user_msg})
                hist.append({"role": "assistant", "content": reply})
                if len(hist) > DIALOG_LIMIT:
                    DIALOG_HISTORY[USER_ID] = hist[-DIALOG_LIMIT:]
                try:
                    write_jsonl(text, reply, kind="pwa")
                except Exception:
                    pass
                self._send_json(200, {"reply": reply})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return
        if url.path == "/api/chat/history":
            try:
                hist = DIALOG_HISTORY.get(USER_ID, [])
                self._send_json(200, {"items": hist[-30:]})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return
        if url.path == "/api/mood":
            try:
                recs = []
                if MOOD_PATH.exists():
                    for line in MOOD_PATH.read_text().strip().splitlines()[-30:]:
                        try:
                            recs.append(json.loads(line))
                        except Exception:
                            pass
                self._send_json(200, {"items": recs})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return
        if url.path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if url.path == "/api/auth/google":
            self._google_redirect()
            return
        if url.path == "/api/auth/google/callback":
            self._google_callback(url)
            return
        if url.path == "/api/auth/google/enabled":
            self._send_json(200, {"enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)})
            return
        if url.path == "/api/onboarding/questions":
            self._send_json(200, {"questions": onboarding.questions_public()})
            return
        # ── центр управления: те же данные, что у прод-сервера. Нужны здесь,
        #    потому что панель открывают и через локальный туннель бота.
        if url.path in ("/api/admin/overview", "/api/admin/config"):
            if not self._is_owner():
                self._send_json(403, {"error": "forbidden"})
                return
            if url.path == "/api/admin/config":
                self._send_json(200, {"items": agent_config.all_items()})
                return
            self._send_json(200, {
                "owner_email": OWNER_EMAIL,
                "users": store.admin_overview(),
                "config": {**psyconfig.info(), "problems": psyconfig.validate()},
                "safety": {"markers_ok": not safety.selftest(),
                           "numbers": len(safety._known_numbers())},
                "models": {k: agent_config.cfg(k) for k in
                           ("model_chat", "model_deep", "humanizer_model", "humanize_on")},
                "dials": {"spec": psyconfig.dials(), "value": agent_config.cfg("dials", "")},
            })
            return
        if url.path == "/api/me":
            user = store.user_by_token(self._bearer())
            if not user:
                self._send_json(401, {"error": "unauthorized"})
                return
            prof = store.get_profile(user["id"])
            self._send_json(200, {
                "user": user,
                "onboarded": bool(prof.get("onboarded")),
                "has_info": bool((prof.get("raw_info") or "").strip()),
                "compiled": prof.get("compiled", ""),
            })
            return
        rel = url.path.lstrip("/") or "index.html"
        target = (WEBAPP_DIR / rel).resolve()
        try:
            target.relative_to(WEBAPP_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        self._send_file(target)


def user_system(compiled_profile: str) -> list[dict]:
    """Универсальное ядро (SYSTEM_BASE) + персональный профиль клиента."""
    blocks = [{"type": "text", "text": SYSTEM_BASE}]
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
    return blocks


def start_web_server() -> None:
    if not WEBAPP_DIR.exists():
        print(f"[web] {WEBAPP_DIR} не найден — Mini App не поднимаю", flush=True)
        return
    try:
        store.init_db()
        print("[web] sqlite готова", flush=True)
    except Exception as e:
        print(f"[web] sqlite init failed: {e}", flush=True)
    # порт занят прежним инстансом → НЕ роняем бота: Telegram-поллинг важнее Mini App.
    try:
        ThreadingHTTPServer.allow_reuse_address = True
        server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), WebHandler)
    except OSError as e:
        print(f"[web] порт {WEB_PORT} занят ({e}) — Mini App пропускаю, бот работает", flush=True)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[web] слушаю http://127.0.0.1:{WEB_PORT}", flush=True)


# ───────────── handlers ─────────────

AVATAR_PATH = ROOT / "webapp" / "avatar.jpg"


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    if AVATAR_PATH.exists():
        try:
            with AVATAR_PATH.open("rb") as f:
                await update.message.reply_photo(photo=f, caption="на связи")
        except Exception:
            pass
    await update.message.reply_text(
        "на связи. пиши или диктуй голосовое — про день, про эмоции, или просто поговорить.\n\n"
        "ежедневный чекин: 22:00 вечером\n\n"
        "команды:\n"
        "/template — шаблон для дневника\n"
        "/morning — утренний чек-ин\n"
        "/evening — вечерний чек-ин\n"
        "/mood 0-10 — быстрый замер настроения\n"
        "/skill <тревога|урж|разбор мысли> — техника\n"
        "/insights — что я сам про себя понял\n"
        "/week — обзор недели\n"
        "/month — обзор месяца\n"
        "/goals — цели и мечты\n"
        "/dashboard — слепок NOW/HERO (mini app)"
    )


async def _process_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kind: str) -> None:
    """Общий путь для текста и расшифрованных голосовых. Стримит ответ."""
    await update.message.chat.send_action("typing")
    crisis = detect_crisis(text)
    try:
        loop = asyncio.get_event_loop()
        is_report = len(text) >= 80
        prompt_text = text
        if crisis:
            prompt_text = f"[КРИЗИС-ФЛАГ — отвечай по кризис-протоколу]\n\n{text}"

        # Редактируем отчёт параллельно стриму
        edited_task = loop.run_in_executor(None, edit_entry, text) if is_report else None
        reply = await stream_reply(update, context, prompt_text, mode="entry", max_tokens=320, task="dialog")
        edited = await edited_task if edited_task else text

        write_jsonl(text, reply or "", kind=kind)
        # синхронизация с веб/PWA: пишем диалог в общий store (Turso) под аккаунт владельца,
        # чтобы то, что написано в TG, появлялось в приложении. не валит ответ при сбое БД.
        try:
            uid = owner_uid()
            store.add_message(uid, "user", text)
            if reply:
                store.add_message(uid, "assistant", reply)
            if is_report:
                # длинная запись = дневник: появляется во вкладке «дневник» приложения
                d = store.add_diary_entry(uid, edited or text, raw=text)
                if d.get("id") is not None:
                    _mark_diary_pushed(d["id"])  # в Notes её пишет сам бот (с разбором) — без дублей от sync push
        except Exception as e:
            print(f"[sync] не записал в store: {e}", flush=True)
        if is_report and reply:
            write_apple_notes(edited, reply)
        if crisis:
            await update.message.reply_text(
                "📞 если станет хуже: 8-800-2000-122 (бесплатно, круглосуточно) или 112"
            )
        if reply:
            asyncio.create_task(_learn_in_background(text, reply))
    except Exception as e:
        await update.message.reply_text(f"сломалось: {e}")


async def _learn_in_background(text: str, reply: str) -> None:
    loop = asyncio.get_event_loop()
    facts = await loop.run_in_executor(None, extract_learning, text, reply)
    if facts:
        await loop.run_in_executor(None, append_learning, facts)
    insight = await loop.run_in_executor(None, extract_insight, text, reply)
    if insight:
        await loop.run_in_executor(None, append_insight, insight)
    await loop.run_in_executor(None, compact_learned)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    text = update.message.text or ""
    await _process_entry(update, context, text, kind="text")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    print(f"[voice] получено сообщение от {update.effective_user.id}", flush=True)
    await update.message.chat.send_action("typing")
    voice = update.message.voice or update.message.audio
    if voice is None:
        print("[voice] update.message.voice пустое — пропуск", flush=True)
        return
    try:
        file = await voice.get_file()
        ogg_path = VOICE_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.ogg"
        await file.download_to_drive(custom_path=ogg_path)
        print(f"[voice] скачал {ogg_path} ({ogg_path.stat().st_size} байт)", flush=True)
    except Exception as e:
        print(f"[voice] ошибка скачивания: {e}", flush=True)
        await update.message.reply_text(f"не смог скачать гс: {e}")
        return
    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, transcribe_voice, ogg_path)
        print(f"[voice] расшифровка: {text[:80]!r}", flush=True)
    except Exception as e:
        print(f"[voice] ошибка whisper: {e}", flush=True)
        await update.message.reply_text(f"не смог расшифровать: {e}")
        return
    if not text:
        await update.message.reply_text("ничего не услышал в записи")
        return
    await update.message.reply_text(f"📝 расшифровка:\n{text}")
    await _process_entry(update, context, text, kind="voice")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    await update.message.chat.send_action("typing")
    await stream_reply(update, context, "", mode="week", max_tokens=300, task="reasoning")


async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    await update.message.chat.send_action("typing")
    await stream_reply(update, context, "", mode="month", max_tokens=460, task="reasoning")


async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    text = " ".join(update.message.text.split()[1:]) if update.message.text else ""
    await update.message.chat.send_action("typing")
    await stream_reply(update, context, text or "покажи мои текущие цели и прогресс", mode="goals", max_tokens=250, task="reasoning")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глубокий вопрос. Использует GPT-OSS-120B (рассуждающую модель) + расширенный RAG."""
    if update.effective_user.id != USER_ID:
        return
    text = " ".join(update.message.text.split()[1:]) if update.message.text else ""
    if not text:
        await update.message.reply_text("формат: /ask <твой вопрос>. это глубокий разбор — медленнее, точнее.")
        return
    await update.message.chat.send_action("typing")
    await stream_reply(update, context, text, mode="ask", max_tokens=500, task="deep")


async def cmd_evening(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    await update.message.reply_text("ну как день?")


async def cmd_morning(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    await update.message.reply_text(
        "доброе. как проснулся? одной фразой:\n— энергия 0-10\n— настроение 0-10\n— тревога 0-10\nили просто расскажи что внутри."
    )


# ───────────── шаблон дневника ─────────────

DIARY_TEMPLATE = (
    "✦ дневник\n\n"
    "🌅 утро (энергия / настроение / тревога 0-10):\n\n"
    "🎯 фокус дня (одно главное):\n\n"
    "🎬 что сделал важного (до 3):\n— \n— \n— \n\n"
    "🪨 где застрял / куда слил время:\n\n"
    "💔 что задело сегодня (эмоция + контекст):\n\n"
    "🧠 одна мысль про себя:\n\n"
    "🛟 опора дня (что вытянуло):\n\n"
    "🌒 вечером — что хочу донести до завтра:"
)


async def cmd_template(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    await update.message.reply_text(
        "вот шаблон. зажми и скопируй, заполни, отправь обратно — разберу.\n"
        "не обязан проходить все пункты. что в фокусе — то и пиши."
    )
    await update.message.reply_text(DIARY_TEMPLATE)


# ───────────── mood ─────────────

def write_mood(score: int, note: str = "") -> None:
    rec = {"ts": datetime.now().isoformat(), "score": score, "note": note}
    DATA_DIR.mkdir(exist_ok=True)
    with MOOD_PATH.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_recent_moods(limit: int = 10) -> list[dict]:
    if not MOOD_PATH.exists():
        return []
    lines = MOOD_PATH.read_text().strip().splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


async def cmd_mood(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    parts = (update.message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        recent = read_recent_moods(5)
        if recent:
            lines = ["последние замеры:"]
            for r in recent:
                ts = r["ts"][:16].replace("T", " ")
                note = f" — {r['note']}" if r.get("note") else ""
                lines.append(f"{ts} · {r['score']}{note}")
            await update.message.reply_text("\n".join(lines) + "\n\nновый: /mood 7 норм")
        else:
            await update.message.reply_text("формат: /mood <0-10> <опц. короткая нота>\nпример: /mood 6 после монтажа просел")
        return
    score = max(0, min(10, int(parts[1])))
    note = parts[2] if len(parts) > 2 else ""
    write_mood(score, note)
    await update.message.reply_text(f"записал. {score}/10{(' · ' + note) if note else ''}")


# ───────────── skills ─────────────

async def cmd_skill(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        keys = ", ".join(SKILLS_LIB.keys())
        await update.message.reply_text(
            "доступные техники: " + keys + "\n\n"
            "формат: /skill <имя> или /skill <свободное описание> — подберу"
        )
        return
    arg = parts[1].strip().lower()
    if arg in SKILLS_LIB:
        await update.message.reply_text(SKILLS_LIB[arg])
        return
    # auto-router через LLM
    try:
        keys = ", ".join(SKILLS_LIB.keys())
        loop = asyncio.get_event_loop()
        def router_call() -> str:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=20,
                system=agent_config.cfg("skill_router_prompt").format(keys=keys),
                messages=[{"role": "user", "content": arg}],
            )
            return resp.content[0].text.strip().lower()
        choice = await loop.run_in_executor(None, router_call)
        choice = choice.split()[0] if choice else ""
        choice = choice.strip("«»\"'.,:!?")
        if choice in SKILLS_LIB:
            await update.message.reply_text(SKILLS_LIB[choice])
        else:
            await update.message.reply_text(
                "не нашёл точной техники. вот всё что есть: " + ", ".join(SKILLS_LIB.keys())
            )
    except Exception as e:
        await update.message.reply_text(f"роутер техник сломался: {e}")


# ───────────── insights ─────────────

async def cmd_insights(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    if not INSIGHTS_PATH.exists():
        await update.message.reply_text("инсайтов пока нет — они копятся из наших диалогов автоматически")
        return
    lines = INSIGHTS_PATH.read_text().strip().splitlines()[-15:]
    items = []
    for line in lines:
        try:
            r = json.loads(line)
            items.append(f"· {r.get('text','').strip()}  ({r.get('ts','')[:10]})")
        except Exception:
            pass
    await update.message.reply_text("свежие инсайты:\n\n" + "\n".join(items) if items else "пусто")


async def cmd_panel(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Ссылка в центр управления с уже вложенным входом.

    Telegram сам подтверждает, что это владелец, поэтому отдельный пароль не нужен:
    кладём токен сессии в ссылку, панель прячет его в браузер и больше не спрашивает.
    """
    if update.effective_user.id != USER_ID:
        return
    base = detect_webapp_url()
    if not base:
        await update.message.reply_text("нет публичного адреса: не поднят туннель на 127.0.0.1:8765")
        return
    try:
        token = store.create_session(owner_uid())
    except Exception as e:
        await update.message.reply_text(f"не создал сессию: {e}")
        return
    url = f"{base.rstrip('/')}/admin.html#token={token}"
    await update.message.reply_text(
        "центр управления. открой один раз — дальше входить не нужно:\n\n" + url,
        disable_web_page_preview=True,
    )


async def cmd_dashboard(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    if not WEBAPP_URL:
        await update.message.reply_text(
            "WEBAPP_URL пуст. подними cloudflared tunnel на 127.0.0.1:8765, добавь URL в .env, перезапусти бота."
        )
        return
    btn = InlineKeyboardButton("📊 открыть слепок", web_app=WebAppInfo(url=WEBAPP_URL))
    kb = InlineKeyboardMarkup([[btn]])
    await update.message.reply_text("психологический слепок текущего момента:", reply_markup=kb)


async def _register_menu_button(app) -> None:
    """Кнопка-меню рядом со скрепкой → открывает Mini App с ПРОДА.
    Только так Telegram отдаёт initData → нативный вход без Google."""
    try:
        from telegram import MenuButtonWebApp
        await app.bot.set_chat_menu_button(
            chat_id=USER_ID,
            menu_button=MenuButtonWebApp(text="MOOD", web_app=WebAppInfo(url=MINIAPP_URL)),
        )
        print(f"[web] menu button → {MINIAPP_URL}", flush=True)
    except Exception as e:
        print(f"[web] не получилось установить menu button: {e}", flush=True)


async def _register_bot_commands(app) -> None:
    """Нативное TG-меню при нажатии '/'."""
    try:
        from telegram import BotCommand
        cmds = [
            BotCommand("dashboard", "слепок NOW / HERO"),
            BotCommand("template", "шаблон дневника"),
            BotCommand("mood", "настроение 0-10"),
            BotCommand("skill", "техника"),
            BotCommand("insights", "инсайты"),
            BotCommand("morning", "утро"),
            BotCommand("panel", "центр управления"),
            BotCommand("evening", "вечер"),
            BotCommand("week", "обзор недели"),
            BotCommand("month", "обзор месяца"),
            BotCommand("goals", "цели и мечты"),
            BotCommand("ask", "глубокий разбор (медленнее, точнее)"),
            BotCommand("menu", "быстрое меню"),
        ]
        await app.bot.set_my_commands(cmds)
        print(f"[tg] commands set: {len(cmds)}", flush=True)
    except Exception as e:
        print(f"[tg] set_my_commands failed: {e}", flush=True)


async def cmd_menu(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != USER_ID:
        return
    rows = [
        [
            InlineKeyboardButton("📊 слепок", web_app=WebAppInfo(url=WEBAPP_URL)) if WEBAPP_URL else InlineKeyboardButton("📊 слепок", callback_data="noop"),
            InlineKeyboardButton("📝 шаблон", callback_data="cmd:template"),
        ],
        [
            InlineKeyboardButton("💓 mood", callback_data="cmd:mood_help"),
            InlineKeyboardButton("🧠 техника", callback_data="cmd:skill_help"),
        ],
        [
            InlineKeyboardButton("💡 инсайты", callback_data="cmd:insights"),
            InlineKeyboardButton("📈 неделя", callback_data="cmd:week"),
        ],
        [
            InlineKeyboardButton("🌅 утро", callback_data="cmd:morning"),
            InlineKeyboardButton("🌒 вечер", callback_data="cmd:evening"),
        ],
    ]
    await update.message.reply_text("выбирай", reply_markup=InlineKeyboardMarkup(rows))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or q.from_user.id != USER_ID:
        return
    await q.answer()
    data = q.data or ""
    if not data.startswith("cmd:"):
        return
    action = data.split(":", 1)[1]
    fake_msg = q.message
    if action == "template":
        await fake_msg.reply_text(DIARY_TEMPLATE)
    elif action == "mood_help":
        await fake_msg.reply_text("замер настроения: /mood 7 после трен полегчало")
    elif action == "skill_help":
        keys = ", ".join(SKILLS_LIB.keys())
        await fake_msg.reply_text("техника: /skill <имя или описание>\n\nдоступно: " + keys)
    elif action == "insights":
        if not INSIGHTS_PATH.exists():
            await fake_msg.reply_text("инсайтов пока нет")
            return
        lines = INSIGHTS_PATH.read_text().strip().splitlines()[-10:]
        items = []
        for line in lines:
            try:
                r = json.loads(line)
                items.append(f"💡 {r.get('text','').strip()}")
            except Exception:
                pass
        await fake_msg.reply_text("\n\n".join(items) if items else "пусто")
    elif action == "week":
        await fake_msg.chat.send_action("typing")
        await stream_reply(update, context, "", mode="week", max_tokens=300)
    elif action == "morning":
        await fake_msg.reply_text("доброе. энергия / настроение / тревога 0-10. или просто как ты.")
    elif action == "evening":
        await fake_msg.reply_text("ну как день?")


async def evening_ping(context: ContextTypes.DEFAULT_TYPE) -> None:
    if has_entry_today():
        return
    await context.bot.send_message(
        chat_id=USER_ID,
        text="22:00. время дневной записи. что было, что чувствуешь — кидай текстом или голосовым.",
    )


async def morning_ping(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=USER_ID,
        text="доброе. короткий чек-ин: энергия / настроение / тревога 0-10. или /mood 7. или просто пара слов.",
    )


# ───────────── извлечение инсайтов (фоном) ─────────────



def extract_insight(user_text: str, reply: str) -> str | None:
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            system=agent_config.cfg("insight_prompt"),
            messages=[{
                "role": "user",
                "content": f"<ваня>\n{user_text}\n</ваня>\n\n<психолог>\n{reply}\n</психолог>",
            }],
        )
        t = resp.content[0].text.strip().strip('"').strip("«»").strip()
        if t in ("—", "-", "") or len(t) < 12:
            return None
        return t[:200]
    except Exception:
        return None


def append_insight(text: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    rec = {"ts": datetime.now().isoformat(), "text": text}
    with INSIGHTS_PATH.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ───────────── main ─────────────

def main() -> None:
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = (
        ApplicationBuilder()
        .token(TG_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("goals", cmd_goals))
    app.add_handler(CommandHandler("evening", cmd_evening))
    app.add_handler(CommandHandler("morning", cmd_morning))
    app.add_handler(CommandHandler("mood", cmd_mood))
    app.add_handler(CommandHandler("skill", cmd_skill))
    app.add_handler(CommandHandler("insights", cmd_insights))
    app.add_handler(CommandHandler("template", cmd_template))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("panel", cmd_panel))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_daily(evening_ping, time=time(hour=22, minute=0, tzinfo=MOSCOW_TZ))
    # утренний пинг отключён по просьбе вани (команда /morning остаётся доступной вручную)

    async def _diary_to_notes(context):
        """Записи дневника владельца из веб-приложения → Apple Notes. launchd на ~/Desktop
        блокируется TCC, поэтому гоним из процесса бота (права терминала есть)."""
        try:
            loop = asyncio.get_event_loop()
            r = await loop.run_in_executor(None, lambda: subprocess.run(
                ["python3", "tools/applenotes_sync.py", "push"], cwd=str(ROOT),
                capture_output=True, text=True, timeout=120))
            out = (r.stdout or r.stderr).strip().splitlines()[-1:] if (r.stdout or r.stderr) else []
            if out:
                print(f"[diary-notes] {out[0]}", flush=True)
        except Exception as e:
            print(f"[diary-notes] {e}", flush=True)

    app.job_queue.run_repeating(_diary_to_notes, interval=120, first=15)

    async def _post_init(application):
        await _register_menu_button(application)
        await _register_bot_commands(application)

    app.post_init = _post_init
    start_web_server()
    print("психолог запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
