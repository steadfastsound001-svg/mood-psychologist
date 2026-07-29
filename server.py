"""Standalone SaaS-сервер психолога. Без Telegram/whisper/Apple Notes — деплоится на любой Python-хостинг.

Эндпойнты: health, auth (register/login/google), onboarding, profile, v2/chat, статика webapp/.
Порт из ENV PORT (Fly/Render дают 8080). SQLite в data/ (на Fly — persistent volume).
"""
import hashlib
import hmac
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)

import store
import onboarding
import safety
import stt
from llm import Anthropic, stream_completion_sync, humanize_stream, humanize_text, trim_incomplete, sentence_guard, _humanize_models as _humanize_cfg
from agent_core import user_system
import agent_config

# ── вторичные промпты: тексты в config/psychologist/prompts/, здесь только метаданные
#    для техпанели (админка может переопределить значение поверх файла) ──
agent_config.register("weekly_prompt", "", "Итоги недели", "3 блока: в фокусе / сдвиг / ориентир. Файл: prompts/weekly.md", "prompt", 5)
agent_config.register("dynmood_prompt", "", "Настрой за 10 дней", "Число 0-100 + резюме. ВНИМАНИЕ: должен возвращать строгий JSON. Файл: prompts/dynmood.md", "prompt", 6)
agent_config.register("diary_feedback_prompt", "", "Отклик на запись дневника", "Короткое ревью без вопросов. Файл: prompts/diary_feedback.md", "prompt", 7)
agent_config.register("diary_polish_prompt", "", "Чистка записи дневника", "Орфография/пунктуация без смены смысла. Файл: prompts/diary_polish.md", "prompt", 8)
agent_config.register("insights_notes_prompt", "", "Живые заметки о клиенте", "Само-обучение: что агент запоминает между сессиями. Файл: prompts/insights_notes.md", "prompt", 9)

client = Anthropic()  # для нестримовых вызовов (weekly/opener)

PORT = int(os.environ.get("PORT", "8080"))
WEBAPP_DIR = ROOT / "webapp"
DIALOG_LIMIT = 30
MOOD_MIN_SESSIONS = 0       # MOOD-оценка: открыта сразу (считается, если пройден тест)
ANALYTICS_MIN_DAYS = 0      # аналитика открыта сразу
DYN_MOOD_DAYS = 10          # окно/период пересчёта динамичного MOOD по дневнику
DOC_MAX_BYTES = 1_000_000   # лимит на один файл
DOC_TOTAL_BYTES = 5_000_000 # суммарный лимит досье
PULSE_SCORES = [12, 32, 55, 78, 95]  # пульс 1..5 → MOOD-шкала 0-100
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
# telegram-id владельца → его Google-акк. Берём OWNER_TG_ID, иначе уже существующий TELEGRAM_USER_ID.
OWNER_TG_ID = (os.environ.get("OWNER_TG_ID", "") or os.environ.get("TELEGRAM_USER_ID", "")).strip()
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "steadfast.sound001@gmail.com").strip().lower()


_DYN_COMPUTING = set()   # uid'ы, для которых динамичный MOOD сейчас считается в фоне
_DYN_LOCK = threading.Lock()


def _dyn_mood_compute(uid, entries):
    """Фоновый подсчёт настроя за 10 дней по дневнику + перепискам с психологом. Кэширует."""
    try:
        now = time.time()
        diary_blob = "\n".join(f"— {e['text'][:600]}" for e in entries[-30:])
        # реплики самого клиента из чата за окно
        msgs = store.recent_messages(uid, 80)
        chat_lines = [m["content"] for m in msgs if m.get("role") == "user"][-40:]
        chat_blob = "\n".join(f"— {c[:400]}" for c in chat_lines)
        blob = "[записи дневника]\n" + (diary_blob or "(нет)") + \
               "\n\n[реплики в разговорах с психологом]\n" + (chat_blob or "(нет)")
        sys = agent_config.cfg("dynmood_prompt")
        resp = client.messages.create(
            system=sys, messages=[{"role": "user", "content": blob}],
            max_tokens=400, task="fast",
        )
        raw = resp.content[0].text.strip()
        m = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        score = max(0, min(100, int(m.get("score"))))
        note = str(m.get("note") or "").strip()[:160]
        desc = str(m.get("desc") or "").strip()[:600]
        store.set_dyn_mood(uid, {"score": score, "note": note, "desc": desc,
                                 "n": len(entries) + len(chat_lines), "ts": now})
    except Exception as e:
        print(f"[dyn_mood] compute fail uid={uid}: {e}", flush=True)
    finally:
        with _DYN_LOCK:
            _DYN_COMPUTING.discard(uid)


