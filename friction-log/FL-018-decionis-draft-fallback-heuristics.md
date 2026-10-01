# FL-018 — Decionis policy draft fallback is not an enforcement artifact

- **Date:** 2026-10-01
- **Component:** Decionis workspace policy-source drafting
- **Environment:** Browser-authenticated Decionis workspace console
- **Expected:** The supplied HomeBound policy source produces a structured draft with reviewable action predicates and a managed Presence authority block.
- **Observed:** Draft generation displayed “fallback extraction heuristics” and `used_llm: false`. It copied large portions of source prose into generic `auto_execute`, `escalate_for_review`, and `ignore_or_block` text arrays.
- **Error:** The generated draft had no exact Ring action/target predicates and no authority resolution fields.
- **Impact:** The output cannot safely govern Ring actions or trigger Presence.
- **Investigation:** Reviewed the generated draft's strategy JSON and the official policy-encoding docs. The docs describe this route as a non-persistent drafting aid; the generated fallback clauses are not a compiled protocol bundle.
- **Workaround:** Do not apply or publish that draft. Translate the requirements into a local, visibly unvalidated policy draft, and leave the existing commerce policy untouched.
- **Resolution:** Draft-generation result remains non-persistent and was not applied. Local rule draft is `policies/homebound-household-policy.draft.json`.
- **Upstream/documentation gap:** The console presents a versionable strategy draft even when fallback extraction is not capable of producing executable policy predicates; the review UI requires users to recognize that limitation.
- **Status:** Open; needs Decionis policy-owner review and dry-run validation.
