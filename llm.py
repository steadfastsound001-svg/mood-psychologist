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


# ───────────── OpenAI (платный, основной) ─────────────
# Имя модели БЕЗ "/" = нативный OpenAI. Имя С "/" = OpenRouter (free fallback).
def _openai_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def _openai_base() -> str:
    return os.environ.get("OPENAI_BASE", "https://api.openai.com/v1")


def _openai_model() -> str:
    # глубокие задачи (портрет, итоги, /ask). редактируется в техпанели (model_deep), иначе ENV.
    import agent_config
    return agent_config.cfg("model_deep", os.environ.get("OPENAI_MODEL", "gpt-5")).strip()


def _openai_model_fast() -> str:
    # частые задачи (чат, дневник, фон). редактируется в техпанели (model_chat), иначе ENV.
    import agent_config
    return agent_config.cfg("model_chat", os.environ.get("OPENAI_MODEL_FAST", "gpt-5-mini")).strip()


# какой OpenAI-моделью крыть каждую задачу
def _openai_model_for_task(task: str | None) -> str | None:
    if not _openai_key():
        return None
    # глубокие задачи → «умная» модель (OPENAI_MODEL, напр. Gemini 3.1 Pro):
    # портрет (analysis), итоги недели (reasoning), /ask (deep).
    # чат и фон → быстрая (OPENAI_MODEL_FAST, напр. Gemini 3 Flash).
    deep_tasks = {"analysis", "reasoning", "deep"}
    return _openai_model() if task in deep_tasks else _openai_model_fast()


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


# ───────────── пер-модельные анти-ИИ фильтры ─────────────
# Каждый гасит ИМЕННО почерк своей модели. Подставляется ПЕРВЫМ, перед общим
# характером агента (SYSTEM_BASE). Привязан к реально выбранной модели (и на фолбэке).
# Источники по анти-sycophancy: floydous gist (210+ papers), FutureSpeakAI/anti-sycophancy, Simon Willison.
_FILTER_GPT = (
    "[анти-почерк модели GPT — соблюдай строго]\n"
    "у GPT сильный RLHF-подхалимаж и узнаваемый почерк. ГАСИ:\n"
    "— ноль лести и поддакивания. не хвали реплики и вопросы («хороший вопрос», «отличное наблюдение», «ты молодец»). не подстраивайся под настроение, чтобы понравиться.\n"
    "— не соглашайся, если человек неправ: мягко, но прямо назови нестыковку (devil's advocate). честность важнее комфорта.\n"
    "— убери эмоциональную вату и реверансы: «рад помочь», «понимаю тебя», «это нормально», «ты не один».\n"
    "— под нож GPT-маркеры: «Безусловно», «Конечно!», «Важно отметить», «Стоит подчеркнуть», вводные-извинения, список-на-каждый-ответ, тире-вставки, жирнота на каждом слове, концовка-резюме «в итоге/таким образом».\n"
    "— не знаешь — скажи. сомнение проговаривай, не сглаживай."
)
_FILTER_DEEPSEEK = (
    "[анти-почерк DeepSeek]\n"
    "DeepSeek тянет в многословие, формальность и over-структуру. ГАСИ: без длинных перечислений и «во-первых/во-вторых», без морали, не дублируй мысль синонимами, без концовки-вывода. короче и живее."
)
_FILTER_QWEN = (
    "[анти-почерк Qwen]\n"
    "Qwen тянет в избыточную вежливость, формальные связки и пере-объяснение. ГАСИ: без «конечно», без длинных преамбул, не разжёвывай очевидное, живой русский, не калька с английского."
)
_FILTER_LLAMA = (
    "[анти-почерк Llama]\n"
    "Llama тянет в дисклеймеры и хедж. ГАСИ: без оговорок «я всего лишь ИИ», без лишних предупреждений, прямо и по делу."
)
_FILTER_GEMINI = (
    "[анти-почерк модели Gemini — соблюдай строго]\n"
    "Gemini палится тремя вещами: пере-структура (списки-всё-подряд), нейтральность без позиции "
    "и угодливость — в рецензир. исследовании 2026 Gemini чаще подтверждал мнение юзера, чем говорил правду. ГАСИ:\n"
    "— НИКАКИХ списков, буллетов, заголовков, нумерации и «с одной стороны… с другой». одна живая мысль сплошной речью.\n"
    "— имей позицию и реагируй лично, а не выдавай сбалансированный нейтральный обзор. у тебя есть своё мнение.\n"
    "— ноль угодливости и валидации («понимаю тебя», «это нормально», «ты молодец», «хороший вопрос»). не подтверждай мнение, чтобы понравиться.\n"
    "— человек неправ — скажи прямо: возрази, дай сильный контраргумент против его позиции (steelman). честность важнее приятности.\n"
    "— под нож Gemini-маркеры: «Важно понимать/отметить», «Стоит помнить», дежурные дисклеймеры, преамбулы, концовка-резюме, обилие **жирноты**.\n"
    "— без морали и коуч-лозунгов. суше, короче, рваным человеческим ритмом."
)
import agent_config
agent_config.register("filter_gpt", _FILTER_GPT, "Фильтр модели: GPT", "Глушит подхалимаж и почерк GPT. Включается на gpt-* и gpt-oss.", "filter", 1)
agent_config.register("filter_deepseek", _FILTER_DEEPSEEK, "Фильтр модели: DeepSeek", "Глушит многословие DeepSeek.", "filter", 2)
agent_config.register("filter_qwen", _FILTER_QWEN, "Фильтр модели: Qwen", "Глушит вежливость/кальку Qwen.", "filter", 3)
agent_config.register("filter_llama", _FILTER_LLAMA, "Фильтр модели: Llama", "Глушит дисклеймеры Llama.", "filter", 4)
agent_config.register("filter_gemini", _FILTER_GEMINI, "Фильтр модели: Gemini", "Глушит структуру/угодливость Gemini. Включается на gemini/google.", "filter", 5)
# модели стека — редактируются из техпанели (иначе берутся из ENV). имя с «/» = OpenRouter, без «/» = нативный OpenAI.
agent_config.register("model_chat", os.environ.get("OPENAI_MODEL_FAST", "google/gemini-3-flash-preview"),
                      "Модель: чат · дневник · фон", "Быстрая модель для диалога, дневника, фоновых задач (extract/чистка/роутер). «/» = OpenRouter.", "model", 1)
