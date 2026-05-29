"""Speech-to-text через Groq Whisper (бесплатный облачный API).

Render не тянет локальный whisper (нет GPU, лимит памяти), поэтому распознавание
голоса в веб-чате идёт через Groq: тот же whisper-large-v3, но в облаке и бесплатно.

ENV:
  GROQ_API_KEY   — ключ с console.groq.com (бесплатный)
  GROQ_STT_MODEL — опц., по умолч. whisper-large-v3-turbo
"""
import os

import httpx

_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


def _key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()


def enabled() -> bool:
    return bool(_key())


def _model() -> str:
    return os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")


def transcribe(audio: bytes, filename: str = "voice.webm", language: str = "ru") -> str:
    """Возвращает распознанный текст. Бросает RuntimeError при сбое."""
    key = _key()
    if not key:
        raise RuntimeError("GROQ_API_KEY не задан")
    if not audio:
        raise RuntimeError("пустой аудиопоток")
    files = {"file": (filename, audio, "application/octet-stream")}
    data = {"model": _model(), "response_format": "json"}
    if language:
        data["language"] = language
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=120) as cli:
        r = cli.post(_ENDPOINT, files=files, data=data, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"groq stt {r.status_code}: {r.text[:200]}")
        return (r.json().get("text") or "").strip()
