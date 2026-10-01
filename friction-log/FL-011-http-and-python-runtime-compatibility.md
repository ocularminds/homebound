# FL-011 — HTTP client and Python runtime compatibility

- **Date:** 2026-10-01
- **Component:** Python MCP client, AgentSafe adapter, and simulator
- **Environment:** macOS development checkout; project declares Python 3.10+
- **Expected:** Install the declared dependencies and collect the automated test suite on the declared Python 3.10+ range.
- **Observed:** The first test run used a bare system Python without the project dependencies and failed to import `mcp`, `uvicorn`, and the MCP SDK's `httpx2` transport. After installing dependencies, Python 3.10 exposed a separate incompatible `datetime.UTC` import.
- **Error:** Initial collection raised `ModuleNotFoundError` for uninstalled dependencies; the clean Python 3.10 environment then raised `ImportError: cannot import name 'UTC' from 'datetime'` in the audit log.
- **Impact:** Test collection could not validate the declared Python 3.10 minimum. The app also relied on MCP's transitive `httpx2` dependency without declaring its direct use.
- **Investigation:** Confirmed `mcp==2.2.0` requires `httpx2>=2.5.0`, and its Streamable HTTP transport accepts `httpx2.AsyncClient`. Confirmed `datetime.UTC` was introduced after Python 3.10.
- **Workaround:** Installed the package extras in isolated Python 3.10 and 3.13 virtual environments, declared `httpx2` directly, and replaced `datetime.UTC` with `timezone.utc`.
- **Resolution:** The application and test suite use the MCP SDK's supported HTTP transport dependency; Python 3.10+ compatibility is retained.
- **Upstream/documentation gap:** The original package metadata omitted a direct dependency that the application imports and used a Python 3.11-only datetime API despite declaring Python 3.10 support.
- **Status:** Resolved; the test suite passes on Python 3.10 and 3.13.
