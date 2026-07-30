"""Безопасность в коде, а не в модели: детектор риска, лимиты и гарантия номера.

Правило в промпте — это просьба. Модель может её не выполнить, и в кризисе цена
ошибки не «плохой стиль», а жизнь. Поэтому здесь детерминированные проверки:

  detect(text, history)  — уровень риска по лексикону (config/psychologist/safety/markers.json)
  policy_for(tier, ...)  — лимит токенов: в кризисе жёсткий потолок снимается
  guarantee(text, tier)  — в ответ гарантированно попадает телефон из справочника

Детектор настроен на ЧУВСТВИТЕЛЬНОСТЬ, не на точность: ложное срабатывание стоит
одного лишнего бережного вопроса, пропуск — несопоставимо дороже.
"""
import json
import re
import unicodedata

import psyconfig

CRISIS_TIERS = {"A", "B", "C", "D"}          # кризис: лимит снят, номер обязателен
ACUTE_TIERS = {"E", "F"}                     # острое: лимит расширен
TIER_MODE = {"A": "CRISIS_ACT", "B": "CRISIS", "C": "CRISIS", "D": "CRISIS",
             "E": "ACUTE", "F": "DANGER_OTHER", "G": "GRIEF"}

_LAT2CYR = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м",
    "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
})


def normalize(text: str) -> str:
    """Без нормализации лексикон дырявый: «нехочужить», «н е х о ч у», «ne hochu zhit»."""
    t = unicodedata.normalize("NFKC", text or "").lower().replace("ё", "е")
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("So"))  # эмодзи
    t = re.sub(r"[^\w\s]+", " ", t, flags=re.UNICODE)
    # «н е х о ч у» → «нехочу»: склеиваем цепочки одиночных букв
    t = re.sub(r"\b(?:(\w)\s+){2,}(\w)\b", lambda m: m.group(0).replace(" ", ""), t)
    t = re.sub(r"\s+", " ", t).strip()
    if re.search(r"[a-z]", t) and not re.search(r"[а-я]", t):
        pass                                   # чисто английская фраза — ищем по английской секции как есть
    return t


def _squash(t: str) -> str:
    """Вариант без пробелов вообще — ловит «нехочужить»."""
    return re.sub(r"\s+", "", t)


def _markers() -> dict:
    raw = psyconfig.get("markers") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def detect(message: str, history: list[str] | None = None) -> str | None:
    """Возвращает tier (A..G) или None. Порядок важен: A самый тяжёлый, проверяется первым."""
    cfg = _markers()
    tiers = cfg.get("tiers") or {}
    win = int(cfg.get("window_messages") or 5)

    texts = [message] + list(history or [])[-win:]
    norm = [normalize(t) for t in texts if t]
    squashed = [_squash(n) for n in norm]

    for tier in ("A", "B", "C", "D", "F", "E", "G"):
        spec = tiers.get(tier) or {}
        for phrase in spec.get("any", []):
            p = normalize(phrase)
            if not p:
                continue
            ps = _squash(p)
            if any(p in n for n in norm) or any(ps in s for s in squashed):
                return tier
        for rule in spec.get("near", []):
            dist = int(rule.get("distance_words") or 6)
            for n in norm:
                if _near(n, rule.get("a", []), rule.get("b", []), dist):
                    return tier
    return None


def _near(text: str, group_a: list[str], group_b: list[str], distance: int) -> bool:
    """Два слота в окне N слов. Фразовый список пропускает «мне всё равно, проснусь я завтра или нет»."""
    words = text.split()
    pos_a, pos_b = [], []
    for i in range(len(words)):
        tail = " ".join(words[i:i + 4])
        if any(tail.startswith(normalize(a)) for a in group_a):
            pos_a.append(i)
        if any(tail.startswith(normalize(b)) for b in group_b):
            pos_b.append(i)
    return any(abs(a - b) <= distance for a in pos_a for b in pos_b)


def policy_for(tier: str | None, base_max_tokens: int) -> dict:
    """Лимит ответа под уровень риска. В кризисе жёсткий потолок снимается —
    иначе протокол физически не помещается и обрывается на полуслове."""
    if tier in CRISIS_TIERS:
        return {"max_tokens": max(base_max_tokens, 1600), "mode": TIER_MODE[tier], "crisis": True}
    if tier in ACUTE_TIERS:
        return {"max_tokens": max(base_max_tokens, 900), "mode": TIER_MODE[tier], "crisis": False}
    if tier == "G":
        return {"max_tokens": base_max_tokens, "mode": "GRIEF", "crisis": False}
    return {"max_tokens": base_max_tokens, "mode": "DEFAULT", "crisis": False}


