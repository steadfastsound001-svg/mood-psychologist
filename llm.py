"""Anthropic-совместимая обёртка над OpenRouter (бесплатный DeepSeek).

Заменяет `from anthropic import Anthropic` минимальной правкой: интерфейс
`client.messages.create(model=..., max_tokens=..., system=..., messages=...)` сохранён,
внутри идёт HTTP в OpenRouter chat completions. Это позволяет не переписывать остальной код.

Модель из ENV LLM_MODEL (по умолч. deepseek/deepseek-v4-flash:free).
Кэш-блоки (cache_control) и блочный `system` от Anthropic просто склеиваются в один system-промпт.
"""
import os
from typing import Any

import httpx

def _api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def _base_url() -> str:
    return os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")


def _default_model() -> str:
    # DeepSeek-v4-flash: быстрый, бесплатный, заточен под лаконичные диалоги.
    return os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-flash:free")


# Specialist routing: разные модели под разные задачи.
# Каждая лучше своих сородичей в своей нише — synergy без оплаты.
TASK_MODELS = {
    "dialog":    "openai/gpt-oss-120b:free",                   # умнее, рассуждающая — главное для голоса
    "reasoning": "openai/gpt-oss-120b:free",                   # /week, /month, /goals
    "analysis":  "qwen/qwen3-next-80b-a3b-instruct:free",      # длинный контекст: snapshot NOW/HERO
    "fast":      "deepseek/deepseek-v4-flash:free",            # extract, edit_entry, router — быстрое, дешёвое
    "deep":      "openai/gpt-oss-120b:free",                   # /ask deep mode
    "consolidate": "qwen/qwen3-next-80b-a3b-instruct:free",    # сжатие профиля
}


def _model_for_task(task: str | None) -> str | None:
    if task and task in TASK_MODELS:
        return TASK_MODELS[task]
    return None


# Фолбэк-цепочка: если нужная модель rate-limit, идём по альтернативам.
_FALLBACK_EXTRA = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-v4-flash:free",
]


def _fallback_models() -> list[str]:
    out = [_default_model()]
    for m in _FALLBACK_EXTRA:
        if m not in out:
            out.append(m)
    return out


class _TextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str, model: str):
        self.content = [_TextBlock(text)]
        self.model = model
        self.stop_reason = "end_turn"


def _flatten_system(system: Any) -> str:
    """Anthropic допускает system как str ИЛИ list[{'type':'text','text':...,'cache_control':...}].
    OpenRouter принимает только str → склеиваем."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for b in system:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n\n".join(p for p in parts if p)
    return str(system)


def _flatten_content(content: Any) -> str:
    """Содержимое сообщения у Anthropic может быть строкой или списком блоков."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return str(content) if content is not None else ""


class _Messages:
    def create(
        self,
        *,
        model: str | None = None,
        max_tokens: int = 1500,
        system: Any = None,
        messages: list[dict] | None = None,
        task: str | None = None,
        **_ignored,
    ) -> _Response:
        # task-routing имеет приоритет над claude-* именами
        if task:
            preferred = _model_for_task(task)
            if preferred:
                model = preferred
        sys_text = _flatten_system(system)
        chat = []
        if sys_text:
            chat.append({"role": "system", "content": sys_text})
        for m in messages or []:
            chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

        fb = _fallback_models()
        models = [model] if model and model not in fb else []
        for m in fb:
            if m not in models:
                models.append(m)
        # Если передали Anthropic-имя (claude-*), просто игнорируем и идём по фолбэкам.
        models = [m for m in models if not (m and m.startswith("claude-"))]

        last_err: Exception | None = None
        for m in models:
            try:
                return self._post(m, chat, max_tokens)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"все модели OpenRouter не ответили: {last_err}")

    def _post(self, model: str, chat: list[dict], max_tokens: int) -> _Response:
        key = _api_key()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY не задан в .env")
        body = {
            "model": model,
            "messages": chat,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/personal-psychologist",
            "X-Title": "Psychologist Bot",
        }
        with httpx.Client(timeout=180) as cli:
            r = cli.post(f"{_base_url()}/chat/completions", json=body, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"openrouter {r.status_code}: {r.text[:300]}")
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"openrouter empty: {str(data)[:300]}")
            text = (choices[0].get("message") or {}).get("content") or ""
            return _Response(text=text, model=model)


