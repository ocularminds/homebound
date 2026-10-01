# FL-020: Public demo pack versus production protocol policy

- **Date:** 2026-10-02
- **Component:** Decionis Policy Exchange and HomeBound workspace policy lifecycle
- **Environment:** HomeBound repository; public Decionis Policy Exchange contribution guide, Policy Encoding docs, and Commerce integration
- **Expected:** Policy Exchange packs provide examples for public demos. Real, editable household policy lives in Decionis Protocol as an org-scoped, versioned policy bundle. HomeBound associates the household with the org and active policy version.
- **Observed:** Decionis documents Policy Exchange packs as public YAML artifacts contributed by pull request, with `apiVersion`, `kind`, filename-matched `metadata.name`, at least one rule, and `defaults.mode: shadow`. Policy Encoding separately documents `POST /v1/protocol/policies/bundles` for org-scoped versioned artifacts. They serve different purposes.
- **Error:** HomeBound has no workspace creation flow or Decionis workspace provisioning callback to create/record a protocol bundle and bind its active version to a home.
- **Impact:** The public pack cannot serve as production policy or be treated as automatically copied into tenant workspaces. The repository cannot claim production policy is installed until a protocol bundle is created and its org/bundle/version association is recorded for the home.
- **Investigation:** Reviewed the public Decionis Policy Exchange contribution guide, Policy Encoding contract, and Commerce's org policy bundle client. The Exchange is a public catalog; Commerce's protocol client uses org-scoped list/publish calls for tenant bundles.
- **Workaround:** Mark the catalog YAML public-demo-only. Keep real policy in Decionis Protocol. Record the intended HomeBound binding as `org_id`, protocol bundle key/id, active version, and home identifier; do not copy the public pack automatically.
- **Resolution:** Updated the pack and README to make the demo-only boundary explicit. Kept the HomeBound protocol draft local and unpublished because its rule fields and input provenance are not validated for enforcement.
- **Upstream/documentation gap:** The public Exchange workflow documents catalog contribution, while workspace-to-home policy association remains a HomeBound product lifecycle requirement. The production policy API is documented separately.
- **Status:** Policy Exchange PR is open as a public demo contribution; production protocol policy provisioning and home-version binding are not implemented. The existing tenant has no HomeBound bundle; prior evaluation failed closed without a managed Presence handoff.
