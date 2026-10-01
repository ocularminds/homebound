# HomeBound

> **Alexa can unlock your front door or disable your Ring camera—but should it?**
> HomeBound puts a zero-trust execution boundary between AI requests and consequential home actions.

An AI assistant can understand a request and choose a tool. That does not make the assistant an authority to operate a door, alarm, or camera. HomeBound sends each proposed action through Decionis Execution Authority before the local Ring simulator can execute it.

## Architecture

```text
Orchestration  Amazon Bedrock Converse (real tool-use integration; Alexa+ compatible MCP contract)
       ↓
Interception   Python MCP server → official Decionis AgentSafe executor
       ↓
Governance     Decionis Execution Authority → Decionis-managed Presence on escalation
       ↓
Execution      AgentSafe grant-bound dispatch → local Ring simulator
```

Alexa+ / Bedrock determines what the user wants. AgentSafe captures the proposed execution. Decionis decides whether the exact action is authorized. Ring executes only after authorization. The orchestration process has no Ring SDK, simulator token, or direct device path. The MCP server is a real Streamable HTTP server; the governance executor is the official [`@decionis/agentsafe`](https://www.npmjs.com/package/@decionis/agentsafe) package.

Decionis natively manages the Presence approval flow. HomeBound neither calls Presence directly nor stores a Presence API credential. For the current AgentSafe release, a trusted household approver identity is configured in the ignored executor settings; it is never accepted from an agent tool call.

## Project phases

Work is delivered in stacked pull requests:

1. [Phase 1 — Bedrock orchestration and MCP](https://github.com/ocularminds/homebound/pull/1)
2. [Phase 2 — Decionis AgentSafe and managed Presence](https://github.com/ocularminds/homebound/pull/2)
3. [Phase 3 — Ring simulator, verified dossier archive, and end-to-end demo](https://github.com/ocularminds/homebound/pull/3)

## What the demo runs

`python -m app.demo` starts the local AgentSafe executor and dossier archiver, Ring simulator, and MCP server. It then asks the configured Bedrock model to make exactly one MCP request for each scripted scenario. The model must preserve the fixture arguments; a mismatch stops the scenario before MCP. Outcomes still come from the configured Decionis tenant and policy—HomeBound does not hard-code a decision.

1. **Kids Home Alone:** at home at 15:00, a child requests `disarmSystem(home_security)`. Decionis should return `ESCALATE`. A parent approves in Decionis Presence; the demo resumes the saved AgentSafe handoff, and only a terminal authorized grant permits the simulated disarm.
2. **Courier, authorized window:** a recognized expected courier requests `unlockDoor(side_gate)` during the configured delivery window. Decionis should return `ALLOW`; the simulator unlocks the gate.
3. **Courier, wrong time:** the same request arrives outside that window. Decionis should return `BLOCK`; no simulator action runs and the side gate remains locked.

The scenario fixture passes the listed context fields through MCP for deterministic demonstration. They are scenario signals, not independent proof of a child's or courier's identity. A deployment must bind policy inputs to authenticated household, Ring, or delivery-system sources before using such signals to authorize a real device.

The simulator is not Ring hardware and does not contact Ring's API. It persists simulated device state, execution events, and replay fingerprints in a local SQLite database.

## Run the live demo

Requirements: Python 3.10+, Node.js 22.14+, AWS credentials permitted to call Bedrock Runtime, an enabled Converse tool-use model, a Decionis tenant/API key, and the household policy/approver configured in that tenant.

Install the Python package and create the local configuration files:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
cp agentsafe/.env.example agentsafe/.env
```

Configure AWS via its normal credential chain. For an IAM Identity Center profile:

```bash
aws configure sso
aws sso login --profile homebound
export AWS_PROFILE=homebound
```

In `.env`, set `AWS_REGION` and `BEDROCK_MODEL_ID`. In `agentsafe/.env`, set the real `EXECUTOR_TENANT_ID`, server-side `DECIONIS_API_KEY`, trusted household `PRESENCE_APPROVER_ID`, and strong random values for `EXECUTOR_CALLER_TOKEN`, `DOWNSTREAM_CREDENTIAL`, `HOMEBOUND_DOSSIER_ARCHIVER_TOKEN`, and `HOMEBOUND_SIMULATOR_DEMO_TOKEN`. Set the matching AgentSafe and archive bearer values in the root `.env` as shown by its comments. Keep both `.env` files local; they are ignored by Git.

Configure the tenant policy to return the expected decisions for the exact action and fixture context described above. The policy should require parent approval for a child disarm request, permit the expected courier inside the household's delivery window, and block that courier outside the window with a reason such as `OUTSIDE_AUTHORIZED_DELIVERY_WINDOW`. The household must also enable the corresponding Decionis-managed Presence approval. HomeBound cannot create or validate tenant policy without access to that tenant.

Install the pinned official Node dependencies and run the stack:

```bash
fnm use 22.23.2
(cd agentsafe && npm ci)
set -a && source .env && set +a
python -m app.demo
```

The first scenario pauses at the terminal while the parent completes the Presence approval. Press Enter after completing the Presence flow to have AgentSafe recheck the original handoff. The demo reports the initial and final decisions, execution result, correlation ID, and dossier identifier. A missing credential, invalid dossier proof, uncertain authority result, or changed proposal fails closed.

For local unit/integration coverage:

```bash
python -m pytest -q
(cd agentsafe && fnm exec --using=22.23.2 npm run check)
```

These tests use local fixtures for external Decionis and AWS responses; they do not claim a live authority or Presence transaction. Live integration validation requires the tenant, policy, approver, AWS profile, and model access listed above.

## Authorization and evidence

- AgentSafe constructs the Execution Intent Envelope and owns exact-action binding, grant claiming, expiry, idempotency, escalation resume, and the only downstream dispatch path.
- The simulator requires the authorization identifiers and exact action metadata bound by AgentSafe, records the grant ID and expiry, and rejects an expired grant. It refuses direct calls, missing evidence, request mutation, and idempotency-key reuse with changed content. AgentSafe owns one-time grant consumption; its grant token never leaves the trusted process.
- Before dispatch, the executor retrieves the org-scoped [Decionis Decision Dossier](https://decionis.com/docs/decision-dossier) and calls the official [`@decionis/verify`](https://www.npmjs.com/package/@decionis/verify) implementation against Decionis' published signing keys. An absent, invalid, or untrusted proof prevents dispatch.
- The exact returned dossier bytes and verifier result are retained under the local ignored `audit/dossiers/` directory. Python also appends action, decision, approval result, execution event, and dossier evidence to `audit/actions.jsonl`; AgentSafe keeps its own journal. These local artifacts contain sensitive household activity and are private to the developer machine.
- `BLOCK` never calls the simulator. `ESCALATE` never calls it until Presence has completed and AgentSafe returns authorization for the same handoff. The demo uses a separate reset token only to restore the simulated baseline between scenarios.
- No signature is synthesized in the simulator. Tests inject verifier responses only at the unit-test boundary; local live execution uses Decionis' dossier response and the official verifier.

## Integration status and boundaries

- **MCP:** real Python SDK Streamable HTTP server, declarative `unlockDoor`, `disarmSystem`, and `viewStream` tools, plus a governed escalation-resume tool.
- **Orchestration:** real Amazon Bedrock Converse tool-use integration. Alexa+ itself is not activated in this repo; connecting it requires Amazon's Alexa+ add-on partner onboarding. No Alexa+ production integration is claimed.
- **AgentSafe / Decionis / Presence:** official AgentSafe executor, Decionis authority, and native Decionis-managed Presence path. No direct Presence API integration or credential exists in HomeBound.
- **Ring:** local simulator only. No physical Ring SDK, account, device, camera stream, or door is contacted.
- **Household signals:** demo context is a deterministic fixture. Production use needs authenticated signals and a tenant policy that accounts for signal provenance.
- **External validation:** no live AWS or Decionis request was made from this development shell because credentials and tenant identity are not configured here. See [FL-001](friction-log/FL-001-aws-credentials.md) and [FL-008](friction-log/FL-008-decionis-credentials-not-configured.md).

## Friction Log Summary

Implementation issues and workarounds are tracked in [`friction-log/`](friction-log/). In addition to the missing local AWS/Decionis credentials (FL-001, FL-008), the official AgentSafe managed-mode configuration currently requires a trusted approver identity even though the Commerce adapter can request role-only routing (FL-007). The Decionis verifier URL format also needed normalization to its signed proof-bundle endpoint (FL-010), and AgentSafe's lookup URL disallows query parameters, so archive/reconciliation share a method-routed local endpoint (FL-009). Alexa+ remains partner-onboarded rather than enabled by this repo (FL-002). No workaround substitutes mock authority decisions or cryptographic signatures for live Decionis results.
