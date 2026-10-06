"""Server-only configuration for the local voice interface."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _voice_key_from_file(path: str) -> str:
    """Read only the named voice setting, without sourcing executor configuration."""
    source = Path(path)
    if not path or not source.is_file():
        return ""
    key = ""
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            match = re.match(r"^\s*(?:export\s+)?DEEPGRAM_API_KEY\s*=", line)
            if match is None:
                continue
            try:
                parts = shlex.split(line[match.end() :], comments=True)
            except ValueError:
                raise ValueError(
                    "Invalid DEEPGRAM_API_KEY entry in the voice configuration file."
                ) from None
            if len(parts) > 1:
                raise ValueError("Invalid DEEPGRAM_API_KEY entry in the voice configuration file.")
            key = parts[0] if parts else ""
    return key


@dataclass(frozen=True, slots=True)
class WebSettings:
    host: str = "127.0.0.1"
    port: int = 8300
    home_timezone: str = "Europe/Stockholm"
    deepgram_api_key: str = field(default="", repr=False)
    deepgram_stt_model: str = "nova-3"
    deepgram_tts_model: str = "aura-2-thalia-en"

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("The Alexa web simulator must bind to loopback.")
        if not 1 <= self.port <= 65535:
            raise ValueError("HOMEBOUND_WEB_PORT must be between 1 and 65535.")
        ZoneInfo(self.home_timezone)

    @property
    def voice_configured(self) -> bool:
        key = self.deepgram_api_key.strip()
        return bool(key) and not key.startswith("{{resolve:")

    @classmethod
    def from_environment(cls) -> WebSettings:
        voice_key = os.getenv("DEEPGRAM_API_KEY", "").strip() or _voice_key_from_file(
            os.getenv("HOMEBOUND_VOICE_ENV_FILE", "agentsafe/.env")
        )
        return cls(
            host=os.getenv("HOMEBOUND_WEB_HOST", "127.0.0.1"),
            port=int(os.getenv("HOMEBOUND_WEB_PORT", "8300")),
            home_timezone=os.getenv("HOMEBOUND_HOME_TIMEZONE", "Europe/Stockholm"),
            deepgram_api_key=voice_key,
            deepgram_stt_model=os.getenv("DEEPGRAM_STT_MODEL", "nova-3"),
            deepgram_tts_model=os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-thalia-en"),
        )