agent_config.register("model_deep", os.environ.get("OPENAI_MODEL", "google/gemini-3.1-pro-preview"),
                      "Модель: портрет · итоги · /ask", "Умная модель для портрета, итогов недели и /ask. «/» = OpenRouter.", "model", 2)

# (подстрока в имени модели) -> ключ конфига фильтра. порядок: специфичное раньше общего.
_FILTER_KEYS = [
    ("gpt-5", "filter_gpt"), ("gpt-4", "filter_gpt"), ("gpt-oss", "filter_gpt"),
    ("gemini", "filter_gemini"),
    ("deepseek", "filter_deepseek"), ("qwen", "filter_qwen"), ("llama", "filter_llama"),
    ("google/", "filter_gemini"), ("openai/", "filter_gpt"),
]


def _model_filter(model: str) -> str:
    m = (model or "").lower()
    for sub, key in _FILTER_KEYS:
        if sub in m:
            return agent_config.cfg(key, "")
    return ""


def _sys_for_model(model: str, base_sys: str) -> str:
    """Пер-модельный фильтр ПЕРЕД общим характером."""
    f = _model_filter(model)
    if not f:
        return base_sys
    return f + "\n\n" + base_sys if base_sys else f


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


def _chain(task: str | None, model: str | None) -> list[str]:
    """Единая цепочка моделей: OpenAI (платный) первым, затем free OpenRouter.
    Если OpenAI упал / нет ключа / кончился баланс — автоматически идём по free."""
    out: list[str] = []
    om = _openai_model_for_task(task)        # None если нет OPENAI_API_KEY
    if om:
        out.append(om)
    if task:                                  # переданный task важнее claude-имени
        pref = _model_for_task(task)
        if pref and pref not in out:
            out.append(pref)
    if model and model not in out:
        out.append(model)
    for m in _fallback_models():
        if m not in out:
            out.append(m)
    # claude-* имена не поддерживаем; нативные OpenAI-модели — только если есть ключ
    return [m for m in out
            if m and not m.startswith("claude-")
            and ("/" in m or _openai_key())]