_LEARN_RUNNING = set()    # uid'ы, для которых сейчас идёт пере-осмысление профиля
_LEARN_MIN_GAP = 1800     # не чаще раза в 30 минут


def _learn_bg(uid):
    """Само-обучение: агент обновляет живые заметки о клиенте из последних сессий."""
    try:
        msgs = store.recent_messages(uid, 40)
        if not msgs:
            return
        convo = "\n".join(
            f"{'клиент' if m.get('role') == 'user' else 'психолог'}: {m.get('content','')[:400]}"
            for m in msgs[-30:]
        )
        prior = store.get_insights(uid)
        sys = agent_config.cfg("insights_notes_prompt")
        u = f"[прошлые заметки]\n{prior or '(пусто)'}\n\n[последние реплики]\n{convo}"
        resp = client.messages.create(
            system=sys, messages=[{"role": "user", "content": u}],
            max_tokens=700, task="fast",
        )
        out = resp.content[0].text.strip()[:1600]
        if out:
            store.set_insights(uid, out)
    except Exception as e:
        print(f"[learn] fail uid={uid}: {e}", flush=True)
    finally:
        with _DYN_LOCK:
            _LEARN_RUNNING.discard(uid)


def _compile_inputs(uid):
    """Все источники о клиенте для сборки портрета: тесты + досье + дневник + что сам сказал."""
    prof = store.get_profile(uid)
    try:
        answers = json.loads(prof.get("test_answers") or "{}")
    except Exception:
        answers = {}
    return (answers, prof.get("raw_info") or "", store.get_extra_tests(uid),
            store.documents_text(uid), store.diary_text_blob(uid),
            store.portrait_feedback_blob(uid))


def _all_tests_done(uid):
    """Портрет/MOOD открываются только когда пройдены первичный + все доп-тесты."""
    prof = store.get_profile(uid)
    try:
        answers = json.loads(prof.get("test_answers") or "{}")
    except Exception:
        answers = {}
    extra = store.get_extra_tests(uid)
    return bool(answers) and all(t["id"] in extra for t in onboarding.EXTRA_TESTS)


def _recompile_bg(uid):
    """Фоновая пересборка портрета из ВСЕХ источников (тесты, досье, дневник, raw_info)."""
    try:
        if not _all_tests_done(uid):   # портрет не строим, пока не пройдены все тесты
            return
        compiled = onboarding.compile_profile(*_compile_inputs(uid))
        if compiled:
            store.set_compiled(uid, compiled)
    except Exception as e:
        print(f"[recompile] fail uid={uid}: {e}", flush=True)


def _maybe_learn(uid):
    """Запускает пере-осмысление в фоне, не чаще раза в 30 мин и не параллельно."""
    if time.time() - store.get_insights_at(uid) < _LEARN_MIN_GAP:
        return
    with _DYN_LOCK:
        if uid in _LEARN_RUNNING:
            return
        _LEARN_RUNNING.add(uid)
    threading.Thread(target=_learn_bg, args=(uid,), daemon=True).start()


_RECOMPILE_RUNNING = set()


def _maybe_recompile(uid):
    """Фоновая пересборка портрета без дублей (дневник/досье изменились)."""
    with _DYN_LOCK:
        if uid in _RECOMPILE_RUNNING:
            return
        _RECOMPILE_RUNNING.add(uid)

    def run():
        try:
            _recompile_bg(uid)
        finally:
            with _DYN_LOCK:
                _RECOMPILE_RUNNING.discard(uid)
    threading.Thread(target=run, daemon=True).start()


