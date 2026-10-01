# FL-013 — Audit package hidden by a broad ignore rule

- **Date:** 2026-10-01
- **Component:** Python audit source and repository packaging
- **Environment:** HomeBound Git checkout on macOS
- **Expected:** Commit the Python `app/audit/` package needed by the AgentSafe adapter and the governed demo, while ignoring generated root-level audit records.
- **Observed:** The `.gitignore` pattern `audit/` matched directories named `audit` at any depth, hiding the `app/audit/` source files. The implementation worked in the local checkout but those modules were absent from the merged phase branch.
- **Error:** `app.audit` files did not appear in Git status and were omitted from the phase PR branch; a clean checkout could not import the audit package.
- **Impact:** Action audit logging, pending escalation persistence, and dossier archival were missing from the shared branch despite local tests passing.
- **Investigation:** Compared the local implementation with the merged phase branch after fetching GitHub. The branch omitted `app/audit/`, and `git check-ignore` traced the cause to the unanchored directory pattern.
- **Workaround:** Anchor the generated audit output ignore rule to the repository root as `/audit/` and add the existing Python audit sources explicitly.
- **Resolution:** The source directory is visible to Git and will be included in the phase PR; generated root-level `audit/` data remains ignored.
- **Upstream/documentation gap:** Git ignore patterns without a leading slash can apply to matching nested directories as well as the repository-root output directory.
- **Status:** Resolved locally; the corrected source is included in this review branch.
