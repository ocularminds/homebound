# FL-030 — Alexa+ CodeArtifact role assumption is denied

- **Date:** 2026-10-02
- **Component:** Alexa+ developer CLI, AWS STS, CodeArtifact
- **Environment:** macOS; AWS CLI 2.37.8; Node.js 24.18.0 and npm 11; local credentials supplied through the ignored `agentsafe/.env`
- **Expected:** The provisioned non-root IAM user assumes Amazon's `AddOn3PDeveloperToolsRead` role, authenticates npm to Alexa+'s private CodeArtifact repository, and installs `@alexa-ai/cli`.
- **Observed:** STS caller identity matched the intended IAM user. The user had the documented inline `sts:AssumeRole` permission for the Amazon role, but the role assumption was denied before CodeArtifact authentication began.
- **Error:** `AccessDenied` for `sts:AssumeRole` on `arn:aws:iam::372468808636:role/AddOn3PDeveloperToolsRead`.
- **Impact:** No CodeArtifact token was issued, npm configuration was not persisted, and `@alexa-ai/cli` remains uninstalled.
- **Investigation:** Rechecked the caller identity, attached inline policy, and lack of a permissions boundary. Amazon's setup guide says to use the AWS account supplied to the Alexa Solutions Architect. The target role is Amazon-managed, so its trust configuration cannot be inspected from this account. An account enrollment/trust issue is likely; an organization-level explicit deny has not been ruled out.
- **Workaround:** None. The install stopped at the denied role assumption. No public-registry substitute, broader IAM policy, or role-trust bypass was used.
- **Resolution:** Pending confirmation from the Alexa Solutions Architect that this AWS account is enrolled and trusted by `AddOn3PDeveloperToolsRead`, or diagnosis of an organization-level deny.
- **Upstream/documentation gap:** The setup guide documents the assume-role profile but does not expose a self-service check for partner account enrollment or the Amazon-managed role's trust conditions.
- **Status:** Open; blocked on Amazon-side enrollment/trust confirmation or AWS organization policy review.
