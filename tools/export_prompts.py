#!/usr/bin/env python3
"""Выгрузка всех промптов из техпанели (вкладка «промпты») в отдельные .md.

Берёт ЭФФЕКТИВНЫЕ значения (DB-оверрайд из админки, иначе дефолт из кода) —
ровно то, что показывает тех-панель. Кладёт в ~/Downloads/soul-prompts/.
"""
import os
import pathlib
import datetime

# .env → окружение (нужно для store/Turso, чтобы подтянуть оверрайды)
ROOT = pathlib.Path(__file__).resolve().parent.parent
envf = ROOT / ".env"
if envf.exists():
    for line in envf.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

import sys
sys.path.insert(0, str(ROOT))

# импорт модулей регистрирует все промпты в agent_config
import agent_core   # noqa: F401  (soul, system_base, anti_ai, layer_order, chat_max_tokens)
import onboarding   # noqa: F401  (compile_prompt)
import server       # noqa: F401  (weekly, dynmood, diary_feedback)
import llm          # noqa: F401  (filter_*, model_*)
import agent_config

OUT = pathlib.Path.home() / "Downloads" / "soul-prompts"
OUT.mkdir(parents=True, exist_ok=True)

items = agent_config.all_items()
CAT_RU = {"prompt": "Промпт", "filter": "Фильтр модели", "model": "Модель", "setting": "Настройка", "order": "Порядок"}

# только текстовые промпты по этапам (вкладка «промпты» + фильтры); модели/настройки — в индекс
prompt_items = [it for it in items if it["cat"] in ("prompt", "filter")]
other_items = [it for it in items if it["cat"] not in ("prompt", "filter")]

def slug(s):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)

written = []
for i, it in enumerate(prompt_items, 1):
    key = it["key"]
    eff = it["value"] if it["overridden"] else it["default"]
    src = "оверрайд из админки" if it["overridden"] else "дефолт из кода"
    fname = f"{i:02d}_{slug(key)}.md"
    body = (
        f"# {it['label']}\n\n"
        f"> **ключ:** `{key}`  \n"
        f"> **категория:** {CAT_RU.get(it['cat'], it['cat'])}  \n"
        f"> **источник:** {src}  \n"
        f"> **описание:** {it['desc']}\n\n"
        f"---\n\n"
        f"{eff}\n"
    )
    (OUT / fname).write_text(body, encoding="utf-8")
    written.append((fname, it["label"], key, len(eff)))

# индекс
idx = [f"# Промпты soul — выгрузка {datetime.date.today().isoformat()}", ""]
idx.append("Эффективные значения из тех-панели (оверрайд из админки, иначе дефолт кода).\n")
idx.append("## Промпты по этапам\n")
for fname, label, key, n in written:
    idx.append(f"- [{label}](./{fname}) — `{key}` ({n} симв.)")
idx.append("\n## Модели и настройки (значения)\n")
for it in other_items:
    eff = it["value"] if it["overridden"] else it["default"]
    idx.append(f"- **{it['label']}** (`{it['key']}`): `{eff}`")
(OUT / "INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

print(f"выгружено {len(written)} промптов + INDEX.md → {OUT}")
for fname, label, key, n in written:
    print(f"  {fname:36s} {label}")
