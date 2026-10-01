# FL-007 — Managed Presence approver configuration

- **Date:** 2026-10-01
- **Component:** Decionis AgentSafe managed escalation
- **Environment:** `@decionis/agentsafe` 0.2.5, Node.js 22.23.2
- **Expected:** Decionis selects the household approver from policy roles and runs Presence; HomeBound does not contact Presence or name an approver in an agent proposal.
- **Observed:** The official AgentSafe runtime's `MANAGED` configuration requires `PRESENCE_APPROVER_ID`; `PRESENCE_APPROVER_ROLE` is optional. The Commerce `PresenceManagedAuthority` instead sends `approver: { role_id: "APPROVER" }` when no individual approver was supplied.
- **Error:** A role-only AgentSafe configuration is refused before startup with `CONFIG_INVALID: PRESENCE_APPROVER_ID`.
- **Impact:** AgentSafe's high-level runtime cannot express Commerce's role-only configuration without an upstream API/configuration change. Selecting a household parent must remain trusted deployment configuration; it must never be accepted from Bedrock/MCP arguments.
- **Investigation:** Read the Commerce managed authority implementation and the published AgentSafe 0.2.5 configuration and `EscalationResolver` contracts. AgentSafe `MANAGED` still delegates the Presence ceremony to Decionis and does not require a Presence credential.
- **Workaround:** Require an administrator-provided household parent identity in the ignored `agentsafe/.env`; keep `PRESENCE_APPROVER_ROLE=APPROVER`. Do not invent an approver ID or place it in checked-in files.
- **Resolution:** This integration follows official AgentSafe managed mode and fails closed until the real identity is configured. The discrepancy is retained for review before onboarding a household that requires policy-selected, role-only approvers.
- **Upstream/documentation gap:** AgentSafe documentation describes MANAGED mode but the implementation requires a specific approver ID; the Commerce integration supports role-only routing. An optional approver ID when a trusted role is configured would align the high-level runtime with the existing authority contract.
- **Status:** Open configuration prerequisite; no mock approver is used.
