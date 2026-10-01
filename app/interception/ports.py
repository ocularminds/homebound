"""Ports used by declarative Ring tools to request governed execution."""

from __future__ import annotations

from typing import Protocol

from app.models.actions import ActionProposal, ActionResult


class ActionRequestPort(Protocol):
    """Accept a proposal for interception; implementations own the decision path."""

    async def request(self, proposal: ActionProposal) -> ActionResult: ...
