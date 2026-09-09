"""Speech to text via Groq Whisper. Fixture transcript when no key is configured (dev)."""
from __future__ import annotations

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings

log = structlog.get_logger(__name__)

FIXTURE_TRANSCRIPT = "my SO number is 45231"


class SttError(Exception):
    pass


class SttUnavailable(Exception):
    """Voice notes are switched off or not configured. A settings problem, not a transient failure -
    deliberately not an SttError, so the retry below never burns 3 x 60s on it."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=6), retry=retry_if_exception_type(SttError), reraise=True)
async def transcribe(audio: bytes, filename: str = "voice.ogg", language: str | None = None) -> str:
    s = get_settings()
    if not s.voice_notes:
        raise SttUnavailable("voice notes are switched off (VOICE_NOTES=false)")
    if not s.groq_api_key:
        # Guessing a transcript would look up a real order for the wrong customer, so only ever in dev.
        if s.is_dev:
            log.info("stt_fixture_used")
            return FIXTURE_TRANSCRIPT
        raise SttUnavailable("GROQ_API_KEY is not set, so speech cannot be turned into text")
    data = {"model": s.groq_stt_model, "response_format": "json"}
    if language:
        data["language"] = language
    files = {"file": (filename, audio, "audio/ogg")}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {s.groq_api_key}"},
                data=data,
                files=files,
            )
    except httpx.HTTPError as e:
        raise SttError(str(e)) from e
    if r.status_code >= 500 or r.status_code == 429:
        raise SttError(f"groq {r.status_code}")
    r.raise_for_status()
    return (r.json().get("text") or "").strip()
