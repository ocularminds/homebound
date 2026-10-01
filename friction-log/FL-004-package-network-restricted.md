# FL-004 — Python package installation required network approval

- **Date:** 2026-10-01
- **Component:** Python environment setup / MCP SDK
- **Environment:** macOS development shell, Python 3.13.5
- **Expected:** Install the project's declared MCP and test dependencies from PyPI.
- **Observed:** The first install failed because this shell could not resolve `pypi.org`. The install succeeded after using the approved network-enabled path.
- **Error:** Initial `NameResolutionError: Failed to resolve 'pypi.org'`; successful retry installed MCP 2.2.0 and its dependencies.
- **Impact:** Dependency setup delayed testing. An initial `pip --user` run also reported version conflicts with packages in the shared Anaconda environment; project verification now uses the repository's isolated `.venv`.
- **Investigation:** The official MCP SDK and all declared test dependencies installed successfully in `.venv` under Python 3.13.5.
- **Workaround:** Use an isolated project virtual environment and use `python -m pytest` so pytest uses the same interpreter as the packages.
- **Resolution:** Resolved for Phase 1 by installing project dependencies into `.venv` through the approved network-enabled path.
- **Upstream/documentation gap:** None found; this was a workspace network restriction and a mixed-interpreter setup.
- **Status:** Resolved; isolated verification passed.
