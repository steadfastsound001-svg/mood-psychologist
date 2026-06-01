"""Редактируемые промпты и настройки агента.

Каждый модуль при импорте регистрирует свои промпты-по-умолчанию через register().
Владелец может переопределить их из админки (хранится в БД agent_config). cfg()
возвращает override из БД, иначе дефолт из кода. Кэш 15с — правки подхватываются
почти сразу, без удара по БД на каждый промпт.
"""
import threading
import time
import store

_REG: dict[str, dict] = {}      # key -> {default, label, desc, cat, order}
_cache: dict[str, str] = {}
_cache_at = 0.0
_TTL = 15.0

# per-call оверрайды (песочница техпанели): на время запроса подменяют любой ключ,
# в т.ч. пустой строкой = «слой выключен». thread-local → не течёт между запросами.
_TLS = threading.local()


def set_overrides(d):
    _TLS.ov = {str(k): ("" if v is None else str(v)) for k, v in (d or {}).items()}


def clear_overrides():
    _TLS.ov = None


def _call_ov():
    return getattr(_TLS, "ov", None)


def register(key, default, label="", desc="", cat="prompt", order=0):
    _REG[key] = {"default": default, "label": label or key, "desc": desc, "cat": cat, "order": order}


def _overrides() -> dict:
    global _cache, _cache_at
    if time.time() - _cache_at > _TTL:
        try:
            _cache = store.all_config()
            _cache_at = time.time()
        except Exception:
            pass
    return _cache


def cfg(key, default=None):
    """Эффективное значение: per-call override (песочница) → override из БД → дефолт реестра → default."""
    co = _call_ov()
    if co is not None and key in co:
        return co[key]                 # "" = слой выключен на этот запрос
    ov = _overrides().get(key)
    if ov:
        return ov
    if key in _REG:
        return _REG[key]["default"]
    return default


def cfg_int(key, default):
    try:
        return int(str(cfg(key, default)).strip())
    except Exception:
        return default


def set_item(key, value):
    store.set_config(key, value or "")
    global _cache_at
    _cache_at = 0.0       # сброс кэша → следующий cfg() перечитает


def reset_item(key):
    set_item(key, "")


def all_items() -> list[dict]:
    """Для админки: все зарегистрированные конфиги + текущее значение/дефолт."""
    ov = _overrides()
    items = []
    for k, m in sorted(_REG.items(), key=lambda x: (x[1]["cat"], x[1]["order"], x[0])):
        items.append({
            "key": k, "label": m["label"], "desc": m["desc"], "cat": m["cat"],
            "value": ov.get(k) or "", "default": m["default"],
            "overridden": bool(ov.get(k)),
        })
    return items
