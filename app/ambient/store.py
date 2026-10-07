"""Private, local spatial memory. SQLite commits notes and event deduplication atomically."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.ambient.catalog import FIXTURE_NOTES


def initial_state(now: float) -> dict[str, Any]:
    return {
        "revision": 0,
        "presence": {"people": [], "guest": False, "observed_at": 0},
        "media": {
            "scene": "coast",
            "playback_id": str(uuid4()),
            "phase": "program",
            "break_until": 0,
            "muted": False,
            "captions": False,
        },
        "inventory": {
            "available": ["pasta", "lemon", "parmesan", "tomato", "basil", "bread"],
            "observed_at": now,
        },
        "cart": {},
        "panel": None,
        "auto_dashboard": True,
        "room": {"tv_area": 65, "reading_lamp": 30, "mode": "evening"},
        "restore": None,
        "plan": [],
        "sequences": {},
        "trace": [],
    }


class CanvasStore:
    def __init__(self, path: str, now: float) -> None:
        if path != ":memory:":
            location = Path(path)
            location.parent.mkdir(parents=True, exist_ok=True)
            location.touch(mode=0o600, exist_ok=True)
            location.chmod(0o600)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=3000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS canvas_state (id INTEGER PRIMARY KEY CHECK (id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS canvas_notes (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS canvas_receipts (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, reply TEXT NOT NULL, created_at REAL NOT NULL);
        """)
        if self.db.execute("SELECT id FROM canvas_state WHERE id=1").fetchone() is None:
            with self.db:
                self.save(initial_state(now))
                for note in FIXTURE_NOTES:
                    self.put_note(
                        {
                            **note,
                            "created_at": now,
                            "expires_at": now + 86400,
                            "dismissed": False,
                            "screening": "demo_fixture",
                        }
                    )

    def load(self) -> dict[str, Any]:
        return json.loads(self.db.execute("SELECT data FROM canvas_state WHERE id=1").fetchone()[0])

    def save(self, state: dict[str, Any]) -> None:
        self.db.execute("INSERT OR REPLACE INTO canvas_state VALUES (1, ?)", (json.dumps(state),))

    def notes(self, now: float) -> list[dict[str, Any]]:
        return sorted(
            (json.loads(row[0]) for row in self.db.execute("SELECT data FROM canvas_notes")),
            key=lambda note: note["created_at"],
            reverse=True,
        )

    def put_note(self, note: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO canvas_notes VALUES (?, ?)", (note["id"], json.dumps(note))
        )

    def receipt(self, identifier: str) -> tuple[str, str] | None:
        return self.db.execute(
            "SELECT fingerprint, reply FROM canvas_receipts WHERE id=?", (identifier,)
        ).fetchone()

    def remember(self, identifier: str, digest: str, reply: str, now: float) -> None:
        self.db.execute(
            "INSERT INTO canvas_receipts VALUES (?, ?, ?, ?)", (identifier, digest, reply, now)
        )
        # A bounded replay window; source sequence watermarks survive pruning.
        self.db.execute("DELETE FROM canvas_receipts WHERE created_at < ?", (now - 86400,))
        self.db.execute(
            "DELETE FROM canvas_notes WHERE json_extract(data, '$.expires_at') < ?", (now,)
        )

    def close(self) -> None:
        self.db.close()
