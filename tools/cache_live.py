#!/usr/bin/env python3
"""Живая проверка кэша: платим мы за него или он не работает.

Арифметика экономии — это обещание, а не факт. Провайдер может проигнорировать
cache_control, OpenRouter — не пробросить ttl, точка кэша может стоять не там.
Всё это выглядит одинаково: ответы приходят, деньги уходят.

Скрипт шлёт один и тот же промпт дважды и смотрит usage: сколько токенов ушло в
запись кэша, сколько прочитано из него, сколько посчитано как обычный вход.
Стоит примерно две реплики.

Запуск:  python3 tools/cache_live.py [МОДЕЛЬ]
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv                                    # noqa: E402
load_dotenv(ROOT / ".env", override=True)
os.environ.setdefault("PSY_ROLE", "webapp")

import httpx                                                      # noqa: E402
import agent_core                                                 # noqa: E402
import agent_config                                               # noqa: E402
import llm                                                        # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else agent_config.cfg("model_chat", "anthropic/claude-opus-5")
H = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
     "Content-Type": "application/json",
     "HTTP-Referer": "https://t.me/personal-psychologist", "X-Title": "Psychologist Bot"}


def call(payload, question: str) -> dict:
    r = httpx.post("https://openrouter.ai/api/v1/chat/completions", headers=H, timeout=180, json={
        "model": MODEL, "max_tokens": 80,
        "messages": [{"role": "system", "content": payload},
                     {"role": "user", "content": question}],
    })
    if r.status_code != 200:
        print(f"✗ HTTP {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    return r.json().get("usage") or {}


def show(tag: str, u: dict) -> tuple[int, int]:
    d = u.get("prompt_tokens_details") or {}
    cached = d.get("cached_tokens") or u.get("cache_read_input_tokens") or 0
    written = u.get("cache_creation_input_tokens") or 0
    total = u.get("prompt_tokens") or 0
    print(f"  {tag:18} вход {total:>6} · записано в кэш {written:>6} · прочитано из кэша {cached:>6}")
    return total, cached


def main() -> int:
    sys_text, head = llm._flatten_system(agent_core.user_system("продакт 30 лет, перфекционизм", "обесценивает успехи"))
    payload = llm.system_payload(MODEL, sys_text, head)
    parts = len(payload) if isinstance(payload, list) else 1
    ttl = llm._cache_ttl() if llm.supports_cache_breakpoint(MODEL) else "—"
    print(f"модель {MODEL}\nпромпт {len(sys_text)} символов, частей {parts}, точка на {head}, ttl {ttl}\n")

    t0, c0 = show("первый запрос", call(payload, "устал, но в целом норм"))
    time.sleep(3)
    t1, c1 = show("второй запрос", call(payload, "и что с этим делать"))

    print()
    if c1 > 0:
        print(f"✓ кэш работает: со второго запроса {c1} из {t1} токенов идут по цене чтения")
        print(f"  экономия на входе ≈ {c1 / max(1, t1):.0%}")
    else:
        print("✗ кэш НЕ сработал: второй запрос посчитан как обычный вход целиком.")
        print("  смотреть: пробрасывает ли провайдер cache_control, не сбита ли точка,")
        print("  не короче ли голова минимума (llm._CACHE_MIN_CHARS)")
    return 0 if c1 > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
