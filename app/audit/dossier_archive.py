"""Authenticated client for the isolated, official-verifier dossier archiver."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx2

LOGGER = logging.getLogger(__name__)


class DossierArchiveClient:
    """Request storage and independent Decionis signature verification locally."""

    def __init__(self, endpoint: str, bearer_token: str, *, timeout_seconds: float = 20.0) -> None:
        parsed = urlsplit(endpoint)
        loopback_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if parsed.scheme != "https" and not loopback_http:
            raise ValueError("Dossier archiver URL must use HTTPS except for loopback development")
        if not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Dossier archiver URL must be an absolute origin without query or fragment")
        if len(bearer_token) < 32:
            raise ValueError("Dossier archiver token must contain at least 32 characters")
        self._endpoint = endpoint.rstrip("/")
        self._bearer_token = bearer_token
        self._timeout_seconds = timeout_seconds

    def archive(self, dossier_id: str, correlation_id: str) -> dict[str, Any]:
        """Archive one actual Decision Dossier and return the verifier's result."""

        try:
            response = httpx2.post(
                f"{self._endpoint}/v1/archive",
                headers={"Authorization": f"Bearer {self._bearer_token}"},
                json={"dossier_id": dossier_id, "correlation_id": correlation_id},
                timeout=self._timeout_seconds,
            )
            body = response.json()
            if not isinstance(body, dict):
                body = {}
            if not response.is_success:
                return {
                    "verified": False,
                    "status": "UNAVAILABLE",
                    "reason_code": body.get("code", f"DOSSIER_ARCHIVER_HTTP_{response.status_code}"),
                }
            return body
        except (httpx2.HTTPError, ValueError, OSError) as error:
            LOGGER.warning(
                "dossier archive unavailable correlation_id=%s error_type=%s",
                correlation_id,
                type(error).__name__,
            )
            return {
                "verified": False,
                "status": "UNAVAILABLE",
                "reason_code": "DOSSIER_ARCHIVER_UNREACHABLE",
            }
