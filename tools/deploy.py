#!/usr/bin/env python3
"""Деплой на Render через API (надёжнее GitHub-вебхука — он молча пропускает пуши).

Запуск:  python3 tools/deploy.py
Читает RENDER_API_KEY и RENDER_SERVICE_ID из .env. Триггерит сборку последнего
коммита main, ждёт пока статус не станет live (или fail). SSL не верифицируется —
системный Python на Mac без сертификатов (см. CLAUDE.md проекта).
"""
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def load_env():
    env = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def api(key, path, method="GET", body=None):
    req = urllib.request.Request(
        "https://api.render.com/v1" + path, method=method,
        headers={"Authorization": "Bearer " + key, "Accept": "application/json",
                 "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None)
    try:
        r = urllib.request.urlopen(req, timeout=30, context=CTX)
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main():
    env = load_env()
    key, srv = env.get("RENDER_API_KEY"), env.get("RENDER_SERVICE_ID")
    if not key or not srv:
        print("нет RENDER_API_KEY / RENDER_SERVICE_ID в .env"); sys.exit(1)
    st, d = api(key, f"/services/{srv}/deploys", "POST", {"clearCache": "do_not_clear"})
    if st not in (200, 201):
        print("не удалось стартовать деплой:", st, d); sys.exit(1)
    dep = (d.get("deploy", d) if isinstance(d, dict) else {})
    depid = dep.get("id")
    commit = (dep.get("commit", {}) or {}).get("id", "")[:9]
    print(f"деплой запущен: {depid} (коммит {commit})")
    for _ in range(40):
        time.sleep(14)
        _, dd = api(key, f"/services/{srv}/deploys/{depid}")
        status = (dd.get("deploy", dd) if isinstance(dd, dict) else {}).get("status", "?")
        print("  ", status, flush=True)
        if status == "live":
            print("✅ live"); return
        if status in ("update_failed", "build_failed", "canceled", "pre_deploy_failed"):
            print("❌ деплой упал:", status); sys.exit(1)
    print("⏳ не дождался live за ~9 мин — проверь дашборд")


if __name__ == "__main__":
    main()
