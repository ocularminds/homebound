# FL-005 — `pytest` executable used a different Python interpreter

- **Date:** 2026-10-01
- **Component:** Test runner / local Python environment
- **Environment:** macOS with Python 3.13.5 and a separate Python 3.10 pytest launcher on `PATH`
- **Expected:** Running `pytest` would use the interpreter where the project dependencies were installed.
- **Observed:** The standalone `pytest` executable imported Python 3.10 and could not find the project package or MCP SDK. `python -m pytest` used Python 3.13 and collected the tests.
- **Error:** `ModuleNotFoundError: No module named 'app'` and `No module named 'mcp'` from the Python 3.10 process.
- **Impact:** The first test run failed during collection despite successful dependency installation in Python 3.13.
- **Investigation:** Compared interpreter versions; `pytest` and `python -m pytest` resolved to different Python installations.
- **Workaround:** Use an isolated `.venv` and run its Python module entry point (`python -m pytest`).
- **Resolution:** Resolved by running `.venv/bin/python -m pytest` from the repository.
- **Upstream/documentation gap:** None found; the shell's PATH contains multiple Python installations.
- **Status:** Resolved; isolated test run passed.
