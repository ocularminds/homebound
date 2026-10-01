# FL-019 — MCP context signals are proposal parameters, not identity proof

- **Date:** 2026-10-02
- **Component:** MCP proposal → AgentSafe Execution Intent Envelope → Decionis policy inputs
- **Environment:** HomeBound local demo, official `@decionis/agentsafe` 0.2.5
- **Expected:** Policy can distinguish a child's request from a parent and evaluate courier/time context without treating agent-supplied labels as authenticated identity.
- **Observed:** AgentSafe captures the proposal action, target, and parameters as the intent. Its trusted actor identifies the HomeBound service. MCP context signals are nested in proposal parameters; they are bound by the intent hash but are not authenticated identity claims.
- **Error:** No runtime error. The risk is semantic: a cryptographically bound caller-supplied `user=parent` or courier label would still be an untrusted assertion.
- **Impact:** A Decionis policy must not treat current scenario fixtures as proof of household identity, courier identity, delivery expectation, or local time. Enabling a direct parent-role allow from these fields would create an unsafe bypass.
- **Investigation:** Inspected the installed AgentSafe `IntentCapture` and `ExecutionIntent` contracts. Trusted actor and downstream context come from executor configuration; proposal parameters are captured separately. The current demo sends its scenario labels through MCP arguments.
- **Workaround:** Keep the direct parent-role policy rule disabled. The child path may request managed Presence approval, but a production policy still needs trusted identity and schedule signals. The README states this boundary.
- **Resolution:** No identity-provider or Ring/doorbell signal adapter is configured. The policy draft records the prerequisite; no tenant change was made.
- **Upstream/documentation gap:** The AgentSafe proposal interface accepts arbitrary JSON parameters and binds them exactly, but binding does not authenticate their provenance. Integrators must supply trusted claims through a separately verified signal path.
- **Status:** Open deployment prerequisite.
