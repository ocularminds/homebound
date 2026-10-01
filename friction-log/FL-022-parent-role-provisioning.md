# FL-022 — Parent email roster is not synchronized by the current CLI

- **Date:** 2026-10-02
- **Component:** HomeBound household setup → Decionis Accounts → Presence role assignments
- **Environment:** HomeBound Python CLI prototype; Commerce reference implementation available locally
- **Expected:** The household owner defines one or more parent emails with the `parent` role. Enrolled parents are eligible for Decionis-managed Presence escalation.
- **Observed:** The Commerce reference resolves approvers as Accounts workspace members and grants Presence's `APPROVER` role with the signed-in owner's `dcn_ps_` product session. HomeBound has no owner sign-in, email invitation, member-resolution, or role-sync UI. The AgentSafe demo currently uses one configured trusted approver ID.
- **Error:** None; this is a HomeBound feature gap, not a failed Presence request.
- **Impact:** The CLI cannot manage a set of parent email-to-member identities. The owner may enroll parents in the Decionis workspace for this prototype; a HomeBound enrollment UI is optional for a later phase.
- **Investigation:** Read Commerce `web/app/presence.server.ts`, its Presence tests, and the approval-chain settings flow. Presence role assignments are performed as the authenticated workspace owner; action-time approval remains Decionis-managed and the action connector does not choose the approver.
- **Workaround:** Use the Decionis workspace to enroll parent members and assign the Presence `APPROVER` role. The local demo remains pinned to its configured approver and fails closed when Decionis does not return a managed escalation.
- **Resolution:** The initial demo path is documented. HomeBound-owned email roster management and synchronization are not implemented.
- **Upstream/documentation gap:** None identified in the Commerce reference flow. HomeBound has no owner-authenticated workspace lifecycle yet.
- **Status:** Open for a future HomeBound UI phase
