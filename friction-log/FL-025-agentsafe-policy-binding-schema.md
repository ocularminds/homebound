# FL-025 — AgentSafe strict action schema rejected the home binding

- **Date:** 2026-10-02
- **Component:** HomeBound policy binding → AgentSafe registered action parameters
- **Environment:** Live HomeBound MCP and official AgentSafe executor; Ring simulator only
- **Expected:** The home/org/bundle/version association is included in the AgentSafe-bound exact intent and accepted by the registered action adapter.
- **Observed:** The first live courier attempt received an authoritative `ALLOW`, but AgentSafe returned 500 before contacting the simulator. The open executor attempt and locked simulator confirmed no downstream action occurred.
- **Error:** HomeBound added `homebound_policy_binding` to signed intent parameters, while AgentSafe's local adapter used a strict schema that allowed only purpose, context signals, and device parameters.
- **Impact:** AgentSafe safely refused an otherwise permitted simulated courier unlock; HomeBound surfaced `AUTHORITY_UNAVAILABLE` and no Ring simulator state changed.
- **Investigation:** Compared the exact Python AgentSafe request parameters with `agentsafe/server.mjs`'s Zod schema and traced the executor's pre-dispatch path. The schema rejected the binding before its handler could contact the signed-dossier preflight or simulator.
- **Workaround:** Added an optional, strict binding object to the action schema and compare its `org_id` with AgentSafe's trusted intent tenant before dispatch. A production AgentSafe process refuses an absent binding. Unit tests cover both matching and mismatched orgs.
- **Resolution:** After adding the strict binding schema and org match, both live courier requests passed through the real MCP and AgentSafe servers. The 16:00 request was allowed and unlocked only the simulated side gate; the 18:01 request was blocked and the gate stayed locked. Signed dossiers verified before dispatch or final audit.
- **Upstream/documentation gap:** None; this was a HomeBound adapter contract mismatch caught by the live integration test.
- **Status:** Resolved.
