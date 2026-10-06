"""Deepgram REST speech input/output. Audio and keys stay out of local logs."""

from __future__ import annotations

from typing import Any

import httpx2

from app.web.settings import WebSettings

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_SPEECH_CHARACTERS = 1800
AUDIO_TYPES = frozenset(
    {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/mpeg"}
)


class VoiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 502) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class DeepgramVoice:
    def __init__(self, settings: WebSettings, client: httpx2.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def _post(self, path: str, **kwargs: Any) -> httpx2.Response:
        if not self.settings.voice_configured:
            raise VoiceError(
                "VOICE_NOT_CONFIGURED",
                "Voice is not configured. You can still type a request.",
                503,
            )
        # This URL is fixed; neither the browser nor a model can select a destination.
        headers = {
            "Authorization": f"Token {self.settings.deepgram_api_key.strip()}",
            **kwargs.pop("headers", {}),
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    f"https://api.deepgram.com/v1/{path}", headers=headers, **kwargs
                )
            else:
                async with httpx2.AsyncClient(
                    timeout=httpx2.Timeout(40, connect=5), follow_redirects=False
                ) as client:
                    response = await client.post(
                        f"https://api.deepgram.com/v1/{path}", headers=headers, **kwargs
                    )
        except httpx2.HTTPError:
            raise VoiceError(
                "VOICE_UNAVAILABLE", "The voice service could not be reached. Please try typing."
            ) from None
        if response.status_code in {401, 403}:
            raise VoiceError(
                "VOICE_AUTH_FAILED", "The voice service rejected its server configuration.", 503
            )
        if response.status_code == 429:
            raise VoiceError(
                "VOICE_RATE_LIMITED", "The voice service is busy. Please try typing.", 429
            )
        if not response.is_success:
            # Never relay provider error bodies, request headers, or credentials.
            raise VoiceError(
                "VOICE_UNAVAILABLE", "The voice service could not complete this request."
            )
        return response

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type not in AUDIO_TYPES:
            raise VoiceError(
                "AUDIO_TYPE_UNSUPPORTED", "This browser's recording format is not supported.", 415
            )
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("AUDIO_SIZE_INVALID", "Record a short request, up to 45 seconds.", 413)
        response = await self._post(
            "listen",
            content=audio,
            headers={"Content-Type": media_type},
            params={
                "model": self.settings.deepgram_stt_model,
                "smart_format": "true",
                "language": "en",
            },
        )
        try:
            transcript = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError, TypeError, ValueError):
            raise VoiceError(
                "TRANSCRIPT_INVALID", "The voice service returned no usable transcript."
            ) from None
        if not isinstance(transcript, str) or not transcript.strip():
            raise VoiceError(
                "NO_SPEECH", "I didn't catch that. Please try again or type your request.", 422
            )
        if len(transcript) > 2000:
            raise VoiceError("TRANSCRIPT_TOO_LONG", "Please use a shorter voice request.", 422)
        return transcript.strip()

    async def speak(self, text: str) -> bytes:
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_SPEECH_CHARACTERS:
            raise VoiceError("SPEECH_TEXT_INVALID", "The reply is too long to read aloud.", 422)
        response = await self._post(
            "speak",
            json={"text": text},
            params={"model": self.settings.deepgram_tts_model, "encoding": "mp3"},
        )
        if not response.content or response.headers.get("content-type", "").split(";", 1)[
            0
        ] not in {"audio/mpeg", "audio/mp3"}:
            raise VoiceError(
                "SPEECH_AUDIO_INVALID", "The voice service returned no playable audio."
            )
        return response.content
