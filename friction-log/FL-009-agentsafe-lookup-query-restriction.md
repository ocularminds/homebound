# FL-009 — AgentSafe lookup URL query restriction

- **Date:** 2026-10-01
- **Component:** AgentSafe downstream lookup / Ring simulator
- **Environment:** `@decionis/agentsafe` 0.2.5, loopback simulator
- **Expected:** Use one bounded local downstream lookup route for AgentSafe reconciliation and signed Decision Dossier evidence archival.
- **Observed:** AgentSafe validates its configured `DOWNSTREAM_LOOKUP_URL` as a URL template without query parameters. The initial plan to distinguish archive and reconciliation using a `?kind=archive` query was rejected by configuration validation.
- **Error:** AgentSafe refuses lookup URLs containing a query string during executor startup.
- **Impact:** AgentSafe and the simulator could not start with the initial lookup URL template.
- **Investigation:** Confirmed the lookup URL validator runs before handler registration and requires `{idempotency_key}` in the path template.
- **Workaround:** Use the single loopback path `/evidence/{idempotency_key}`. AgentSafe `GET`s it for execution reconciliation and uses `POST` for dossier archive preflight. The route accepts only those methods and still requires the executor-only simulator bearer token plus exact dossier/correlation bindings.
- **Resolution:** Added a method-routed evidence endpoint with separate behavior for `GET` and `POST`; the AgentSafe egress policy is limited to the configured simulator host/routes.
- **Upstream/documentation gap:** Document the no-query lookup URL validation requirement alongside the URL template examples.
- **Status:** Resolved in Phase 3; regression-tested.
