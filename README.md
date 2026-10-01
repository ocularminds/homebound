# HomeBound

**Alexa can unlock your front door or disable your Ring camera—but should it?** HomeBound demonstrates a zero-trust control layer that separates an AI agent's request from the authority to execute it.

## Architecture

```text
1. Orchestration     Amazon Bedrock Converse (Alexa+ compatible MCP contract)
2. Interception      Python Ring MCP tools → official Decionis AgentSafe process
3. Governance        Decionis Execution Authority → managed Decionis Presence
4. Physical execution Ring simulator (no hardware required)
```

Alexa+ or Bedrock determines what the user wants. AgentSafe captures the proposed execution. Decionis decides whether that exact action is authorized. Ring executes only after authorization. The orchestration layer has no Ring SDK or direct device path.

The work is split into three PRs as requested. See [the architecture and phase plan](docs/architecture.md). **Phase 2 adds the official AgentSafe executor and Decionis-managed Presence path.** Physical Ring dispatch stays disabled in this phase; an authority `ALLOW` cannot operate a device until the simulator handler is introduced in Phase 3.

## Phase 1: run locally

Requirements: Python 3.10+, an AWS profile or IAM Identity Center session allowed to call Bedrock Runtime, and an enabled Bedrock model that supports tool use.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Set `AWS_REGION` and `BEDROCK_MODEL_ID` in your shell or `.env`, and configure AWS authentication through the standard AWS credential chain. The app does not store credentials. For IAM Identity Center, for example:

```bash
aws configure sso
aws sso login --profile homebound
export AWS_PROFILE=homebound
```

Start the Streamable HTTP MCP server in one terminal:

```bash
set -a && source .env && set +a
python -m app.cli.mcp_server
```

Ask the Bedrock agent in a second terminal:

```bash
set -a && source .env && set +a
python -m app.cli.ask 'Alexa, disarm the Ring system'
```

The Bedrock runtime selects from the real MCP tool schemas (`unlockDoor`, `disarmSystem`, `viewStream`). The Phase 1 interception port returns `BLOCK / NOT_PERFORMED`; the MCP server has no Ring adapter to bypass that result.

Run Phase 1 tests with:

```bash
python -m pytest
```

The Bedrock orchestration test uses an injected runtime response and makes no AWS request. To check the real AWS path, first verify your profile with `aws sts get-caller-identity`, then run the command above with a model ID enabled for Converse tool use.

## Phase 2: connect AgentSafe, Decionis, and managed Presence

The trusted execution authority runs separately from Python. Use Node.js 22.14 or newer. The pinned `@decionis/agentsafe` 0.2.5 runtime captures the MCP proposal, asks Decionis for an exact-action verdict, owns grant consumption, and uses Decionis-managed Presence for escalations. HomeBound never calls Presence directly.

1. Copy `agentsafe/.env.example` to `agentsafe/.env` and set the real Decionis tenant UUID, server-side API key, household parent approver identity, and a strong executor caller token. The token must match `HOMEBOUND_AGENTSAFE_BEARER_TOKEN` in the root `.env`.
2. Install and start the executor:

   ```bash
   fnm use 22.23.2
   cd agentsafe
   npm ci
   ./run-local.sh
   ```

3. In the root `.env`, uncomment `HOMEBOUND_AGENTSAFE_URL` and `HOMEBOUND_AGENTSAFE_BEARER_TOKEN`, then start the Python MCP server from the repository root as above.
4. After Decionis Presence approval, resume the saved handoff once using the correlation ID returned by the MCP action:

   ```bash
   python -m app.cli.resume_escalation CORRELATION_ID
   ```

The resume command presents AgentSafe's saved managed escalation handoff unchanged. AgentSafe checks expiry and intent binding, asks Decionis to resolve the Presence result, and executes only after Decionis returns an authorized grant. In this PR, the registered handler intentionally fails before AgentSafe's dispatch boundary because the Ring simulator arrives in Phase 3. An `ALLOW` therefore means policy authorization only; it does not claim a device action occurred.

AgentSafe also requires a downstream URL and credential setting for its executor configuration. Phase 2 points those settings at the reserved `.invalid` domain and labels the local credential as unused. Its handlers do not request a downstream credential or call that URL. Do not replace these settings with Ring credentials until the simulator adapter lands in Phase 3.

AgentSafe's own journal records the decision, intent, and dossier identifiers before any future dispatch. Fetching the full Decionis dossier and verifying its signature through Decionis' published verification mechanism are explicit Phase 3 deliverables; this phase does not describe a dossier ID as the signed artifact.

## Three target scenarios

The complete demo is planned for Phase 3 and will run against a configured Decionis tenant and the Ring simulator:

1. **Kids Home Alone:** child asks to disarm the system → `ESCALATE` → parent completes Decionis Presence approval → exact action may proceed.
2. **High-Value Courier, authorized window:** expected courier requests the side gate during the allowed window → `ALLOW` → simulator unlocks the gate.
3. **High-Value Courier, wrong time:** same courier outside the delivery window → `BLOCK` → simulator remains locked.

Identity and intent alone do not establish authority. The third scenario tests that distinction.

## Integration status

- **MCP:** real Python SDK server over Streamable HTTP.
- **Agent orchestration:** real Bedrock Converse tool-use path; live AWS calls need the user's AWS profile and model access.
- **AgentSafe:** the official Decionis Node.js executor is a separate process; Python uses its authenticated HTTP API. In this phase, all ALLOW results stop before physical dispatch.
- **Decionis and Presence:** managed escalation is configured through AgentSafe; Decionis runs Presence and issues a grant after approval. HomeBound has no Presence credential or direct Presence client. Live decisions need a real tenant key, tenant UUID, policy, and household approver identity.
- **Ring:** Phase 3 will use an explicitly labelled simulator. No physical Ring hardware or API integration is claimed.
- **Alexa+:** the MCP contract is suitable for connection after account onboarding. Amazon's public Alexa+ add-on material currently describes a selected-partner program, so this repository does not claim an active Alexa+ account integration.

## Friction Log Summary

- The current shell has no active AWS credentials, so the Bedrock call cannot yet be live-verified here. See [FL-001](friction-log/FL-001-aws-credentials.md).
- No Decionis tenant key, tenant UUID, or parent approver identity is configured in this shell, so live authority decisions and Presence approval have not been claimed. See [FL-008](friction-log/FL-008-decionis-credentials-not-configured.md).
- Alexa+ add-on onboarding is partner-gated. Bedrock is the active orchestration path while access is pending. See [FL-002](friction-log/FL-002-alexa-plus-partner-onboarding.md).
- The official AgentSafe executor runs as a Node.js process. The project will integrate that boundary from Python over HTTP instead of recreating it. See [FL-003](friction-log/FL-003-agentsafe-runtime-language.md).
- AgentSafe's managed-mode configuration requires a trusted approver identity, while Commerce supports role-only escalation. HomeBound keeps the identity in ignored executor configuration, not in an agent proposal. See [FL-007](friction-log/FL-007-managed-approver-configuration.md).
- Python dependencies required an approved network-enabled install, and the shell has multiple Python interpreters. Phase 1 was verified in the repository's `.venv`; see [FL-004](friction-log/FL-004-package-network-restricted.md) and [FL-005](friction-log/FL-005-mixed-python-runners.md).
- The sandbox blocked the initial loopback HTTP smoke test; it passed through the approved local-network verification path. See [FL-006](friction-log/FL-006-loopback-smoke-test.md).

Every implementation obstacle and workaround is recorded under [`friction-log/`](friction-log/).
