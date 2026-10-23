# Product feedback

Prepared for Build, Ship, Shape: Amazon Developer Hackathon. These observations
describe this project's actual use; packaged AWS infrastructure is distinguished
from the live local demo. Detailed integration reports are in [`friction-log/`](../../friction-log/).

## Amazon Fire TV / Vega

**Use:** The primary HomeBound canvas runs in Amazon WebView inside a Vega React
Native application. We used SDK 0.24.12112, the `vegaWebview` starter, CLI release
builds, Virtual Device, and VDA reverse forwarding to the local backend.

**Worked:** The starter adapted our existing HTML/CSS/JavaScript canvas with a
small native shell. The build validates the manifest and produces installable
packages for three architectures. The simulator lets us work without hardware.

**Needs work:** A clearer one-page WebView-to-simulator quickstart should include
host networking, cleartext policy, remote key handling, and the correct artifact
path. In a command runner that ends its process group, the CLI reported “ready”
but the simulator then stopped; keeping the terminal session alive resolved it.
The generated build also emitted a missing optional assets-directory warning.
WebView inspector access on port 9229 failed in this image. The original media
encode stalled; a one-reference H.264 Constrained Baseline export played through
both commercial breaks. A verified media manifest and codec sample would help.
See [FL-033](../../friction-log/FL-033-vega-packaging-and-media-playback.md).

**Onboarding:** Installation and the first release package succeeded on Apple
Silicon. The template's dependency tree includes npm audit advisories; developers
need a vendor-supported upgrade path rather than a forced SDK dependency update.

**Build again:** Yes. It makes the shared television a practical interface for
contextual home assistance, especially when a simulator is available early.

## Amazon Bedrock

**Use:** Real Converse calls interpret user requests, structured tool proposals,
and our own illustrated scene images. The current demo uses the Amazon Nova Lite
inference profile. AgentCore and Guardrails deployment adapters are also packaged.

**Worked:** Tool use and image context let the same conversational layer support
notes, recipes, draft shopping, and a coordinated room preview. Typed proposals
keep model output separate from deterministic audience and execution rules.

**Needs work:** Model names versus inference-profile ids, account activation,
and availability errors need clearer, actionable onboarding messages. Expired
local CLI sessions should be easier to distinguish from model-permission errors.

**Onboarding:** Account/model access and exact model compatibility were the main
early friction. The latest scene request returned successfully after refreshing
AWS CLI login. See FL-015 and the runtime compatibility history.

**Build again:** Yes, with deterministic proposal validation and explicit
authorization outside the model. The AWS Builder integration is the live Bedrock
path; we do not equate a CloudFormation template with a deployed service.

## Alexa+ / Alexa-style companion

**Use:** An Alexa-style web and voice companion shares the TV's home state.
The repository implements a real MCP server, but Alexa+ partner access was not
granted. Deepgram and Bedrock power the demonstrated companion.

**Worked:** A shared conversation and home state complement TV well: a note can
be dictated on one surface and shown to its intended viewer on another.

**Needs work:** A public sandbox, an accessible MCP package, and clear partner
eligibility would reduce uncertainty for hackathon developers. The documented
private CodeArtifact role assumption was denied for our provisioned IAM user.

**Onboarding:** The team recommended a simulator; that let us demonstrate the
interaction while accurately disclosing the missing Alexa+ connection. See
FL-028 and FL-030 for the exact partner-access issue.

**Build again:** Yes as a complementary interface when partner onboarding is
available. Fire TV is this entry's primary experience.

## Ring, Decionis, and supporting tools

**Use:** A separate governed-device demonstration uses a local Ring simulator,
official Decionis AgentSafe and Verify packages, real Decionis decisions, and a
signed dossier archive. Ring hardware and real camera recognition are unconnected.

**Worked:** Exact-action binding and independent signature checks make proposed
home actions auditable. A draft or proposal cannot silently become execution.

**Needs work / onboarding:** AgentSafe action naming, policy schemas, and proof
packet formats required live integration diagnosis. The managed parent-approval
path remains blocked by a missing tenant Presence connection (FL-032). We do
not stage a fake approval ceremony or lead the TV film with gate opening.

**Build again:** Yes, after making provider capabilities and tenant prerequisites
explicit. Deepgram supports the optional continuous voice interface; Runway was
used to create original cartoon and commercial media, with provenance included.
