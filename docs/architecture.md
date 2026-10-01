# HomeBound architecture and delivery phases

## Locked pitch

> Alexa can unlock your front door or disable your Ring camera—but should it? We’re building a zero-trust control layer for AI-powered homes with Decionis, ensuring AI agents act only on authorized actions.

## Four separate layers

```text
Bedrock / Alexa+ orchestration
    understands the request and selects a tool
              ↓
HomeBound MCP + AgentSafe interception
    captures an exact proposal and prevents direct device access
              ↓
Decionis Execution Authority + managed Presence
    evaluates policy and returns ALLOW, ESCALATE, or BLOCK
              ↓
Ring execution adapter
    performs the authorized action and records device state
```

Bedrock is the live orchestration integration in the prototype. Alexa+ MCP add-on onboarding is a separate partner-gated deployment step. The MCP service is a real Streamable HTTP server; its handlers never call a Ring SDK. The official Decionis AgentSafe runtime runs as a separate trusted process because its supported executor is Node.js. The HomeBound application, MCP server, scenarios, and simulator remain Python.

## PR phases

1. **Orchestration and MCP contract** — Python package, Streamable HTTP MCP endpoint, Bedrock Converse tool-use loop, schemas, and fail-closed tool responses. No device can execute in this phase.
2. **AgentSafe and Decionis authority** — connect Python MCP tools to the official `@decionis/agentsafe` executor; configure real Decionis credentials, exact action bindings, managed Presence escalation, grant consumption, and durable escalation resume state. Physical dispatch remains disabled until Phase 3.
3. **Ring simulator and complete scenarios** — wire the authorized executor to a stateful Ring simulator; configure the household policy; run the three prescribed scenarios; retrieve the exact signed Decision Dossier from Decionis and verify it with the official verifier; add binding, replay, expiry, and audit integration coverage and final demo documentation.

Each phase is delivered as its own pull request. Later PRs stack on the previous phase until merged.

## Phase 1 request path

1. The Bedrock Converse API receives natural language and the MCP tool schemas.
2. Bedrock selects `unlockDoor`, `disarmSystem`, or `viewStream`.
3. The Python orchestration client invokes that tool over Streamable HTTP MCP.
4. The tool creates a typed action proposal and sends it to the interception port.
5. Until AgentSafe is configured, the port returns `BLOCK / NOT_PERFORMED`.

Bedrock does not receive Ring credentials, policy rules, or a device SDK. A model tool call is a proposal only.

## Integration sources and constraints

- MCP uses the [official Python SDK](https://github.com/modelcontextprotocol/python-sdk)'s Streamable HTTP transport.
- Bedrock uses the AWS SDK for Python (`boto3`) and the [Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html) tool-use contract.
- The official Decionis [AgentSafe runtime](https://www.npmjs.com/package/@decionis/agentsafe) is distributed for Node.js. HomeBound will keep it as an isolated process instead of reimplementing its execution authority in Python.
- Decionis managed Presence is the human approval path. Following Commerce, HomeBound asks Decionis to manage Presence and resumes the exact AgentSafe handoff; HomeBound does not call Presence directly. The official AgentSafe executor requires a household approver identity in trusted managed-mode configuration; this identity never comes from the agent proposal.
- Ring hardware is not required. Physical execution will use a clearly labelled Python simulator adapter.

The reviewed [Alexa+ add-on documentation](https://developer.amazon.com/docs/alexaplus/add-ons/home.html) describes a selected-partner access program. A live Alexa+ claim requires onboarding through Amazon; the Bedrock route is the active orchestration integration in this prototype.
