"""Слияние аккаунтов: переносит ВСЕ данные «жирного» аккаунта под другой (Google) аккаунт.

Безопасность:
  - только UPDATE-ы, НИ ОДНОГО DELETE (полностью обратимо через бэкап);
  - перед любым изменением делает полный бэкап БД в backups/;
  - по умолчанию dry-run (ничего не пишет), реальная запись только с --apply.

Запуск (читает TURSO_* из .env — значит работает с ПРОДОМ):
  python tools/migrate_account.py list
  python tools/migrate_account.py backup
  python tools/migrate_account.py merge --from <OLD_ID> --to-email steadfast.sound001@gmail.com
  python tools/migrate_account.py merge --from <OLD_ID> --to-email steadfast.sound001@gmail.com --apply
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

import store

TABLES = ["users", "sessions", "profiles", "messages", "documents", "mood_logs", "diary_entries"]
# таблицы с данными пользователя, которые переносим (user_id -> target)
ROW_TABLES = ["messages", "documents", "diary_entries", "mood_logs"]
PROFILE_FIELDS = ["raw_info", "test_answers", "compiled", "extra_tests"]


def _backend() -> str:
    return "TURSO (ПРОД)" if store._turso_on() else "local sqlite (dev)"


def counts(uid: int) -> dict:
    def c(sql, p):
        r = store.query(sql, p)
        return int(r[0]["n"]) if r else 0
    out = {
        "messages": c("SELECT COUNT(*) n FROM messages WHERE user_id=?", (uid,)),
        "documents": c("SELECT COUNT(*) n FROM documents WHERE user_id=?", (uid,)),
        "diary": c("SELECT COUNT(*) n FROM diary_entries WHERE user_id=?", (uid,)),
        "mood": c("SELECT COUNT(*) n FROM mood_logs WHERE user_id=?", (uid,)),
    }
    prof = store.query("SELECT raw_info, test_answers, compiled, extra_tests, onboarded FROM profiles WHERE user_id=?", (uid,))
    p = prof[0] if prof else {}
    out["raw_info_len"] = len(p.get("raw_info") or "")
    out["compiled_len"] = len(p.get("compiled") or "")
    out["test_answers_len"] = len(p.get("test_answers") or "")
    out["extra_tests_len"] = len(p.get("extra_tests") or "")
    out["onboarded"] = int(p.get("onboarded") or 0)
    out["docs_bytes"] = store.documents_total(uid)
    return out


def cmd_list(_args):
    print(f"\n=== БД: {_backend()} ===\n")
    users = store.query("SELECT id, email, name, created_at FROM users ORDER BY id", ())
    if not users:
        print("пользователей нет"); return
    for u in users:
        c = counts(u["id"])
        when = time.strftime("%Y-%m-%d", time.localtime(u["created_at"])) if u.get("created_at") else "?"
        print(f"id={u['id']:<3} {u.get('email',''):<38} рег={when} onb={c['onboarded']}")
        print(f"      msgs={c['messages']:<5} docs={c['documents']}({c['docs_bytes']}b) "
              f"diary={c['diary']:<4} mood={c['mood']:<4} "
              f"raw={c['raw_info_len']}b compiled={c['compiled_len']}b "
              f"tests={c['test_answers_len']}b extra={c['extra_tests_len']}b")
    print()


def cmd_backup(_args) -> Path:
    dump = {"_meta": {"ts": time.time(), "backend": _backend()}}
    for t in TABLES:
        try:
            dump[t] = store.query(f"SELECT * FROM {t}", ())
        except Exception as e:
            dump[t] = {"_error": str(e)}
    out = ROOT / "backups" / f"db_backup_{int(time.time())}.json"
    out.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    sizes = {t: (len(dump[t]) if isinstance(dump[t], list) else "ERR") for t in TABLES}
    print(f"бэкап → {out}")
    print("строк:", sizes)
    return out


def _resolve(args):
    src = store.query("SELECT id, email FROM users WHERE id=?", (args.from_id,))
    if not src:
        print(f"!! source id={args.from_id} не найден"); sys.exit(1)
    if args.to_email:
        tgt = store.query("SELECT id, email FROM users WHERE email=?", (args.to_email.strip().lower(),))
    else:
        tgt = store.query("SELECT id, email FROM users WHERE id=?", (args.to_id,))
    if not tgt:
        print("!! target не найден"); sys.exit(1)
    s, t = src[0], tgt[0]
    if s["id"] == t["id"]:
        print("!! source и target совпадают"); sys.exit(1)
    return s, t


def _merged_profile(src_id, tgt_id):
    def prof(uid):
        r = store.query("SELECT raw_info, test_answers, compiled, extra_tests, onboarded FROM profiles WHERE user_id=?", (uid,))
        return r[0] if r else {}
    sp, tp = prof(src_id), prof(tgt_id)
    out = {}
    for f in ["raw_info", "test_answers", "compiled"]:
        tv = (tp.get(f) or "").strip()
        out[f] = tp.get(f) if tv else (sp.get(f) or "")
    # extra_tests: объединяем словари (target имеет приоритет при коллизии ключа)
    try:
        se = json.loads(sp.get("extra_tests") or "{}")
    except Exception:
        se = {}
    try:
        te = json.loads(tp.get("extra_tests") or "{}")
    except Exception:
        te = {}
    se.update(te)
    out["extra_tests"] = json.dumps(se, ensure_ascii=False)
    out["onboarded"] = 1 if (int(sp.get("onboarded") or 0) or int(tp.get("onboarded") or 0)) else 0
    return out


def cmd_merge(args):
    print(f"\n=== БД: {_backend()} ===")
    s, t = _resolve(args)
    cs, ct = counts(s["id"]), counts(t["id"])
    print(f"\nИСТОЧНИК  id={s['id']} {s['email']}")
    print(f"          {cs}")
    print(f"ЦЕЛЬ      id={t['id']} {t['email']}")
    print(f"          {ct}")
    print("\nПЕРЕНОС (UPDATE user_id, без удалений):")
    for tbl in ROW_TABLES:
        n = store.query(f"SELECT COUNT(*) n FROM {tbl} WHERE user_id=?", (s["id"],))[0]["n"]
        print(f"  {tbl}: {n} строк → user_id {s['id']}→{t['id']}")
    mp = _merged_profile(s["id"], t["id"])
    print("\nПРОФИЛЬ цели после слияния:")
    print(f"  raw_info={len(mp['raw_info'])}b compiled={len(mp['compiled'])}b "
          f"test_answers={len(mp['test_answers'])}b extra_tests={len(mp['extra_tests'])}b onboarded={mp['onboarded']}")

    if not args.apply:
        print("\n[DRY-RUN] ничего не записано. Для применения добавь --apply\n")
        return

    cmd_backup(args)
    print("\n>>> ПРИМЕНЯЮ...")
    now = time.time()
    for tbl in ROW_TABLES:
        # UPDATE OR IGNORE — на случай конфликта PK(user_id,day) в mood_logs ничего не теряем и не удаляем
        store.execute(f"UPDATE OR IGNORE {tbl} SET user_id=? WHERE user_id=?", (t["id"], s["id"]))
    store.execute(
        "UPDATE profiles SET raw_info=?, test_answers=?, compiled=?, extra_tests=?, onboarded=?, updated_at=? WHERE user_id=?",
        (mp["raw_info"], mp["test_answers"], mp["compiled"], mp["extra_tests"], mp["onboarded"], now, t["id"]),
    )
    print(">>> ГОТОВО.\n")
    print("ПОСЛЕ:")
    print(f"  ИСТОЧНИК id={s['id']}: {counts(s['id'])}")
    print(f"  ЦЕЛЬ     id={t['id']}: {counts(t['id'])}\n")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("backup")
    m = sub.add_parser("merge")
    m.add_argument("--from", dest="from_id", type=int, required=True)
    m.add_argument("--to", dest="to_id", type=int)
    m.add_argument("--to-email", dest="to_email")
    m.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    {"list": cmd_list, "backup": cmd_backup, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    main()
