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
_FILTER_GPT = ""   # текст в config/psychologist/filters/
_FILTER_DEEPSEEK = ""   # текст в config/psychologist/filters/
_FILTER_QWEN = ""   # текст в config/psychologist/filters/
_FILTER_LLAMA = ""   # текст в config/psychologist/filters/
_FILTER_GEMINI = ""   # текст в config/psychologist/filters/
_FILTER_CLAUDE = ""   # текст в config/psychologist/filters/claude.md
import agent_config
agent_config.register("filter_claude", _FILTER_CLAUDE, "Фильтр модели: Claude",
                      "Гасит почерк Claude: рефлекс валидации чувств, трёхчастная структура, кальки терапевт-английского. "
                      "Важен, т.к. финал клиенту пишет именно Claude-редактор.", "filter", 0)
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

# ───────────── два агента: «аналитик» (DeepSeek) → «редактор-голос» (Sonnet) ─────────────
# Агент 1 (DeepSeek) силён в сути/анализе, но слаб в живом русском (кальки, канцелярит,
# машинный ритм, лишняя структура). Агент 2 (Sonnet 4.6) закрывает эти слабости: правит и
# доводит до голоса психолога ПО ТЕМ ЖЕ ИНСТРУКЦИЯМ (душа подмешивается в систему редактора).
EDITOR_PROMPT = ""   # текст в config/psychologist/prompts/editor.md
agent_config.register("humanizer_prompt", "", "Редактор-голос (2-й агент)",
                      "Второй агент (Sonnet) правит черновик DeepSeek: чинит кальки/канцелярит/машинность, доводит до голоса, сохраняет остроту. Душа подмешивается автоматически.", "prompt", 8)
agent_config.register("humanizer_model", "anthropic/claude-sonnet-4.6", "Модель: редактор-голос",
                      "Кто правит сообщения и ревью (2-й агент). Sonnet 4.6 закрывает слабый русский DeepSeek. Альтернативы: claude-opus-4.x (мощнее, дороже), gpt-5.", "model", 3)
agent_config.register("humanize_on", "1", "Редактор-голос вкл (1/0)",
                      "1 — ответ психолога и ревью проходят 2-го агента (DeepSeek→Sonnet). 0 — только DeepSeek (быстрее, суше).", "setting", 1)


def _humanize_models():
    """(вкл, модель-редактор, система редактора = душа + рамка редактора)."""
    import agent_config
    soul = agent_config.cfg("soul", "")
    frame = agent_config.cfg("humanizer_prompt")
    sys = (soul + "\n\n" + frame) if soul else frame   # «по тем же инструкциям» — душа внутри редактора
    return (agent_config.cfg("humanize_on", "1") == "1",
            agent_config.cfg("humanizer_model", "anthropic/claude-sonnet-4.6"),
            sys)


def _editor_input(draft: str, user_msg: str | None) -> str:
    if user_msg:
        return (f"[реплика клиента]\n{user_msg}\n\n"
                f"[черновик ответа аналитика — отредактируй в финал]\n{draft}")
    return f"[черновик — отредактируй в финал]\n{draft}"


def humanize_stream(draft: str, user_msg: str | None = None, max_tokens: int = 600):
    """Генератор: 2-й агент (Sonnet) правит черновик и стримит финал.
    Выключено / агент не стартовал → отдаём черновик как есть (graceful)."""
    on, model, sys = _humanize_models()
    draft = (draft or "").strip()
    if not on or not draft:
        if draft:
            yield draft
        return
    try:
        gen = stream_completion_sync(system=sys, messages=[{"role": "user", "content": _editor_input(draft, user_msg)}],
                                     max_tokens=max_tokens, force=model)
        first = next(gen)                 # тут всплывёт ошибка старта редактора
    except StopIteration:
        yield draft; return
    except Exception:
        yield draft; return               # редактор не ответил → черновик
    yield first
    try:
        for d in gen:
            yield d
    except Exception:
        return                            # обрыв середины — оставляем что есть


