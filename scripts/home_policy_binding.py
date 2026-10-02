"""Private local storage helpers for versioned home-to-policy associations."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.models.policy import HomePolicyBinding


def record_policy_version(
    binding: dict[str, Any],
    *,
    bundle_id: str,
    policy_version: str,
    recorded_at: str,
    source: str,
) -> dict[str, Any]:
    """Return a binding with an appended, deduplicated version association."""

    current = HomePolicyBinding(
        home_id=binding["home_id"],
        org_id=binding["org_id"],
        bundle_id=bundle_id,
        policy_version=policy_version,
    )
    existing_history = binding.get("version_history", [])
    if not isinstance(existing_history, list) or any(
        not isinstance(entry, dict) for entry in existing_history
    ):
        raise ValueError("Home policy version history must be a list of objects.")
    history = [dict(entry) for entry in existing_history]

    old_pair = (binding["bundle_id"], binding["policy_version"])
    new_pair = (current.bundle_id, current.policy_version)
    known_pairs = {
        (entry.get("bundle_id"), entry.get("policy_version")) for entry in history
    }
    if old_pair not in known_pairs:
        history.append(
            {
                "bundle_id": old_pair[0],
                "policy_version": old_pair[1],
                "recorded_at": recorded_at,
                "source": source if old_pair == new_pair else "existing_home_binding",
            }
        )
    if not history or (history[-1].get("bundle_id"), history[-1].get("policy_version")) != new_pair:
        history.append(
            {
                "bundle_id": current.bundle_id,
                "policy_version": current.policy_version,
                "recorded_at": recorded_at,
                "source": source,
            }
        )

    return {
        **binding,
        **current.as_dict(),
        "version_history": history,
    }


def write_private_json(path: str | Path, value: dict[str, Any]) -> None:
    """Atomically write private JSON with owner-only file and directory modes."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
