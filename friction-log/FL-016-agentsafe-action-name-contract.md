# FL-016 — AgentSafe action identifier contract

- **Date:** 2026-10-01
- **Component:** Python MCP → AgentSafe proposal schema → Decionis action binding
- **Environment:** HomeBound local integration; official `@decionis/agentsafe` runtime
- **Expected:** MCP tool calls named `unlockDoor`, `disarmSystem`, and `viewStream` are accepted by AgentSafe and remain bound to the same downstream operations.
- **Observed:** The official AgentSafe proposal schema accepts lowercase action identifiers but rejects MCP's public camelCase names.
- **Error:** A live request returned HTTP 400 with the sanitized upstream code `PROPOSAL_INVALID`.
- **Impact:** Consequential MCP actions could not reach Decionis, even though the tool names and local simulator were valid.
- **Investigation:** Inspected the AgentSafe action-name contract and verified the upstream rejection without recording response bodies or credentials.
- **Workaround:** Keep MCP's declarative public tool names and map them to the signed vendor-neutral capabilities `home.entry.unlock`, `home.security.disarm`, and `home.camera.view_stream`. The execution adapter maps only after validating the corresponding grant.
- **Resolution:** Mapping implemented in `app/interception/agentsafe_http.py` and `agentsafe/server.mjs`; Python and Node contract tests cover it.
- **Upstream/documentation gap:** The MCP-facing docs do not describe the lowercase restriction or the mapping requirement.
- **Status:** Resolved locally; live Decionis request now passes schema validation.
