# FL-028 — Alexa+ developer CLI is behind partner-only CodeArtifact access

- **Date:** 2026-10-02
- **Component:** Alexa+ MCP Toolkit, Alexa AI CLI, Amazon Developer onboarding
- **Environment:** Amazon Developer portal session; Node.js 24.18.0; AWS account in us-east-1
- **Expected:** Install the Alexa AI CLI, authenticate the developer account, and inspect available add-ons to determine whether HomeBound can be activated in Alexa+.
- **Observed:** The documented public npm command returned E404 for @alexa-ai/cli. Amazon's current setup guide configures the @alexa-ai scope to a private CodeArtifact registry and requires assuming AddOn3PDeveloperToolsRead. The Alexa+ for Builders page says access is currently limited to selected partners.
- **Error:** npm E404 from the public npm registry. AWS STS returned AccessDenied: Roles may not be assumed by root accounts for the Alexa+ developer-tools role.
- **Impact:** The Alexa AI CLI could not be installed from the public registry, so this account's add-on list, deploy entitlement, and web simulator access could not be checked. No Alexa+ add-on was created or deployed.
- **Investigation:** AWS STS reports the current caller as the account root, and IAM ListUsers returned no IAM users. Amazon's setup guide requires a non-root IAM principal with sts:AssumeRole permission and CodeArtifact authentication. The signed-in Amazon Developer portal exposes the public Alexa+ for Builders page, which has no self-service partner enrollment control.
- **Workaround:** None used. Bedrock remains the working real orchestration path. No public-registry substitute or untrusted package source was used.
- **Resolution:** Pending Alexa+ partner access and a non-root developer identity authorized to assume Amazon's CodeArtifact role. Do not create long-lived IAM access keys just to bypass the private registry boundary.
- **Upstream/documentation gap:** The install command alone yields a misleading npm 404 unless the earlier private CodeArtifact authentication and role-assumption steps are completed. Public Alexa+ documentation also describes MCP tooling as available to selected partners only.
- **Status:** Open; requires Amazon Alexa+ partner onboarding and a suitable non-root AWS developer principal.