def humanize_text(draft: str, user_msg: str | None = None, max_tokens: int = 600) -> str:
    """Не-стрим версия для ревью (итоги/отклик): вернуть отредактированный текст."""
    draft = (draft or "").strip()
    if not draft:
        return ""
    try:
        out = "".join(humanize_stream(draft, user_msg=user_msg, max_tokens=max_tokens)).strip()
        return trim_incomplete(out) or draft
    except Exception:
        return draft


# ───────────── завершённость: недописанных сообщений быть не должно ─────────────

_SENT_END = ".!?…"


def trim_incomplete(text: str) -> str:
    """Если ответ упёрся в max_tokens и оборвался на полуслове — срезаем хвост
    до последнего завершённого предложения. Завершённый текст не трогаем."""
    t = (text or "").rstrip()
    if not t:
        return t
    tail = t.rstrip("*»)\"'” ")          # закрывающие кавычки/звёздочки после точки — не обрыв
    if tail and tail[-1] in _SENT_END:
        return t
    cut = max(tail.rfind(c) for c in _SENT_END)
    if cut >= 60:                         # есть что оставить — режем недописанный хвост
        return t[:cut + 1]
    return t                              # ни одной завершённой мысли — отдаём как есть


def sentence_guard(gen, hold: int = 160):
    """Обёртка стрима: придерживает хвост ~hold символов, чтобы финал не ушёл
    клиенту оборванным на полуслове. На завершении хвост чистится до точки."""
    buf = ""
    head_sent = False
    for d in gen:
        buf += d
        if len(buf) > hold * 2:
            cut = len(buf) - hold
            yield buf[:cut]
            head_sent = True
            buf = buf[cut:]
    t = buf.rstrip()
    if not t:
        return
    tail = t.rstrip("*»)\"'” ")
    if tail and tail[-1] in _SENT_END:
        yield buf
        return
    cut = max(tail.rfind(c) for c in _SENT_END)
    if cut >= 0 and (head_sent or cut >= 60):
        yield t[:cut + 1]
    else:
        yield buf                         # ни одной точки в хвосте — лучше отдать как есть

# (подстрока в имени модели) -> ключ конфига фильтра. порядок: специфичное раньше общего.
_FILTER_KEYS = [
    ("claude", "filter_claude"), ("anthropic/", "filter_claude"),
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


# OpenRouter-модели с reasoning: размышление тратится ИЗ max_tokens → видимый ответ
# обрезается на полуслове, если не дать резерв. Подстроки в имени модели.
_REASONING_OR = ("deepseek-v4", "deepseek-r1", "gemini-3.1-pro", "thinking", "gpt-5", "o3-", "o4-")


def _token_body(model: str, max_tokens: int) -> dict:
    """Reasoning-модели хотят max_completion_tokens (+бюджет на reasoning) и reasoning_effort.
    Остальные — обычный max_tokens. minimal по умолчанию: для чата-психолога reasoning не нужен."""
    if _is_reasoning_openai(model):
        body = {"max_completion_tokens": max_tokens + 256}
        eff = os.environ.get("OPENAI_REASONING_EFFORT", "minimal").strip()
        if eff:
            body["reasoning_effort"] = eff
        return body
    m = model.lower()
    if "/" in model and any(s in m for s in _REASONING_OR):
        # резерв на размышление + просим минимум усилий (OpenRouter unified reasoning param;
        # провайдеры без поддержки игнорируют)
        return {"max_tokens": max_tokens + 800, "reasoning": {"effort": "low"}}
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
    force: str | None = None,
):
    """Синхронный генератор текстовых дельт (SSE), OpenAI→OpenRouter fallback по моделям.
    force — жёстко эта модель и только она (для humanizer-прохода Sonnet)."""
    sys_text = _flatten_system(system)
    chat = []
    if sys_text:
        chat.append({"role": "system", "content": sys_text})
    for m in messages or []:
        chat.append({"role": m.get("role", "user"), "content": _flatten_content(m.get("content", ""))})

    models = [force] if force else _chain(task, model)
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