def _verify_telegram(init_data: str) -> dict | None:
    """Валидирует Telegram WebApp initData по HMAC (ботовый токен). Возвращает tg-user или None."""
    if not TELEGRAM_TOKEN or not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    recv_hash = pairs.pop("hash", None)
    if not recv_hash:
        return None
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash):
        return None
    try:
        return json.loads(pairs.get("user") or "{}") or None
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    # ── helpers ──
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bearer(self):
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.startswith("Bearer ") else ""

    def _owner(self):
        """Возвращает пользователя только если он владелец (по OWNER_EMAIL). Иначе None."""
        u = store.user_by_token(self._bearer())
        if u and (u.get("email") or "").strip().lower() == OWNER_EMAIL:
            return u
        return None

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except Exception:
            n = 0
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def _base_url(self):
        if PUBLIC_URL:
            return PUBLIC_URL
        proto = self.headers.get("X-Forwarded-Proto", "https")
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", f"localhost:{PORT}")
        return f"{proto}://{host}"

    def _redirect(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.end_headers()

    def _send_file(self, path: Path):
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
        if path.suffix in (".png", ".jpg", ".jpeg", ".woff", ".woff2", ".ico"):
            # картинки/шрифты не меняются — браузеру можно держать сутки
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            # код подключается с ?v=N, но сам файл не кэшируем — никакого залипания
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
        # gzip для текстовых ответов: app.js 90КБ → ~25КБ, заметно на холодном старте
        if path.suffix in (".js", ".css", ".html", ".svg", ".json") and len(data) > 1024 \
                and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            import gzip as _gz
            data = _gz.compress(data, 6)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _build_stats(self, uid):
        prof = store.get_profile(uid)
        extra = store.get_extra_tests(uid)
        try:
            answers = json.loads(prof.get("test_answers") or "{}")
        except Exception:
            answers = {}
        st = store.chat_stats(uid)
        sessions = st["sessions"]
        days = st["days_since_reg"]
        streak = st.get("streak", 0)
        # анализ (портрет + MOOD) открывается только когда пройдены ВСЕ тесты:
        # первичный + все доп-тесты.
        onboard_done = bool(answers)
        extra_total = len(onboarding.EXTRA_TESTS)
        extra_done = sum(1 for t in onboarding.EXTRA_TESTS if t["id"] in extra)
        all_tests_done = onboard_done and extra_done == extra_total
        tests_total = extra_total + 1
        tests_passed = extra_done + (1 if onboard_done else 0)
        # итоговый MOOD = база из тестов + актуальное состояние из дневника и разговоров.
        # тесты дают устойчивую черту, dyn-mood (LLM по дневнику+чату) — текущее состояние.
        test_mood = onboarding.compute_mood(answers, extra) if sessions >= MOOD_MIN_SESSIONS else None
        dyn = store.get_dyn_mood(uid)
        dyn_score = dyn.get("score") if dyn else None
        parts = []
        if test_mood is not None:
            parts.append((test_mood, 0.5))                  # черта/базлайн
        if isinstance(dyn_score, (int, float)):
            parts.append((float(dyn_score), 0.5))           # актуальное состояние (дневник+терапия)
        mood = round(sum(v * w for v, w in parts) / sum(w for _, w in parts)) if parts else None
        if not all_tests_done:
            mood = None              # MOOD закрыт, пока не пройдены все тесты
        portrait_done = bool((prof.get("compiled") or "").strip())
        tests_done = {t["id"]: (t["id"] in extra) for t in onboarding.EXTRA_TESTS}
        return {
            "sessions": sessions, "user_msgs": st["user_msgs"], "days_since_reg": round(days, 1),
            "streak": streak,
            "mood": mood, "mood_remaining": max(0, MOOD_MIN_SESSIONS - sessions),
            "mood_base": test_mood, "mood_dynamic": dyn_score,
            "mood_today": store.mood_today(uid),
            "mood_history": store.mood_history(uid, 30),
            "tests": tests_done, "portrait": portrait_done,
            "analytics_unlocked": days >= ANALYTICS_MIN_DAYS,
            "analytics_in_days": max(0, round(ANALYTICS_MIN_DAYS - days, 1)),
            "onboard_test_done": onboard_done,
            "all_tests_done": all_tests_done,
            "tests_total": tests_total, "tests_passed": tests_passed,
        }

    def _chat_stream(self, uid, text):
        """Стримит ответ психолога чанками (text/plain), затем сохраняет диалог."""
        prof = store.get_profile(uid)
        insights = store.get_insights(uid)
        digest = store.msg_feedback_digest(uid)         # лайки/дизлайки → агент подстраивается на лету
        if digest:
            insights = (insights + "\n\n" if insights else "") + "[реакции клиента на твои прошлые ответы]\n" + digest
        messages = store.recent_messages(uid, 20) + [{"role": "user", "content": text}]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        acc = []
        # ДВА АГЕНТА: 1) аналитик собирает суть → 2) Sonnet-редактор доводит до голоса и стримит.
        on, _editor_model, _ = _humanize_cfg()
        cap = agent_config.cfg_int("chat_max_tokens", 700)
        # риск считаем в коде до LLM: в кризисе потолок ответа поднимается, иначе
        # девятишаговый протокол физически не помещается и обрывается на полуслове.
        tier = safety.detect(text, [m["content"] for m in messages[:-1] if m.get("role") == "user"])
        cap = safety.policy_for(tier, cap)["max_tokens"]
        try:
            if on:
                # агент 1 — аналитик (task=dialog → model_chat), полный контекст, не стримим клиенту
                draft = trim_incomplete("".join(stream_completion_sync(
                    system=user_system(prof.get("compiled", ""), insights),
                    messages=messages, max_tokens=cap, task="dialog",
                )).strip())
                # агент 2 — Sonnet-редактор: правит черновик с учётом реплики клиента, стримит
                gen = humanize_stream(draft, user_msg=text, max_tokens=cap + 200)
            else:
                # один проход — быстрее, суше
                gen = stream_completion_sync(
                    system=user_system(prof.get("compiled", ""), insights),
                    messages=messages, max_tokens=cap, task="dialog",
                )
            for delta in sentence_guard(gen):
                acc.append(delta)
                try:
                    self.wfile.write(delta.encode("utf-8")); self.wfile.flush()
                except Exception:
                    break
        except Exception as e:
            try:
                self.wfile.write(f"\n[сломалось: {e}]".encode("utf-8"))
            except Exception:
                pass
        reply = "".join(acc).strip()
        # в кризисе телефон обязан быть в ответе. модель могла его не дать — дописываем.
        fixed = safety.guarantee(reply, tier)
        if fixed != reply:
            try:
                self.wfile.write(fixed[len(reply):].encode("utf-8")); self.wfile.flush()
            except Exception:
                pass
            reply = fixed
            print(f"[safety] uid={uid} tier={tier}: дописал номер в ответ", flush=True)
        if reply:
            store.add_message(uid, "user", text)
            store.add_message(uid, "assistant", reply)
            _maybe_learn(uid)  # фоновое само-обучение по свежему разговору

    def _admin_test_chat(self, uid, body):
        """Песочница владельца: тот же системный промпт и модель, что в проде,
        но БЕЗ записи в историю и без само-обучения. Для проверки правок промптов.
        История диалога приходит с клиента (не персистится)."""
        text = (body.get("q") or "").strip()
        if not text:
            self._json(400, {"error": "empty"}); return
        prof = store.get_profile(uid)
        insights = store.get_insights(uid)
        messages = []
        for m in (body.get("history") or [])[-20:]:
            role = "user" if m.get("role") == "user" else "assistant"
            content = (m.get("content") or "").strip()
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})
        model = (body.get("model") or "").strip() or None   # A/B: прогон через конкретную модель
        ov = body.get("overrides")                           # тумблеры песочницы: {key: "" = выкл, или новое значение}
        if isinstance(ov, dict):
            agent_config.set_overrides(ov)
        else:
            agent_config.clear_overrides()
        sys_blocks = user_system(prof.get("compiled", ""), insights)
        max_tok = agent_config.cfg_int("chat_max_tokens", 700)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for delta in stream_completion_sync(
                system=sys_blocks, messages=messages, max_tokens=max_tok,
                task="dialog", model=model,
            ):
                try:
                    self.wfile.write(delta.encode("utf-8")); self.wfile.flush()
                except Exception:
                    break
        except Exception as e:
            try:
                self.wfile.write(f"\n[сломалось: {e}]".encode("utf-8"))
            except Exception:
                pass
        finally:
            agent_config.clear_overrides()                   # не течёт на следующие запросы

    def _transcribe(self):
        """Распознаёт голос (сырые байты аудио) через Groq Whisper → {"text": ...}."""
        if not store.user_by_token(self._bearer()):
            self._json(401, {"error": "unauthorized"}); return
        if not stt.enabled():
            self._json(503, {"error": "распознавание не настроено (нет GROQ_API_KEY)"}); return
        try:
            n = int(self.headers.get("Content-Length", 0))
        except Exception:
            n = 0
        if n <= 0 or n > 25 * 1024 * 1024:
            self._json(400, {"error": "пустой или слишком большой аудиофайл"}); return
        audio = self.rfile.read(n)
        ct = (self.headers.get("Content-Type") or "").lower()
        ext = "ogg" if "ogg" in ct else "mp4" if ("mp4" in ct or "m4a" in ct) else "webm"
        try:
            text = stt.transcribe(audio, filename=f"voice.{ext}")
            self._json(200, {"text": text}); return
        except Exception as e:
            self._json(502, {"error": str(e)}); return

    def _opener(self, uid):
        """Короткая личная фраза для пустого чата: по профилю + паузе с прошлого раза."""
        prof = store.get_profile(uid)
        msgs = store.recent_messages(uid, 1)
        compiled = (prof.get("compiled") or "").strip()
        if not msgs:
            hint = "это первый разговор. поздоровайся коротко, по-человечески, и задай один открытый вопрос про то, что привело."
        else:
            hint = "вы уже общались. открой разговор живой личной фразой и одним точным вопросом — без «чем могу помочь»."
        sys = user_system(compiled, store.get_insights(uid))
        try:
            resp = client.messages.create(
                system=sys,
                messages=[{"role": "user", "content": f"[служебное: сгенерируй ТОЛЬКО первую реплику-открытие, 1 строка. {hint}]"}],
                max_tokens=120, task="dialog",
            )
            return trim_incomplete(resp.content[0].text.strip())
        except Exception:
            return "с чего начнём сегодня?"

    def _weekly(self, uid):
        """Рефлексия психолога за последние 7 дней по сообщениям клиента."""
        rows = store.recent_messages(uid, 120)
        user_texts = [m["content"] for m in rows if m.get("role") == "user"]
        if len(user_texts) < 3:
            return ""
        blob = "\n".join(f"— {t}" for t in user_texts[-40:])
        sys = agent_config.cfg("weekly_prompt")
        try:
            resp = client.messages.create(
                system=sys, messages=[{"role": "user", "content": blob}],
                max_tokens=1000, task="reasoning",   # Pro: forced-reasoning ест часть бюджета
            )
            return humanize_text(resp.content[0].text.strip(), max_tokens=1100)  # Sonnet → человечнее
        except Exception as e:
            return f"не удалось собрать: {e}"

    def _dynamic_mood(self, uid):
        """Настрой за 10 дней по дневнику. НЕ блокирует: LLM-подсчёт уходит в фон,
        ответ отдаётся сразу (кэш / pending). Пересчёт раз в 10 дней."""
        now = time.time()
        win = DYN_MOOD_DAYS * 86400
        cached = store.get_dyn_mood(uid)
        if cached and (now - cached.get("ts", 0)) < win:
            left = max(0, DYN_MOOD_DAYS - int((now - cached.get("ts", 0)) // 86400))
            return {**cached, "days_left": left}
        entries = store.diary_since(uid, now - win)
        user_msgs = [m for m in store.recent_messages(uid, 20) if m.get("role") == "user"]
        signals = len(entries) + len(user_msgs)
        if signals < 3:  # из 1-2 записей честную оценку не дать
            if cached:
                return {**cached, "days_left": 0, "stale": True}
            return {"score": None,
                    "note": f"настрой посчитается, когда наберётся больше записей и разговоров ({signals} из 3)",
                    "n": signals, "days_left": DYN_MOOD_DAYS}
        # данных достаточно, но кэш пуст/устарел → считаем в фоне, ответ не ждёт LLM
        with _DYN_LOCK:
            fresh = uid not in _DYN_COMPUTING
            if fresh:
                _DYN_COMPUTING.add(uid)
        if fresh:
            threading.Thread(target=_dyn_mood_compute, args=(uid, entries), daemon=True).start()
        if cached:
            return {**cached, "days_left": 0, "stale": True}
        return {"score": None, "note": "считаю настрой по дневнику — загляни через минуту",
                "n": len(entries), "days_left": DYN_MOOD_DAYS, "pending": True}

    def _diary_feedback(self, text):
        """Короткий психологический отклик на запись дневника (1-2 строки, голос психолога)."""
        sys = agent_config.cfg("diary_feedback_prompt")
        try:
            resp = client.messages.create(
                system=sys, messages=[{"role": "user", "content": text[:4000]}],
                max_tokens=220, task="fast",
            )
            return trim_incomplete(humanize_text(resp.content[0].text.strip(), max_tokens=300)[:400])  # Sonnet → человечнее
        except Exception:
            return ""

    def _diary_polish(self, raw):
        """Бот бережно вычищает запись дневника: орфография, пунктуация, абзацы.
        Смысл, тон и голос автора не меняет. При сбое — возвращает исходник."""
        sys = agent_config.cfg("diary_polish_prompt")
        try:
            resp = client.messages.create(
                system=sys, messages=[{"role": "user", "content": raw}],
                max_tokens=1200, task="fast",
            )
            out = resp.content[0].text.strip()
            return out or raw
        except Exception:
            return raw

    # ── GET ──
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/api/health":
            self._json(200, {"ok": True, "db": "turso" if store._turso_on() else "sqlite"}); return
        if p == "/api/auth/google/enabled":
            self._json(200, {"enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)}); return
        if p == "/api/auth/google":
            self._google_redirect(u); return
        if p == "/api/auth/google/callback":
            self._google_callback(u); return
        if p == "/api/onboarding/questions":
            self._json(200, {"questions": onboarding.questions_public()}); return
        if p == "/api/tests":
            self._json(200, {"tests": onboarding.extra_tests_public()}); return
        if p == "/api/me":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            prof = store.get_profile(user["id"])
            self._json(200, {"user": user, "onboarded": bool(prof.get("onboarded")),
                             "compiled": prof.get("compiled", "")}); return
        if p == "/api/stats":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, self._build_stats(user["id"])); return
        if p == "/api/documents":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, {"documents": store.list_documents(user["id"]),
                             "total": store.documents_total(user["id"]),
                             "limit": DOC_TOTAL_BYTES}); return
        if p == "/api/v2/dynamic-mood":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, self._dynamic_mood(user["id"])); return
        if p == "/api/v2/messages":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, {"messages": store.recent_messages(user["id"], 100)}); return
        if p == "/api/admin/overview":
            if not self._owner():
                self._json(403, {"error": "forbidden"}); return
            self._json(200, {"owner_email": OWNER_EMAIL, "users": store.admin_overview()}); return
        if p == "/api/admin/config":
            if not self._owner():
                self._json(403, {"error": "forbidden"}); return
            self._json(200, {"items": agent_config.all_items()}); return
        if p == "/api/admin/user":
            if not self._owner():
                self._json(403, {"error": "forbidden"}); return
            try:
                tid = int(parse_qs(u.query).get("id", [""])[0])
            except Exception:
                self._json(400, {"error": "bad id"}); return
            self._json(200, store.admin_user_detail(tid)); return
        if p == "/api/v2/opener":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, {"text": self._opener(user["id"])}); return
        if p == "/api/diary":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, {"entries": store.list_diary_entries(user["id"])}); return
        # статика
        rel = p.lstrip("/") or "index.html"
        target = (WEBAPP_DIR / rel).resolve()
        try:
            target.relative_to(WEBAPP_DIR.resolve())
        except ValueError:
            self.send_error(403); return
        if not target.is_file():
            # SPA-fallback на index
            target = WEBAPP_DIR / "index.html"
            if not target.is_file():
                self.send_error(404); return
        self._send_file(target)

    # ── POST ──
    def do_POST(self):
        u = urlparse(self.path)
        # транскрипция голоса читает СЫРЫЕ байты — до json-парсинга _body()
        if u.path == "/api/v2/transcribe":
            self._transcribe(); return
        body = self._body()
        try:
            if u.path == "/api/auth/register":
                email = (body.get("email") or "").strip().lower()
                pw = body.get("password") or ""
                if not email or len(pw) < 4:
                    self._json(400, {"error": "нужен email и пароль от 4 символов"}); return
                user = store.create_user(email, pw, (body.get("name") or "").strip())
                if not user:
                    self._json(409, {"error": "email уже занят"}); return
                self._json(200, {"token": store.create_session(user["id"]), "user": user}); return

            if u.path == "/api/auth/telegram":
                # нативный вход из Telegram mini-app: Google OAuth внутри webview Telegram блокирует.
                tg_user = _verify_telegram(body.get("initData") or "")
                if not tg_user or not tg_user.get("id"):
                    self._json(401, {"error": "telegram auth failed"}); return
                tgid = str(tg_user["id"])
                name = (tg_user.get("first_name") or "").strip()
                # tg-id владельца → его Google-аккаунт (единая база); прочие → изолированный tg-акк
                email = OWNER_EMAIL if (OWNER_TG_ID and tgid == OWNER_TG_ID) else f"tg{tgid}@telegram.local"
                user = store.get_or_create_oauth_user(email, name or "telegram")
                prof = store.get_profile(user["id"])
                self._json(200, {"token": store.create_session(user["id"]), "user": user,
                                 "onboarded": bool(prof.get("onboarded"))}); return

            if u.path == "/api/auth/login":
                user = store.verify_user((body.get("email") or "").strip().lower(), body.get("password") or "")
                if not user:
                    self._json(401, {"error": "неверный email или пароль"}); return
                prof = store.get_profile(user["id"])
                self._json(200, {"token": store.create_session(user["id"]), "user": user,
                                 "onboarded": bool(prof.get("onboarded"))}); return

            if u.path == "/api/admin/config":
                if not self._owner():
                    self._json(403, {"error": "forbidden"}); return
                key = (body.get("key") or "").strip()
                if not key:
                    self._json(400, {"error": "no key"}); return
                if body.get("reset"):
                    agent_config.reset_item(key)
                else:
                    agent_config.set_item(key, body.get("value") or "")
                self._json(200, {"ok": True, "items": agent_config.all_items()}); return

            if u.path == "/api/admin/test-chat":
                owner = self._owner()
                if not owner:
                    self._json(403, {"error": "forbidden"}); return
                self._admin_test_chat(owner["id"], body); return

            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            uid = user["id"]

            if u.path == "/api/onboarding/submit":
                # сохраняем ответы, помечаем онбординг пройденным. Портрет НЕ компилируем —
                # это делается по запросу через /api/profile/compile.
                answers = body.get("answers") or {}
                raw_info = body.get("raw_info") or ""
                store.save_test_answers(uid, answers)
                if raw_info:
                    store.save_raw_info(uid, raw_info)
                store.set_compiled(uid, "")  # onboarded=1, портрет соберётся в фоне
                threading.Thread(target=_recompile_bg, args=(uid,), daemon=True).start()
                self._json(200, {"ok": True}); return

            if u.path == "/api/profile/compile":
                if not _all_tests_done(uid):
                    self._json(403, {"error": "пройди все тесты — тогда соберём портрет"}); return
                try:
                    compiled = onboarding.compile_profile(*_compile_inputs(uid))
                    store.set_compiled(uid, compiled)
                    self._json(200, {"ok": True, "compiled": compiled}); return
                except Exception as e:
                    self._json(500, {"error": str(e)}); return

            if u.path == "/api/profile/feedback":
                liked = bool(body.get("liked", True))
                fb_text = (body.get("text") or "").strip()[:2000]
                store.add_portrait_feedback(uid, liked, fb_text)
                # пересобираем портрет в фоне — агент учтёт отзыв и напишет точнее
                threading.Thread(target=_recompile_bg, args=(uid,), daemon=True).start()
                self._json(200, {"ok": True}); return

            if u.path == "/api/profile/info":
                store.save_raw_info(uid, body.get("raw_info") or "")
                threading.Thread(target=_recompile_bg, args=(uid,), daemon=True).start()
                self._json(200, {"ok": True}); return

            if u.path == "/api/tests/submit":
                tid = (body.get("test_id") or "").strip()
                tans = body.get("answers") or {}
                valid = {t["id"] for t in onboarding.EXTRA_TESTS}
                if tid not in valid:
                    self._json(400, {"error": "unknown test"}); return
                extra = store.get_extra_tests(uid)
                extra[tid] = tans
                store.save_extra_tests(uid, extra)
                threading.Thread(target=_recompile_bg, args=(uid,), daemon=True).start()
                self._json(200, {"ok": True, "stats": self._build_stats(uid)}); return

            if u.path == "/api/documents":
                name = (body.get("name") or "файл").strip()[:120]
                content = body.get("content") or ""
                size = len(content.encode("utf-8"))
                if size == 0:
                    self._json(400, {"error": "пустой файл"}); return
                if size > DOC_MAX_BYTES:
                    self._json(413, {"error": "файл больше 1 МБ"}); return
                if store.documents_total(uid) + size > DOC_TOTAL_BYTES:
                    self._json(413, {"error": "досье переполнено (лимит 5 МБ)"}); return
                store.add_document(uid, name, content)
                self._json(200, {"ok": True, "documents": store.list_documents(uid),
                                 "total": store.documents_total(uid)}); return

            if u.path == "/api/documents/delete":
                try:
                    did = int(body.get("id"))
                except Exception:
                    self._json(400, {"error": "bad id"}); return
                store.delete_document(uid, did)
                self._json(200, {"ok": True, "documents": store.list_documents(uid),
                                 "total": store.documents_total(uid)}); return

            if u.path == "/api/v2/chat":
                text = (body.get("q") or "").strip()
                if not text:
                    self._json(400, {"error": "empty"}); return
                self._chat_stream(uid, text); return

            if u.path == "/api/v2/feedback":          # лайк/дизлайк на ответ психолога
                store.add_msg_feedback(uid, bool(body.get("liked")), body.get("text") or "")
                self._json(200, {"ok": True}); return

            if u.path == "/api/mood/checkin":
                try:
                    n = int(body.get("score"))
                except Exception:
                    self._json(400, {"error": "bad score"}); return
                n = max(1, min(5, n))
                store.log_mood(uid, PULSE_SCORES[n - 1], "pulse")
                self._json(200, {"ok": True, "stats": self._build_stats(uid)}); return

            if u.path == "/api/v2/weekly":
                self._json(200, {"text": self._weekly(uid)}); return

            if u.path == "/api/diary":
                raw = (body.get("text") or "").strip()
                if not raw:
                    self._json(400, {"error": "empty"}); return
                if len(raw) > 8000:
                    raw = raw[:8000]
                # сохраняем сразу с сырым текстом — ответ быстрый, без ожидания LLM
                entry = store.add_diary_entry(uid, raw, raw)
                # в фоне: чистка орфографии + психологический отклик
                eid = entry.get("id")

                def _polish_bg(uid=uid, eid=eid, raw=raw):
                    try:
                        clean = self._diary_polish(raw)
                        if clean and clean != raw and eid is not None:
                            store.update_diary_text(uid, eid, clean)
                        fb = self._diary_feedback(clean if clean else raw)
                        if fb and eid is not None:
                            store.set_diary_feedback(uid, eid, fb)
                    except Exception as e:
                        print(f"[diary] bg failed uid={uid} id={eid}: {e}", flush=True)

                threading.Thread(target=_polish_bg, daemon=True).start()
                _maybe_recompile(uid)   # дневник — источник портрета, обновляем фоном
                self._json(200, {"ok": True, "entry": entry,
                                 "entries": store.list_diary_entries(uid)}); return

            if u.path == "/api/diary/update":
                try:
                    eid = int(body.get("id"))
                except Exception:
                    self._json(400, {"error": "bad id"}); return
                text = (body.get("text") or "").strip()[:8000]
                if not text:
                    self._json(400, {"error": "empty"}); return
                store.update_diary_text(uid, eid, text)
                self._json(200, {"ok": True, "entries": store.list_diary_entries(uid)}); return

            if u.path == "/api/diary/delete":
                try:
                    eid = int(body.get("id"))
                except Exception:
                    self._json(400, {"error": "bad id"}); return
                store.delete_diary_entry(uid, eid)
                self._json(200, {"ok": True, "entries": store.list_diary_entries(uid)}); return

            self._json(404, {"error": "not found"})
        except Exception as e:
            self._json(500, {"error": str(e)})

    # ── google oauth ──
    def _google_redirect(self, u=None):
        if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
            self._json(400, {"error": "google не настроен"}); return
        # вход из нативного приложения (?app=1) → state=app, токен вернём на soulauth://
        app = ""
        try:
            app = parse_qs(u.query).get("app", [""])[0] if u is not None else ""
        except Exception:
            app = ""
        p = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": self._base_url() + "/api/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account",
        }
        if app == "1":
            p["state"] = "app"
        self._redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(p))

    def _google_callback(self, u):
        import httpx
        q = parse_qs(u.query)
        code = q.get("code", [""])[0]
        is_app = q.get("state", [""])[0] == "app"   # вход из нативного приложения
        base = self._base_url()
        # куда вернуть: в приложение по custom-scheme или в веб
        def dest(query):
            return (f"soulauth://callback?{query}" if is_app else base + f"/?{query}")
        if not code:
            self._redirect(dest("auth_error=1")); return
        try:
            with httpx.Client(timeout=30) as cli:
                tok = cli.post("https://oauth2.googleapis.com/token", data={
                    "code": code, "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": base + "/api/auth/google/callback",
                    "grant_type": "authorization_code",
                }).json()
                access = tok.get("access_token")
                if not access:
                    self._redirect(dest("auth_error=token")); return
                info = cli.get("https://www.googleapis.com/oauth2/v2/userinfo",
                               headers={"Authorization": "Bearer " + access}).json()
            email = info.get("email")
            if not email:
                self._redirect(dest("auth_error=email")); return
            user = store.get_or_create_oauth_user(email, info.get("name") or "")
            token = store.create_session(user["id"])
            prof = store.get_profile(user["id"])
            self._redirect(dest(f"token={token}&onb={1 if prof.get('onboarded') else 0}"))
        except Exception as e:
            print("google callback error:", e, flush=True)
            self._redirect(dest("auth_error=server"))


def main():
    store.init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"SaaS-сервер на :{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
