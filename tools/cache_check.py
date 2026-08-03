#!/usr/bin/env python3
"""Проверка точки кэша: что кэшируется общая голова промпта, а не личное клиента.

Ошибка здесь дорогая и молчаливая. Попадёт профиль внутрь кэша — кэш ломается на
каждом клиенте и платишь полную цену, ничего при этом не заметив. Не попадёт точка
вовсе — платишь полную цену всегда. Ни то ни другое из ответов модели не видно.

Запуск:  python3 tools/cache_check.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv                                    # noqa: E402
load_dotenv(ROOT / ".env", override=True)
os.environ.setdefault("PSY_ROLE", "webapp")

import agent_core                                                 # noqa: E402
import llm                                                        # noqa: E402

fails = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("✓ " if ok else "✗ ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


A = agent_core.user_system("клиент А: перфекционизм, вина перед близкими", "обесценивает успехи")
B = agent_core.user_system("клиент Б: тревога, бессонница", "избегает конфликтов")

text_a, head_a = llm._flatten_system(A)
text_b, head_b = llm._flatten_system(B)

check("точка кэша выставлена", head_a > 0, f"{head_a} символов")
check("голова одинакова у разных клиентов", text_a[:head_a] == text_b[:head_b])
check("голова — это почти весь промпт", head_a / len(text_a) > 0.8,
      f"{head_a}/{len(text_a)} = {head_a / len(text_a):.0%}")
check("профиль клиента ЗА точкой", "клиент А" not in text_a[:head_a])
check("наблюдения ЗА точкой", "обесценивает успехи" not in text_a[:head_a])
check("душа В голове", "это голос психолога" in text_a[:head_a])
check("слои личности В голове", "КРИЗИС — ОТМЕНЯЕТ ВСЕ ПРАВИЛА ФОРМЫ" in text_a[:head_a])

# что реально уходит провайдеру
pay_claude = llm.system_payload("anthropic/claude-opus-5", text_a, head_a)
pay_gemini = llm.system_payload("google/gemini-3-flash-preview", text_a, head_a)
check("Anthropic получает части с cache_control",
      isinstance(pay_claude, list) and pay_claude[0].get("cache_control", {}).get("type") == "ephemeral",
      f"частей: {len(pay_claude) if isinstance(pay_claude, list) else 1}")
check("склейка частей = исходный промпт",
      isinstance(pay_claude, list) and "".join(p["text"] for p in pay_claude) == text_a)
check("Gemini получает строку (кэш у него сам)", isinstance(pay_gemini, str))
check("короткий промпт не режем", llm.system_payload("anthropic/claude-opus-5", "коротко", 3) == "коротко")

# цена: вход решает всё, поэтому считаем именно его
IN = len(text_a) // 3
for model, p_in in (("anthropic/claude-opus-5", 5.0), ("anthropic/claude-sonnet-5", 2.0),
                    ("anthropic/claude-haiku-4.5", 1.0)):
    full = IN / 1e6 * p_in
    cached = IN / 1e6 * p_in * 0.1
    print(f"   {model:30} вход {IN} ток.: без кэша ${full:.4f} · по кэшу ${cached:.4f}")

print("\n" + (f"{len(fails)} провал(ов)" if fails else "все проверки прошли"))
sys.exit(1 if fails else 0)
