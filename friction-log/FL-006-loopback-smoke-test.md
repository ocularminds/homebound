# FL-006 — Sandbox denied the local MCP HTTP smoke test

- **Date:** 2026-10-01
- **Component:** MCP Streamable HTTP local verification
- **Environment:** macOS restricted execution sandbox
- **Expected:** A local MCP client can connect to the MCP server on `127.0.0.1:8000`.
- **Observed:** The initial client and curl requests were denied before reaching Uvicorn with `Operation not permitted`. The same MCP list-tools and fail-closed call succeeded after using the approved local-network verification path.
- **Error:** `httpx2.ConnectError: All connection attempts failed`; curl reported `Operation not permitted`.
- **Impact:** The default sandbox cannot perform loopback HTTP integration checks.
- **Investigation:** Confirmed Uvicorn was serving the real Streamable HTTP endpoint and received the client request after network-enabled verification.
- **Workaround:** Run local server-to-client smoke checks through the permitted network-enabled verification path; retain in-process MCP protocol tests for normal CI.
- **Resolution:** Resolved for Phase 1. Smoke test listed all three Ring tools and returned `BLOCK / NOT_PERFORMED` for `unlockDoor`.
- **Upstream/documentation gap:** None found; the restriction came from the execution environment.
- **Status:** Resolved.
