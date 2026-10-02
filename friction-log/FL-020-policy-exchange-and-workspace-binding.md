# FL-020: Public demo pack versus production protocol policy

- **Date:** 2026-10-02
- **Component:** Decionis Policy Exchange and HomeBound workspace policy lifecycle
- **Environment:** HomeBound repository; public Decionis Policy Exchange contribution guide, Policy Encoding docs, and Commerce integration
- **Expected:** Policy Exchange packs provide examples for public demos. Real, editable household policy lives in Decionis Protocol as an org-scoped, versioned policy bundle. HomeBound associates the household with the org and active policy version.
- **Observed:** Decionis documents Policy Exchange packs as public YAML artifacts contributed by pull request, with `apiVersion`, `kind`, filename-matched `metadata.name`, at least one rule, and `defaults.mode: shadow`. Policy Encoding separately documents `POST /v1/protocol/policies/bundles` for org-scoped versioned artifacts. They serve different purposes.
- **Error:** Initially, HomeBound had no workflow to publish a protocol bundle or bind its org, bundle, version, and home identifiers.
- **Impact:** The public pack cannot serve as production policy or be treated as automatically copied into tenant workspaces. A protocol bundle and explicit home binding are required.
- **Investigation:** Reviewed the public Decionis Policy Exchange contribution guide, Policy Encoding contract, and Commerce's org policy bundle client. The Exchange is a public catalog; Commerce's protocol client uses org-scoped list/publish calls for tenant bundles.
- **Workaround:** Mark the catalog YAML public-demo-only and keep production rules in Decionis Protocol. The Phase 7 publisher merges reviewed rules into the existing bundle, verifies publication, and writes an ignored local binding record.
- **Resolution:** Published `homebound-household-v1` in the production tenant and recorded `home_id`, `org_id`, `bundle_id`, and version in `.homebound/policy-binding.json`. The Python MCP server includes that binding in every AgentSafe intent and audit record.
- **Upstream/documentation gap:** The current AgentSafe package does not expose Decionis' requested policy-version selector or return the selected version, so HomeBound cannot pin or verify the exact version at action time. Owner edits in the Decionis workspace must be synchronized into the local binding until that integration is available.
- **Status:** Production bundle and local association are in place. Automated workspace creation, owner roster enrollment, and active-version synchronization remain future product work.
