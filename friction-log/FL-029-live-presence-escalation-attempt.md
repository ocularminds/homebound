# FL-029 — Fresh child request failed before a Presence handoff

- **Date:** 2026-10-02
- **Component:** Decionis enforcement → AgentSafe → managed Presence escalation
- **Environment:** Live Decionis tenant; local AgentSafe 0.2.5 executor and Ring simulator; no physical device
- **Expected:** A child at home at 15:00 requests disarmSystem(home_security), Decionis returns ESCALATE, and its native Presence flow creates a parent approval request.
- **Observed:** MCP captured the exact disarm intent and submitted it through AgentSafe. AgentSafe failed closed with AUTHORITY_UNAVAILABLE; the local simulator remained at its secured baseline.
- **Error:** AgentSafe evidence recorded AUTHORITY_FAILED_CLOSED with reason AUTHORITY_REQUEST_FAILED; no decision dossier or escalation handoff was returned.
- **Impact:** No Presence request was created, so there was nothing for the parent to approve or deny. No Ring execution occurred.
- **Investigation:** Live courier allow and block evaluations succeeded earlier in the same session. The current child request returned before the Presence handoff and exposed only the generic authority failure code. The lower-level cause remains undetermined.
- **Workaround:** None. Keep the request fail-closed; do not call Presence directly or bypass AgentSafe. Inspect the Decionis/AgentSafe authority error and retry only after the authority path is healthy.
- **Resolution:** Pending a successful child evaluation and a real Presence ceremony.
- **Upstream/documentation gap:** The current client response does not surface the underlying Decionis request error needed to distinguish policy, identity, Presence, and transient service failures.
- **Status:** Open; a fresh request is required once the authority error is diagnosed.
