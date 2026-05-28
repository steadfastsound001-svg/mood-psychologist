"""Standalone SaaS-сервер психолога. Без Telegram/whisper/Apple Notes — деплоится на любой Python-хостинг.

Эндпойнты: health, auth (register/login/google), onboarding, profile, v2/chat, статика webapp/.
Порт из ENV PORT (Fly/Render дают 8080). SQLite в data/ (на Fly — persistent volume).
"""
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)

import store
import onboarding
from llm import Anthropic, stream_completion_sync
from agent_core import user_system

client = Anthropic()  # для нестримовых вызовов (weekly/opener)

PORT = int(os.environ.get("PORT", "8080"))
WEBAPP_DIR = ROOT / "webapp"
DIALOG_LIMIT = 30
MOOD_MIN_SESSIONS = 10      # MOOD-оценка открывается после N сеансов
ANALYTICS_MIN_DAYS = 10     # аналитика открывается после N дней
DOC_MAX_BYTES = 1_000_000   # лимит на один файл
DOC_TOTAL_BYTES = 5_000_000 # суммарный лимит досье
PULSE_SCORES = [12, 32, 55, 78, 95]  # пульс 1..5 → MOOD-шкала 0-100
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")


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
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
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
        mood = onboarding.compute_mood(answers, extra) if sessions >= MOOD_MIN_SESSIONS else None
        portrait_done = bool((prof.get("compiled") or "").strip())
        tests_done = {t["id"]: (t["id"] in extra) for t in onboarding.EXTRA_TESTS}
        ach = [{"id": "start", "icon": "🚀", "label": "старт", "got": bool(prof.get("onboarded"))}]
        for t in onboarding.EXTRA_TESTS:
            a = t["achievement"]
            ach.append({"id": t["id"], "icon": a["icon"], "label": a["label"], "got": t["id"] in extra})
        ach.append({"id": "portrait", "icon": "🎨", "label": "портрет собран", "got": portrait_done})
        ach.append({"id": "streak7", "icon": "🔥", "label": "7 дней подряд", "got": streak >= 7})
        ach.append({"id": "sessions10", "icon": "💬", "label": "10 сеансов", "got": sessions >= MOOD_MIN_SESSIONS})
        return {
            "sessions": sessions, "user_msgs": st["user_msgs"], "days_since_reg": round(days, 1),
            "streak": streak,
            "mood": mood, "mood_remaining": max(0, MOOD_MIN_SESSIONS - sessions),
            "mood_today": store.mood_today(uid),
            "mood_history": store.mood_history(uid, 30),
            "tests": tests_done, "portrait": portrait_done,
            "analytics_unlocked": days >= ANALYTICS_MIN_DAYS,
            "analytics_in_days": max(0, round(ANALYTICS_MIN_DAYS - days, 1)),
            "achievements": ach,
        }

    def _chat_stream(self, uid, text):
        """Стримит ответ психолога чанками (text/plain), затем сохраняет диалог."""
        prof = store.get_profile(uid)
        messages = store.recent_messages(uid, 20) + [{"role": "user", "content": text}]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        acc = []
        try:
            for delta in stream_completion_sync(
                system=user_system(prof.get("compiled", "")),
                messages=messages, max_tokens=220, task="dialog",
            ):
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
        if reply:
            store.add_message(uid, "user", text)
            store.add_message(uid, "assistant", reply)

    def _opener(self, uid):
        """Короткая личная фраза для пустого чата: по профилю + паузе с прошлого раза."""
        prof = store.get_profile(uid)
        msgs = store.recent_messages(uid, 1)
        compiled = (prof.get("compiled") or "").strip()
        if not msgs:
            hint = "это первый разговор. поздоровайся коротко, по-человечески, и задай один открытый вопрос про то, что привело."
        else:
            hint = "вы уже общались. открой разговор живой личной фразой и одним точным вопросом — без «чем могу помочь»."
        sys = user_system(compiled)
        try:
            resp = client.messages.create(
                system=sys,
                messages=[{"role": "user", "content": f"[служебное: сгенерируй ТОЛЬКО первую реплику-открытие, 1 строка. {hint}]"}],
                max_tokens=80, task="dialog",
            )
            return resp.content[0].text.strip()
        except Exception:
            return "с чего начнём сегодня?"

    def _weekly(self, uid):
        """Рефлексия психолога за последние 7 дней по сообщениям клиента."""
        import time as _t
        cutoff = _t.time() - 7 * 86400
        rows = store.recent_messages(uid, 120)
        user_texts = [m["content"] for m in rows if m.get("role") == "user"]
        if len(user_texts) < 3:
            return ""
        blob = "\n".join(f"— {t}" for t in user_texts[-40:])
        sys = ("ты психолог. на входе — реплики клиента за неделю. напиши короткие тёплые итоги недели "
               "(3-5 строк, на «ты», строчные, без воды и без markdown кроме **жирного**): что было в фокусе, "
               "какой сдвиг заметен, один мягкий ориентир на следующую неделю. только из реплик, не выдумывай.")
        try:
            resp = client.messages.create(
                system=sys, messages=[{"role": "user", "content": blob}],
                max_tokens=400, task="reasoning",
            )
            return resp.content[0].text.strip()
        except Exception as e:
            return f"не удалось собрать: {e}"

    # ── GET ──
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/api/health":
            self._json(200, {"ok": True, "db": "turso" if store._turso_on() else "sqlite"}); return
        if p == "/api/auth/google/enabled":
            self._json(200, {"enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)}); return
        if p == "/api/auth/google":
            self._google_redirect(); return
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
        if p == "/api/v2/opener":
            user = store.user_by_token(self._bearer())
            if not user:
                self._json(401, {"error": "unauthorized"}); return
            self._json(200, {"text": self._opener(user["id"])}); return
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

            if u.path == "/api/auth/login":
                user = store.verify_user((body.get("email") or "").strip().lower(), body.get("password") or "")
                if not user:
                    self._json(401, {"error": "неверный email или пароль"}); return
                prof = store.get_profile(user["id"])
                self._json(200, {"token": store.create_session(user["id"]), "user": user,
                                 "onboarded": bool(prof.get("onboarded"))}); return

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
                store.set_compiled(uid, "")  # onboarded=1, портрет пустой
                self._json(200, {"ok": True}); return

            if u.path == "/api/profile/compile":
                prof = store.get_profile(uid)
                try:
                    answers = json.loads(prof.get("test_answers") or "{}")
                except Exception:
                    answers = {}
                raw_info = prof.get("raw_info") or ""
                extra = store.get_extra_tests(uid)
                docs = store.documents_text(uid)
                try:
                    compiled = onboarding.compile_profile(answers, raw_info, extra, docs)
                    store.set_compiled(uid, compiled)
                    self._json(200, {"ok": True, "compiled": compiled}); return
                except Exception as e:
                    self._json(500, {"error": str(e)}); return

            if u.path == "/api/profile/info":
                raw_info = body.get("raw_info") or ""
                store.save_raw_info(uid, raw_info)
                prof = store.get_profile(uid)
                try:
                    answers = json.loads(prof.get("test_answers") or "{}")
                except Exception:
                    answers = {}
                extra = store.get_extra_tests(uid)
                docs = store.documents_text(uid)

                def bg():
                    try:
                        store.set_compiled(uid, onboarding.compile_profile(answers, raw_info, extra, docs))
                    except Exception as e:
                        print("recompile fail:", e, flush=True)
                threading.Thread(target=bg, daemon=True).start()
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

            self._json(404, {"error": "not found"})
        except Exception as e:
            self._json(500, {"error": str(e)})

    # ── google oauth ──
    def _google_redirect(self):
        if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
            self._json(400, {"error": "google не настроен"}); return
        params = urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": self._base_url() + "/api/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account",
        })
        self._redirect("https://accounts.google.com/o/oauth2/v2/auth?" + params)

    def _google_callback(self, u):
        import httpx
        code = parse_qs(u.query).get("code", [""])[0]
        base = self._base_url()
        if not code:
            self._redirect(base + "/?auth_error=1"); return
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
                    self._redirect(base + "/?auth_error=token"); return
                info = cli.get("https://www.googleapis.com/oauth2/v2/userinfo",
                               headers={"Authorization": "Bearer " + access}).json()
            email = info.get("email")
            if not email:
                self._redirect(base + "/?auth_error=email"); return
            user = store.get_or_create_oauth_user(email, info.get("name") or "")
            token = store.create_session(user["id"])
            prof = store.get_profile(user["id"])
            self._redirect(base + f"/?token={token}&onb={1 if prof.get('onboarded') else 0}")
        except Exception as e:
            print("google callback error:", e, flush=True)
            self._redirect(base + "/?auth_error=server")


def main():
    store.init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"SaaS-сервер на :{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
