# FL-010 — Decision Dossier verification URL normalization

- **Date:** 2026-10-01
- **Component:** Decionis Decision Dossier archival and verification
- **Environment:** official `@decionis/verify` 0.4.0 and Decionis API
- **Expected:** Retrieve the org-scoped dossier, follow its verification reference, verify its signature, then preserve the exact returned dossier and verification result.
- **Observed:** The dossier's published `verification_url` can identify the public `/verify` route, while the official verifier fetches a signed `/proof-bundle` route. Both are same-origin public dossier URLs carrying the signature query value.
- **Error:** Passing the `/verify` URL directly into the verifier does not use the proof-bundle payload shape expected by `verifyDossierFromUrls`.
- **Impact:** Dossier signature verification could not be handed directly from the dossier response to the verifier library.
- **Investigation:** Checked the Decionis dossier payload and the installed official verifier contract; confirmed that the verification URL must be constrained before deriving a proof-bundle URL.
- **Workaround:** Accept only the exact dossier-specific `/verify` or `/proof-bundle` path on the configured Decionis HTTPS origin and require its signed `sig` query value. Normalize `/verify` to the dossier's corresponding `/proof-bundle` route while preserving the signature parameters, then use `@decionis/verify` and its official JWKS trust anchor.
- **Resolution:** The archive client rejects alternate hosts and paths, checks the verified payload's dossier ID, requires both a verified signature and trusted Decionis anchor, and stores the raw dossier bytes unchanged with verification metadata.
- **Upstream/documentation gap:** The relationship between the user-facing verification URL and the proof-bundle route expected by the verifier package should be explicit in integration examples.
- **Status:** Resolved in Phase 3; unit tests cover URL refusal and verifier usage. Live Decionis verification awaits tenant credentials (FL-008).
