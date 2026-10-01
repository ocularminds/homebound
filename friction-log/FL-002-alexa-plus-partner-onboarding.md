# FL-002 — Alexa+ MCP add-on onboarding is partner-gated

- **Date:** 2026-10-01
- **Component:** Alexa+ MCP add-ons
- **Environment:** Amazon Developer portal and public Alexa+ add-on documentation
- **Expected:** Register and test a HomeBound MCP endpoint as an Alexa+ add-on during prototype development.
- **Observed:** Amazon's public documentation describes add-on onboarding as available to selected partners working directly with Amazon.
- **Error:** No public self-service registration path was available in the reviewed portal/docs.
- **Impact:** A live Alexa+ invocation cannot be claimed until the account is enrolled and the add-on is approved.
- **Investigation:** Confirmed the add-on transport is remote Streamable HTTP MCP and identified the Alexa+ requirements separately from the local Bedrock agent.
- **Workaround:** Use Bedrock Converse as the real natural-language orchestration path. Keep the MCP tool contract compatible with the documented Alexa+ transport for later connection.
- **Resolution:** Pending partner onboarding.
- **Upstream/documentation gap:** Eligibility and access require direct Amazon partner contact; self-service availability was not found.
- **Status:** Open
