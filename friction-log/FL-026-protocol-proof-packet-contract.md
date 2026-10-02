# FL-026 — Protocol dossier reads no longer include a verification URL

- **Date:** 2026-10-02
- **Component:** AgentSafe pre-dispatch Decision Dossier verification
- **Environment:** Live Decionis Protocol API, official `@decionis/verify`, local Ring simulator
- **Expected:** The org-scoped dossier response provides a signed proof reference the archiver can verify before dispatch.
- **Observed:** The dossier endpoint returned the tenant's stored dossier but no `verification.verification_url`. The separate tenant-bound proof-packet endpoint returned the dossier payload, proof bundle, and `subject` binding. The signed inner payload omits `org_id`; tenant association comes from the authenticated dossier row and proof packet subject.
- **Error:** The previous adapter rejected `DOSSIER_VERIFICATION_URL_MISSING`. Its follow-up approach also incorrectly expected `org_id` inside the signed payload.
- **Impact:** AgentSafe correctly stopped an authorized simulated unlock before device dispatch because the dossier could not be independently verified.
- **Investigation:** Compared the live endpoint response shapes with Decionis Protocol's proof-packet route and the installed verifier package. Confirmed the packet is tenant-bound, carries the signed bundle, and can be independently checked against the pinned production JWKS.
- **Workaround:** Fetch the org-scoped dossier and proof packet, require their dossier identifiers and tenant subject to match, require the packet's signed payload to match the archived dossier payload, and use `verifyDossierProofBundle` with the official Decionis JWKS. Preserve both raw responses. Dispatch is eligible only when signature verification, required-artifact coverage, and the official trust anchor all pass.
- **Resolution:** The live dossier verified with the official trust anchor and complete required-artifact coverage. The 16:00 courier action then executed on the simulator; the 18:01 courier action was blocked without simulator execution.
- **Upstream/documentation gap:** The installed integration's older public verification-URL contract does not describe the current tenant-bound proof-packet route or its unsigned subject tenant binding. The adapter now follows the Protocol proof-packet contract and independently verifies the signed payload.
- **Status:** Resolved for the current Protocol API and verifier package.