def _known_numbers() -> list[str]:
    """Номера из справочника — только они считаются валидными."""
    text = psyconfig.get("crisis_numbers") or ""
    return re.findall(r"\b(?:\d[\d\-]{2,}\d|\d{3})\b", text)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def has_number(text: str) -> bool:
    """Номер присутствует, только если совпал со справочником.

    Короткие (112, 124) ищем как ОТДЕЛЬНЫЙ токен, длинные — по последним 10 цифрам.
    Иначе «112» находится внутри выдуманного «8-800-111-22-33», и галлюцинация
    проходит проверку — ровно та ошибка, ради которой сверка и делается.
    """
    short, long_ = set(), set()
    for n in _known_numbers():
        d = _digits(n)
        (short if len(d) <= 4 else long_).add(d[-10:] if len(d) > 4 else d)
    if not short and not long_:
        return False
    body = _digits(text)
    if any(k in body for k in long_):
        return True
    tokens = {_digits(t) for t in re.findall(r"\b[\d\-\s]{3,}\b", text)}
    return any(s in tokens for s in short)


_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-()]{7,}\d)(?!\d)")


def scrub_numbers(text: str) -> str:
    """Выдуманный телефон опаснее отсутствия телефона: человек в кризисе набирает
    его и попадает в никуда. Правило «давай только из справочника» — просьба, и
    модель её нарушает, поэтому сверяем в коде.

    Ищем только телефоноподобные цепочки (8+ цифр) — «5-4-3-2-1» и «20 минут»
    под это не попадают. Незнакомый номер заменяем на настоящий, а не вырезаем:
    дыра посреди фразы читается хуже и оставляет человека вообще без телефона.
    """
    if not text:
        return text
    known = {_digits(n)[-10:] for n in _known_numbers() if len(_digits(n)) > 4}
    if not known:
        return text
    fallback = ""
    for n in _known_numbers():
        if len(_digits(n)) > 4:
            fallback = n.strip("-—· ")
            break
    if not fallback:
        return text

    def fix(m: re.Match) -> str:
        d = _digits(m.group(0))
        if len(d) < 8 or d[-10:] in known:
            return m.group(0)
        print(f"[safety] выдуманный номер в ответе: {m.group(0)!r} → {fallback}", flush=True)
        return fallback

    return _PHONE_RE.sub(fix, text)


def guarantee(text: str, tier: str | None) -> str:
    """В кризисе ответ обязан нести телефон. Нет — дописываем из справочника."""
    if tier not in CRISIS_TIERS or has_number(text):
        return text
    numbers = (psyconfig.get("crisis_numbers") or "").strip()
    if not numbers:
        return text
    tail = "\n\nи ещё, это важно. вот куда можно позвонить прямо сейчас:\n" + numbers
    return text.rstrip() + tail


def last_resort(tier: str | None) -> str:
    """Что сказать, когда не ответила ни одна модель.

    Техническая строка «все модели не ответили» — худшее, что человек может увидеть
    в ответ на «не хочу жить». Провайдер падает, счёт кончается, сеть рвётся, а
    человек в этот момент уже написал. Ответ на такой случай лежит в коде и не
    зависит ни от одной модели.
    """
    if tier in CRISIS_TIERS:
        numbers = (psyconfig.get("crisis_numbers") or "").strip()
        return ("я здесь. у меня сейчас сбой со связью, и я не могу ответить так, "
                "как нужно, — но оставлять тебя с этим одного я не буду.\n\n"
                "позвони прямо сейчас, там живые люди и круглосуточно:\n" + numbers +
                "\n\nи напиши мне ещё раз через пару минут. я отвечу.")
    return ("у меня сбой со связью — не дотянулся ни до одной модели. "
            "напиши ещё раз через минуту, я вернусь.")


_selftest_cache: tuple | None = None      # (отпечаток лексикона, результат)


def selftest() -> list[str]:
    """Прогон канонических фраз из конфига. Битый лексикон выглядит в метриках
    как затишье, поэтому проверяется при загрузке.

    Результат кэшируется по самому лексикону: панель дёргает его на каждый запрос,
    а прогон 12 фраз по всем tier'ам стоит ощутимо дороже, чем сравнение строк.
    """
    global _selftest_cache
    raw = psyconfig.get("markers") or ""
    if _selftest_cache and _selftest_cache[0] == raw:
        return _selftest_cache[1]
    cfg = _markers()
    problems = []
    for case in cfg.get("selftest", []):
        got = detect(case.get("text", ""))
        want = case.get("tier")
        if got != want:
            problems.append(f"детектор: {case.get('text')!r} → {got}, ожидалось {want}")
    _selftest_cache = (raw, problems)
    return problems


if __name__ == "__main__":
    bad = selftest()
    print("\n".join(bad) if bad else f"детектор ok: {len(_markers().get('selftest', []))} кейсов, "
                                     f"номеров в справочнике: {len(_known_numbers())}")