def _is_reasoning_openai(model: str) -> bool:
    """gpt-5* и o-series — reasoning-модели OpenAI: другой параметр лимита токенов."""
    if "/" in model:
        return False
    m = model.lower()
    return (m.startswith("gpt-5") or m.startswith("o1")
            or m.startswith("o3") or m.startswith("o4") or m.startswith("o5"))


def _token_body(model: str, max_tokens: int) -> dict:
    """Reasoning-модели хотят max_completion_tokens (+бюджет на reasoning) и reasoning_effort.
    Остальные — обычный max_tokens. minimal по умолчанию: для чата-психолога reasoning не нужен."""
    if _is_reasoning_openai(model):
        body = {"max_completion_tokens": max_tokens + 256}
        eff = os.environ.get("OPENAI_REASONING_EFFORT", "minimal").strip()
        if eff:
            body["reasoning_effort"] = eff
        return body
    return {"max_tokens": max_tokens}


def _provider_headers(model: str, stream: bool = False):
    """(url, headers) под нужный провайдер. None — если для модели нет ключа."""
    if "/" in model:                          # OpenRouter
        key = _api_key()
        if not key:
            return None
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/personal-psychologist",
            "X-Title": "Psychologist Bot",
        }
        base = _base_url()
    else:                                     # нативный OpenAI
        key = _openai_key()
        if not key:
            return None
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        base = _openai_base()
    if stream:
        headers["Accept"] = "text/event-stream"
    return f"{base}/chat/completions", headers


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
        sys_text = _flatten_system(system)
        chat = []
        if sys_text:
            chat.append({"role": "system", "content": sys_text})
        for m in messages or []:
            chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

        models = _chain(task, model)
        has_sys = bool(chat) and chat[0]["role"] == "system"
        last_err: Exception | None = None
        for m in models:
            try:
                if has_sys:
                    chat[0]["content"] = _sys_for_model(m, sys_text)   # пер-модельный фильтр
                return self._post(m, chat, max_tokens)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"все модели не ответили: {last_err}")

    def _post(self, model: str, chat: list[dict], max_tokens: int) -> _Response:
        ph = _provider_headers(model)
        if ph is None:
            raise RuntimeError(f"нет ключа для модели {model}")
        url, headers = ph
        body = {"model": model, "messages": chat, **_token_body(model, max_tokens)}
        with httpx.Client(timeout=180) as cli:
            r = cli.post(url, json=body, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"{model} {r.status_code}: {r.text[:300]}")
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"{model} empty: {str(data)[:300]}")
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
    """Синхронный генератор текстовых дельт (SSE), OpenAI→OpenRouter fallback по моделям."""
    sys_text = _flatten_system(system)
    chat = []
    if sys_text:
        chat.append({"role": "system", "content": sys_text})
    for m in messages or []:
        chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

    models = _chain(task, model)
    last_err: Exception | None = None
    for m in models:
        ph = _provider_headers(m, stream=True)
        if ph is None:
            continue
        url, headers = ph
        if sys_text:
            chat[0]["content"] = _sys_for_model(m, sys_text)   # пер-модельный фильтр
        body = {"model": m, "messages": chat, "stream": True, **_token_body(m, max_tokens)}
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
    """Async-генератор дельт текста (SSE), OpenAI→OpenRouter fallback по моделям."""
    sys_text = _flatten_system(system)
    chat = []
    if sys_text:
        chat.append({"role": "system", "content": sys_text})
    for m in messages or []:
        chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

    models = _chain(task, model)
    last_err: Exception | None = None
    for m in models:
        ph = _provider_headers(m, stream=True)
        if ph is None:
            continue
        url, headers = ph
        if sys_text:
            chat[0]["content"] = _sys_for_model(m, sys_text)   # пер-модельный фильтр
        body = {"model": m, "messages": chat, "stream": True, **_token_body(m, max_tokens)}
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
