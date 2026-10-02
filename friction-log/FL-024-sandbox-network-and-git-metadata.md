# FL-024 — Sandbox blocked external DNS and Git branch metadata writes

- **Date:** 2026-10-02
- **Component:** Decionis production validation and HomeBound phase branch setup
- **Environment:** Restricted Codex workspace sandbox
- **Expected:** The policy publisher can resolve the Decionis API, and a phase branch can be created from the merged `origin/master`.
- **Observed:** Default sandbox execution failed DNS lookup for `api.decionis.com`; Git refused to create `.git/index.lock` because repository metadata is read-only in the default permission profile.
- **Error:** Network request returned `ENOTFOUND`; `git switch -c` returned `Operation not permitted` at `.git/index.lock`.
- **Impact:** The production bundle could not be read or published and the work could not be isolated into the requested phase branch using default permissions.
- **Investigation:** Confirmed the project files were writable and the merged `origin/master` was current. The failures were limited to external networking and Git metadata writes.
- **Workaround:** Used narrowly scoped approved command access for the Decionis request and branch creation. The ignored `agentsafe/.env` supplied credentials at runtime; output included only bundle version and rule identifiers, never the API key or org ID.
- **Resolution:** Created the phase branch from merged master, read the existing Commerce bundle, and used the production policy publisher to validate and publish the merged HomeBound version.
- **Upstream/documentation gap:** None; this was a local workspace permission boundary.
- **Status:** Resolved for the current phase.
