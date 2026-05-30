"""Локальный BM25-ретривер по дневнику и инсайтам.

Зачем: модель не должна читать весь log.jsonl каждый раз. Подаём top-K
релевантных к текущей реплике записей → модель видит контекст по делу,
тратит меньше токенов, отвечает точнее.

Без внешних зависимостей. Pure Python.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
LOG_PATH = ROOT / "data" / "log.jsonl"
INSIGHTS_PATH = ROOT / "data" / "insights.jsonl"

_RU_STOPWORDS = {
    "и", "в", "не", "на", "что", "я", "с", "это", "как", "а", "но", "по", "то",
    "же", "за", "к", "из", "у", "от", "до", "о", "об", "так", "уже", "если",
    "там", "тут", "вот", "был", "была", "было", "были", "есть", "быть", "мне",
    "меня", "его", "её", "их", "мы", "ты", "он", "она", "оно", "они", "ему",
    "себя", "себе", "при", "для", "над", "под", "без",
}


def tokenize(s: str) -> list[str]:
    s = s.lower()
    toks = re.findall(r"[а-яa-z0-9]{3,}", s)
    return [t for t in toks if t not in _RU_STOPWORDS]


def load_corpus() -> list[dict]:
    """Каждый документ: {id, ts, text, kind}."""
    docs: list[dict] = []
    if LOG_PATH.exists():
        for i, line in enumerate(LOG_PATH.read_text().splitlines()):
            try:
                r = json.loads(line)
                entry = (r.get("entry") or "").strip()
                if len(entry) < 20:
                    continue
                docs.append({
                    "id": f"log:{i}",
                    "ts": r.get("ts", ""),
                    "text": entry,
                    "kind": r.get("kind", "text"),
                })
            except Exception:
                continue
    if INSIGHTS_PATH.exists():
        for i, line in enumerate(INSIGHTS_PATH.read_text().splitlines()):
            try:
                r = json.loads(line)
                t = (r.get("text") or "").strip()
                if not t:
                    continue
                docs.append({
                    "id": f"ins:{i}",
                    "ts": r.get("ts", ""),
                    "text": t,
                    "kind": "insight",
                })
            except Exception:
                continue
    return docs


def bm25_search(query: str, docs: list[dict] | None = None, top_k: int = 6, k1: float = 1.5, b: float = 0.75) -> list[dict]:
    if docs is None:
        docs = load_corpus()
    if not docs:
        return []
    q_terms = tokenize(query)
    if not q_terms:
        return []
    tokenized = [tokenize(d["text"]) for d in docs]
    N = len(docs)
    avgdl = sum(len(t) for t in tokenized) / max(1, N)

    df = Counter()
    for toks in tokenized:
        for term in set(toks):
            df[term] += 1

    results = []
    for i, toks in enumerate(tokenized):
        if not toks:
            continue
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log((N - df[term] + 0.5) / (df[term] + 0.5) + 1)
            num = tf[term] * (k1 + 1)
            den = tf[term] + k1 * (1 - b + b * dl / avgdl)
            score += idf * num / den
        if score > 0:
            results.append((score, docs[i]))
    results.sort(key=lambda x: -x[0])
    return [d for _, d in results[:top_k]]


def format_for_context(hits: list[dict], max_chars: int = 2500) -> str:
    """Готовит компактный блок для system/user prompt."""
    if not hits:
        return ""
    out = []
    total = 0
    for h in hits:
        date = (h.get("ts") or "")[:10]
        kind = h.get("kind", "")
        text = h["text"]
        # обрезаем длинные записи
        if len(text) > 350:
            text = text[:350].rstrip() + "…"
        chunk = f"[{date} · {kind}] {text}"
        if total + len(chunk) > max_chars:
            break
        out.append(chunk)
        total += len(chunk)
    return "\n\n".join(out)


def retrieve_context(query: str, top_k: int = 6, max_chars: int = 2500) -> str:
    """Главный API. Возвращает готовый блок текста или пустую строку."""
    if not query or len(query.strip()) < 8:
        return ""
    hits = bm25_search(query, top_k=top_k)
    return format_for_context(hits, max_chars=max_chars)
