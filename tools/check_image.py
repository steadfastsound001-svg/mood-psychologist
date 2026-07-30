#!/usr/bin/env python3
"""Собирает файловый набор Docker-образа и пробует поднять сервер на нём.

Зачем. Dockerfile перечислял модули поимённо. Появились psyconfig и safety —
в образ они не попали, и деплой шесть недель падал на ModuleNotFoundError,
молча откатываясь на старую версию: локально всё работало, в проде жил июнь.
Проверка воспроизводит ровно то, что видит контейнер, и падает здесь, а не там.

Запуск:  python3 tools/check_image.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dockerignore() -> list[str]:
    f = ROOT / ".dockerignore"
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def copy_targets() -> list[str]:
    """Что копирует Dockerfile: разбираем сам файл, чтобы проверка не разошлась с ним."""
    out = []
    for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*COPY\s+(.+?)\s+\S+\s*$", ln)
        if m:
            out.extend(m.group(1).split())
    return out


def ignored(rel: Path, patterns: list[str]) -> bool:
    parts = rel.parts
    for p in patterns:
        p = p.rstrip("/")
        if rel.match(p) or p in parts or rel.name == p:
            return True
    return False


def build(dst: Path) -> int:
    pats = dockerignore()
    n = 0
    for target in copy_targets():
        for src in sorted(ROOT.glob(target)):
            rel = src.relative_to(ROOT)
            if ignored(rel, pats):
                continue
            if src.is_dir():
                shutil.copytree(src, dst / rel,
                                ignore=lambda d, names: [x for x in names
                                                         if ignored(Path(x), pats)])
                n += sum(1 for _ in (dst / rel).rglob("*") if _.is_file())
            else:
                shutil.copy2(src, dst / rel)
                n += 1
    return n


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp)
        n = build(dst)
        print(f"в образ попало файлов: {n}")
        probe = (
            "import os, sys\n"
            "os.environ.setdefault('PSY_ROLE', 'webapp')\n"
            "import server, psyconfig\n"
            "p = psyconfig.validate()\n"
            "print('слои:', len(psyconfig.layers_info()))\n"
            "print('проблемы конфига:', p or 'нет')\n"
            "sys.exit(1 if p else 0)\n"
        )
        r = subprocess.run([sys.executable, "-c", probe], cwd=dst,
                           capture_output=True, text=True, timeout=120)
        print(r.stdout.strip())
        if r.returncode != 0:
            print("\n✗ образ нерабочий — деплой упал бы ровно так:\n")
            print((r.stderr or "").strip()[-1500:])
            return 1
        print("\n✓ сервер поднимается на том наборе файлов, что уедет в прод")
        return 0


if __name__ == "__main__":
    sys.exit(main())