class Anthropic:
    """Минимальный shim под используемое подмножество Anthropic SDK."""

    def __init__(self, api_key: str | None = None):
        # api_key игнорируется — мы идём в OpenRouter.
        self.messages = _Messages()


# ───────────── sync streaming (SSE) — для ThreadingHTTPServer ─────────────

import json as _json


def stream_completion_sync(
    *,
    system: Any = None,
    messages: list[dict] | None = None,
    max_tokens: int = 220,
    model: str | None = None,
    task: str | None = None,
):
    """Синхронный генератор текстовых дельт от OpenRouter (SSE), с fallback по моделям."""
    if task:
        preferred = _model_for_task(task)
        if preferred:
            model = preferred
    sys_text = _flatten_system(system)
    chat = []
    if sys_text:
        chat.append({"role": "system", "content": sys_text})
    for m in messages or []:
        chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

    fb = _fallback_models()
    models = [model] if model and model not in fb else []
    for m in fb:
        if m not in models:
            models.append(m)
    models = [m for m in models if not (m and m.startswith("claude-"))]

    key = _api_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY не задан в .env")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/personal-psychologist",
        "X-Title": "Psychologist Bot",
        "Accept": "text/event-stream",
    }
    url = f"{_base_url()}/chat/completions"
    last_err: Exception | None = None
    for m in models:
        body = {"model": m, "messages": chat, "max_tokens": max_tokens, "stream": True}
        got_any = False
        try:
            with httpx.Client(timeout=180) as cli:
                with cli.stream("POST", url, json=body, headers=headers) as r:
                    if r.status_code >= 400:
                        last_err = RuntimeError(f"openrouter {r.status_code}")
                        continue
                    for raw in r.iter_lines():
                        if not raw or raw.startswith(":") or not raw.startswith("data:"):
                            continue
                        payload = raw[5:].strip()
                        if payload == "[DONE]":
                            return
                        try:
                            obj = _json.loads(payload)
                            delta = obj["choices"][0].get("delta", {}).get("content")
                        except Exception:
                            delta = None
                        if delta:
                            got_any = True
                            yield delta
                    if got_any:
                        return
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise RuntimeError(f"стрим: все модели не ответили: {last_err}")


# ───────────── async streaming (SSE) ─────────────


async def stream_completion(
    *,
    system: Any = None,
    messages: list[dict] | None = None,
    max_tokens: int = 400,
    model: str | None = None,
    task: str | None = None,
):
    """Async-генератор дельт текста от OpenRouter (SSE), с fallback по моделям."""
    if task:
        preferred = _model_for_task(task)
        if preferred:
            model = preferred
    sys_text = _flatten_system(system)
    chat = []
    if sys_text:
        chat.append({"role": "system", "content": sys_text})
    for m in messages or []:
        chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

    fb = _fallback_models()
    models = [model] if model and model not in fb else []
    for m in fb:
        if m not in models:
            models.append(m)
    models = [m for m in models if not (m and m.startswith("claude-"))]

    key = _api_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY не задан в .env")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/personal-psychologist",
        "X-Title": "Psychologist Bot",
        "Accept": "text/event-stream",
    }
    url = f"{_base_url()}/chat/completions"
    last_err: Exception | None = None
    for m in models:
        body = {"model": m, "messages": chat, "max_tokens": max_tokens, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=180) as cli:
                async with cli.stream("POST", url, json=body, headers=headers) as r:
                    if r.status_code >= 400:
                        last_err = RuntimeError(f"openrouter {r.status_code}")
                        continue
                    async for raw in r.aiter_lines():
                        if not raw:
                            continue
                        if raw.startswith(":"):
                            continue
                        if not raw.startswith("data:"):
                            continue
                        payload = raw[5:].strip()
                        if payload == "[DONE]":
                            return
                        try:
                            obj = _json.loads(payload)
                        except Exception:
                            continue
                        try:
                            delta = obj["choices"][0].get("delta", {}).get("content")
                        except Exception:
                            delta = None
                        if delta:
                            yield delta
                    return
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"стрим: все модели не ответили: {last_err}")
