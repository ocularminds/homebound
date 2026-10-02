# FL-015 — Bedrock inference blocked by AWS account verification

- **Date:** 2026-10-01
- **Component:** Amazon Bedrock Runtime Converse tool-use orchestration
- **Environment:** AWS MCP, `us-east-1`, Nova Lite inference profile `us.amazon.nova-lite-v1:0`
- **Expected:** A non-action Converse smoke request returns the selected declarative tool call so the Bedrock tool-use path can be validated.
- **Observed:** The request reached the Bedrock Runtime API, but the service rejected it before model inference.
- **Error:** `AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation.` AWS's response says to contact `aws-verification@amazon.com` if the error persists beyond two hours.
- **Impact:** No live Bedrock generation or tool selection can be claimed yet. The local Bedrock orchestrator cannot be validated against this account until verification completes.
- **Investigation:** Confirmed the model identifier and region were already selected for the prototype. The failure is an account-level verification gate, not a model schema or application exception.
- **Workaround:** None that safely demonstrates real Bedrock orchestration. Keep local tests and the Ring simulator available, and retry after AWS verification completes.
- **Resolution:** Resolved 2026-10-02. A live Converse request on the exact configured profile `us.amazon.nova-lite-v1:0` in `us-east-1` returned a response (8 tokens). Bedrock inference is active; this did not invoke any Ring tool.
- **Upstream/documentation gap:** AWS's error provides the verification window and support contact but no status endpoint for this gate.
- **Status:** Resolved for model inference. The earlier account-verification rejection no longer reproduces.
