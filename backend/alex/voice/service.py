"""Whisper, OpenAI TTS (streamed PCM), and ElevenLabs. Missing keys stay explicit."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from alex.config import KEY_HELP, get_settings

OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


def capabilities(voice_provider: str, voice_id: str) -> dict:
    settings = get_settings()
    openai = bool(settings.openai_api_key.strip())
    eleven = bool(settings.elevenlabs_api_key.strip() and (settings.elevenlabs_voice_id.strip() or voice_id.strip()))
    stt = "openai" if openai else "browser"
    if voice_provider == "openai" and openai:
        tts = "openai"
    elif voice_provider == "elevenlabs" and settings.elevenlabs_api_key.strip():
        tts = "elevenlabs" if (settings.elevenlabs_voice_id.strip() or voice_id.strip()) else "browser"
    elif voice_provider == "browser":
        tts = "browser"
    elif openai:
        tts = "openai"
    elif eleven:
        tts = "elevenlabs"
    else:
        tts = "browser"
    return {
        "stt": stt,
        "tts": tts,
        "openai_voices": OPENAI_VOICES,
        "elevenlabs_configured": bool(settings.elevenlabs_api_key.strip()),
        "elevenlabs_voice_set": bool(settings.elevenlabs_voice_id.strip() or voice_id.strip()),
        "help": {
            "openai": KEY_HELP["openai"],
            "elevenlabs": KEY_HELP["elevenlabs"],
        },
        "note": (
            "Browser speechRecognition and speechSynthesis work with no keys. "
            "On Windows, speechSynthesis uses the installed Microsoft voices. "
            "OpenAI streams PCM for lower latency. ElevenLabs streams MP3."
        ),
    }


async def transcribe(audio: bytes, filename: str) -> str:
    settings = get_settings()
    if not settings.openai_api_key.strip():
        raise NotConfigured("Whisper needs OPENAI_API_KEY. The browser speech recognizer is the fallback.")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            files={"file": (filename or "speech.webm", audio, "application/octet-stream")},
            data={"model": "whisper-1"},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Whisper returned {response.status_code}: {response.text[:400]}")
    return str(response.json().get("text") or "").strip()


async def stream_tts(text: str, voice_provider: str, voice_id: str) -> tuple[str, AsyncIterator[bytes]]:
    """Return (content_type, byte iterator). Raises NotConfigured when the UI should use speechSynthesis."""
    settings = get_settings()
    spoken = (text or "").strip()
    if not spoken:
        raise RuntimeError("Nothing to speak.")
    spoken = spoken[:4000]
    provider = voice_provider
    if provider == "openai":
        if not settings.openai_api_key.strip():
            raise NotConfigured("OpenAI TTS needs OPENAI_API_KEY. Switch voice to Browser in Settings.")
        voice = voice_id if voice_id in OPENAI_VOICES else "nova"
        return "application/octet-stream", _openai_pcm(spoken, voice, settings.openai_api_key)
    if provider == "elevenlabs":
        voice = (voice_id or settings.elevenlabs_voice_id or "").strip()
        if not settings.elevenlabs_api_key.strip() or not voice:
            raise NotConfigured(
                "ElevenLabs needs ELEVENLABS_API_KEY and a voice id. "
                f"Keys: {KEY_HELP['elevenlabs']}"
            )
        return "audio/mpeg", _elevenlabs(spoken, voice, settings.elevenlabs_api_key)
    raise NotConfigured("Browser voice is selected. The interface will use speechSynthesis.")


async def _openai_pcm(text: str, voice: str, api_key: str) -> AsyncIterator[bytes]:
    payload = {"model": "tts-1", "voice": voice, "input": text, "response_format": "pcm"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20)) as client:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")[:400]
                raise RuntimeError(f"OpenAI TTS returned {response.status_code}: {body}")
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk


async def _elevenlabs(text: str, voice_id: str, api_key: str) -> AsyncIterator[bytes]:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    payload = {"text": text, "model_id": "eleven_turbo_v2_5"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20)) as client:
        async with client.stream(
            "POST",
            url,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")[:400]
                raise RuntimeError(f"ElevenLabs returned {response.status_code}: {body}")
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk


class NotConfigured(RuntimeError):
    pass
