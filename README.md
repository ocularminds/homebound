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

The work is split into three PRs as requested. See [the architecture and phase plan](docs/architecture.md). **Phase 1 is the current PR:** the Bedrock and MCP request path is real, and consequential requests fail closed until AgentSafe and Decionis are configured in Phase 2. No Ring device action executes in Phase 1.

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

## Three target scenarios

The complete demo is planned for Phase 3 and will run against a configured Decionis tenant and the Ring simulator:

1. **Kids Home Alone:** child asks to disarm the system → `ESCALATE` → parent completes Decionis Presence approval → exact action may proceed.
2. **High-Value Courier, authorized window:** expected courier requests the side gate during the allowed window → `ALLOW` → simulator unlocks the gate.
3. **High-Value Courier, wrong time:** same courier outside the delivery window → `BLOCK` → simulator remains locked.

Identity and intent alone do not establish authority. The third scenario tests that distinction.

## Integration status

- **MCP:** real Python SDK server over Streamable HTTP.
- **Agent orchestration:** real Bedrock Converse tool-use path; live AWS calls need the user's AWS profile and model access.
- **AgentSafe:** Phase 2 will use the official Decionis Node.js executor as a separate process. The HomeBound application remains Python; it will not reimplement AgentSafe's execution boundary.
- **Decionis and Presence:** Phase 2 will use Decionis Execution Authority with managed Presence escalation. The connector will not call Presence directly. Real tenant credentials and a configured approver/policy are required for the approval ceremony.
- **Ring:** Phase 3 will use an explicitly labelled simulator. No physical Ring hardware or API integration is claimed.
- **Alexa+:** the MCP contract is suitable for connection after account onboarding. Amazon's public Alexa+ add-on material currently describes a selected-partner program, so this repository does not claim an active Alexa+ account integration.

## Friction Log Summary

- The current shell has no active AWS credentials, so the Bedrock call cannot yet be live-verified here. See [FL-001](friction-log/FL-001-aws-credentials.md).
- Alexa+ add-on onboarding is partner-gated. Bedrock is the active orchestration path while access is pending. See [FL-002](friction-log/FL-002-alexa-plus-partner-onboarding.md).
- The official AgentSafe executor runs as a Node.js process. The project will integrate that boundary from Python over HTTP instead of recreating it. See [FL-003](friction-log/FL-003-agentsafe-runtime-language.md).
- Python dependencies required an approved network-enabled install, and the shell has multiple Python interpreters. Phase 1 was verified in the repository's `.venv`; see [FL-004](friction-log/FL-004-package-network-restricted.md) and [FL-005](friction-log/FL-005-mixed-python-runners.md).
- The sandbox blocked the initial loopback HTTP smoke test; it passed through the approved local-network verification path. See [FL-006](friction-log/FL-006-loopback-smoke-test.md).

Every implementation obstacle and workaround is recorded under [`friction-log/`](friction-log/).
