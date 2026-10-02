# FL-023 — Protocol rule facts and numeric time operators

- **Date:** 2026-10-02
- **Component:** HomeBound Protocol rules → AgentSafe Execution Intent → Decionis policy graph
- **Environment:** HomeBound production policy bundle; read-only inspection of Decionis Protocol and AgentSafe contracts
- **Expected:** Published rules select the exact AgentSafe action, target, and parameters, and apply the configured 14:00–18:00 home-local delivery window.
- **Observed:** The original local draft used top-level `action`/`target` fields and compared `HH:MM` strings with `GTE`/`LTE` operators. AgentSafe nests action details in `context.agent_safe.action`; Decionis compares those range operators numerically. The first production submission also rejected the disabled parent's `normal` severity and courier `normal` severity, and then rejected reuse of the immutable Commerce bundle ID.
- **Error:** The API's general policy validator accepted shape but the Protocol endpoint enforced rule severity enums and immutable bundle revisions. String-valued ranges do not match Decionis' numeric comparison implementation.
- **Impact:** A structurally accepted but semantically mismatched rule could fail to trigger Presence or courier policy outcomes.
- **Investigation:** Read AgentSafe's signed intent schema and Decionis `PolicyGraph.buildEvaluateDecisionPolicyFacts`/comparison logic. Confirmed nested fields and numeric range semantics.
- **Workaround:** Updated HomeBound predicates to `context.agent_safe.action.type`, `.resource`, and `.parameters.*`; changed severities to the supported `routine`/`elevated` values; used a new stable bundle ID for the version. The demo sends `local_time_minutes`; 14:00–18:00 is 840–1080, with outside-window blockers at `>1080` and `<840`. Existing Commerce rules are copied into the new active bundle because Decionis evaluates the newest active bundle.
- **Resolution:** The corrected immutable revision was published as `homebound-household-v1` while preserving all three existing Commerce rules. The publisher verifies the post-publication bundle and stores the local home binding.
- **Upstream/documentation gap:** The general policy validation route does not exercise the stricter Protocol write validation or semantically evaluate conditions against a captured AgentSafe request. The publisher now proceeds to Protocol submission only after validation, reports redacted error details, and verifies stored rule IDs.
- **Status:** Resolved for the deterministic prototype fixtures. Authenticated provenance for courier recognition, delivery expectation, household confirmation, and local time remains required before physical-device use.
