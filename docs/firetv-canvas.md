# FireTV ambient canvas

HomeBound turns a living-room screen into a context-sensitive companion: the right note for the person present, a recipe that accounts for the pantry, or a quiet view of home during a break. The implementation lives at `/tv`, alongside the Alexa-style voice screen at `/`.

This is a browser prototype with original illustrated scenes. Bedrock interpretation and the configured Deepgram speech service are real. Ring/Alexa+ sensors, physical FireTV playback, camera video, weather, commercial detection, product offers, and Amazon Pay are not connected. The AWS supervisor and transports are implemented and tested with service fixtures, with infrastructure supplied for a separate deployment.

## Try the experience

Start the configured stack from the project root using the [web simulator instructions](web-simulator.md):

```bash
source .venv/bin/activate
set -a
source .env
set +a
fnm exec --using=22.23.2 python -m app.cli.web --with-services
```

Open [the TV canvas](http://127.0.0.1:8300/tv). **Demo signals** selects local audience, media, break, and pantry fixtures. The Alexa screen can dictate notes into the same home. The TV microphone is opt-in, retains its connection between turns, and suspends recording during synthesized replies. The Alexa screen keeps its existing automatic listener and greeting. Avoid enabling both microphones in the same room.

| Moment | Try | Result |
| --- | --- | --- |
| A child arrives | Demo signals → Leo | The sample homework reminder appears. |
| A dictated note | “Tell Mom I took the dog out,” then Demo signals → Mom | The saved personal note appears when Mom is alone. |
| An intense movie | Demo signals → After the last light | Personal note text waits behind a small generic indicator. |
| An interruption | Demo signals → Commercial break | A dashboard and eligible notes replace the illustrated program view. |
| The program returns | Demo signals → Program resumes | The original program returns immediately on the next projection. |
| A guest arrives | Demo signals → A guest joins | Personal note bodies disappear from the API and the screen. |
| Dinner inspiration | Select The weekend table, then “What are they cooking?” | Scene recipe and pantry availability appear. Olive oil is initially missing. |
| A changed pantry | Demo signals → Restock olive oil | Open recipe cards update to “You have all the ingredients.” |
| A scene item | Select After the last light, then “I like that jacket” | A similar demo jacket appears with an illustrative price. |
| Review before buying | “Add that to my cart” | An editable draft cart appears. No order or payment is submitted. |
| Read with the game on | “I want to read a book but keep the game on in the background” | Game, mute, captions, dimmed TV area, and brighter reading lamp are previewed. |
| Restore | “Restore the room” | The previous room and program preview return. |

The surface supports directional-key focus navigation, visible focus indicators, touch, keyboard input, and responsive layouts. It contains no persistent sidebar. Notes and shopping panels are temporary parts of the media canvas.

## Video and notes during commercials

The video player uses separate program and commercial elements. For the planned
one-minute cartoon, it pauses the program at 20 and 42 seconds, plays a six-second
house promo, and returns to the actual paused position. These are explicit ad
cues for an owned local video, not automatic detection inside another streaming
service. The viewer can pause an ad to read a note, replay the short, enable
sound, or enable captions. Browser autoplay starts muted.

Eligible notes appear beside the commercial. They disappear locally as soon as
it ends, before waiting for the server's program-resumed response. Audience,
guest and freshness checks still apply. A late callback from an older playback
session cannot start a break or restore its old program after the viewer has
selected something else. Hidden tabs suspend playback.

**Production status:** the requested rabbit-and-bulldog cartoon is awaiting the
user's Runway connection and has not been generated. Its
[storyboard](../media/park-chase/brief.md) and
[generation prompts](../media/park-chase/runway-prompts.md) are prepared. The
selector says “Film being prepared” until all five exports exist and are
nonempty under `app/web/static/media/`: `park-chase.mp4`,
`park-chase-poster.jpg`, `park-chase.vtt`, `movie-night-ad.mp4`, and
`popcorn-ad.mp4`. The target is a 60-second H.264/AAC program and two six-second
H.264/AAC promos, with a poster and English captions. Review the actual Runway
outputs and verify their duration, codecs and sound before publishing them.

Once the exports are ready, select the short in **Demo signals**, or open
`/tv?play=park_chase`. Files are served with HTTP byte-range support and are
included in the Python package. Video is streamed to this browser canvas;
physical FireTV casting remains an integration task. Synthetic test clips are
kept in the ignored test workspace and are never published as the cartoon.

## What runs where

| Component | Local behavior | AWS path supplied |
| --- | --- | --- |
| Supervisor | Bedrock Converse selects one `composeCanvas` proposal | The same planner runs behind AgentCore `/invocations`. |
| Context agent | Server selects notes for the current audience and attention level | Routed presence events trigger the same receiver policy. |
| Media agent | Fixed room preview and signalled break/program transitions | Ordered media events retain their original playback ID and time. |
| Shopping agent | Known scene metadata, pantry snapshot, and demo catalog join | Inventory events refresh the same catalog projection. |
| Memory | One private SQLite store per local home | AgentCore Memory is a future adapter, not implemented. |
| Screening | Conservative local demo checks | Standalone `ApplyGuardrail` against a numbered published version. |
| Execution | Canvas state and draft cart only | Physical adapters still require AgentSafe and Decionis. |

Natural-language and image interpretation is probabilistic; audience, timing, inventory freshness, cart totals, and permitted state changes are deterministic. For scene questions, the planner sends only the simulator's own cooking/movie PNG plus fixed metadata. It does not capture protected video, browse for products, identify people in images, or invent a purchasable offer. “Generative UI” here means selecting and populating reviewed components using a closed schema, not rendering model-generated HTML or JavaScript.

The default local path is:

```text
Alexa / TV request -> Bedrock Converse -> typed proposal
                                         |
local demo events -> Context / Media / Shopping -> filtered JSON -> TV
                         |
                 local notes and state
```

The optional deployment path is:

```text
Normalized event -> EventBridge V2 custom bus -> SQS FIFO
    -> Lambda -> AgentCore supervisor -> SQS FIFO -> home receiver -> TV
```

Events route by kind without an LLM call. A request to plan a conversation invokes Bedrock separately. Model latency never holds the local state lock while an audience change is waiting. Cloud delivery remains asynchronous and has not been latency-tested in AWS.

## Privacy and state lifecycle

- Personal notes require exactly their recipient, alone, with a fresh presence signal. Unknown, stale, empty, mixed, or guest audiences do not receive their bodies. A note explicitly addressed to everyone may appear while a guest is present with a known resident.
- Audience filtering happens before the browser projection. Hidden bodies are absent from `/api/canvas`, the inference context, and the orchestration trace. The trace contains generic outcomes only.
- A dictated note must preserve the supplied body and an explicit recipient outside that body. A name mentioned within a note cannot become its delivery audience. No parent role, identity, or device authority is inferred from speech.
- Presence expires after five minutes; notes expire after 24 hours; pantry availability becomes unknown after 24 hours. Expired notes stop displaying and stored rows are pruned on subsequent writes. Local SQLite has owner-only file permissions; deploy on an encrypted, access-controlled host for real household data.
- A focused program displays only a generic waiting indicator. Notes can appear during its break. A program-resumed event restores the view; a 90-second deadline measured from the observed break time is the fail-safe when that signal is lost. A queued break cannot extend that deadline.
- Source sequence and observation-time watermarks reject older updates. A break from an old playback ID cannot replace a newer program. Event receipts and note creation survive restarts, reject changed payloads reusing an ID, and deduplicate for 24 hours. Sequence watermarks outlive that window.
- The browser removes personal notes when hidden, offline, or without a fresh response for three seconds. It ignores responses older than its last projection. A future production TV needs a similarly bounded local privacy fallback.
- Model-selected items are checked against the known scene. A program change during inference cancels scene-dependent requests. The cart uses catalog prices and quantities, has no checkout URL, and cannot submit a payment.
- Reading mode changes only the virtual room. Its fixed five-step plan and restored preview carry no physical execution claim or fabricated Decionis grant.

This is one home, one web process, and one canvas. Do not expose the loopback server as a household authentication system. Production needs pairing, authenticated sensor provenance, per-home access isolation, an audience-consent model, retention controls, and supported device/media adapters.

## Bedrock Guardrails

Configure a published policy using the non-secret root environment settings:

```dotenv
HOMEBOUND_CANVAS_GUARDRAIL_ID=<published-guardrail-id>
HOMEBOUND_CANVAS_GUARDRAIL_VERSION=<numbered-version>
HOMEBOUND_CANVAS_REQUIRE_GUARDRAIL=true
```

The server screens incoming text before inference and the exact note body before persistence. An intervention, timeout, malformed response, missing required configuration, or provider failure holds new content. `DRAFT` is rejected. Saved notes carry the screening policy fingerprint; changing to a different published policy hides notes screened under an earlier policy until an explicit future re-screening workflow exists. The two labelled, reviewed sample notes remain demo fixtures.

The supplied policy blocks common sensitive identifiers and high-strength harmful content categories. Guardrails is additional content screening, not proof of who is watching. The renderer accepts only fixed local artwork and text components, so no model-generated images can enter an overlay; arbitrary visual-output screening is not implemented. Local regex screening is explicitly labelled and is not equivalent to AWS Guardrails.

Do not enable raw Bedrock model-invocation logging for real notes without a reviewed retention and access policy: original sensitive input can enter logs before masking. Application diagnostics omit event/note bodies and provider assessments. Structured AgentCore application logs and worker logs have KMS encryption and bounded retention in the template; inspect the account's other default runtime logs and telemetry before using household data.

## Event and API contracts

`AmbientEvent` is a versioned, closed envelope: `id` (UUID), `source`, `kind`, `sequence`, `observed_at` (Unix seconds), `data`, `home_id`, and `version`. This phase accepts only `local-home`, version `1`, and three labelled simulator sources:

| Kind / source | Allowed data |
| --- | --- |
| `presence` / `ring-simulator` | `people` from Mom/Leo/Alex IDs, and boolean `guest` |
| `media` / `firetv-simulator` | Known `scene`, `playback_id`, and `phase` (`program` or `break`) |
| `inventory` / `pantry-simulator` | `available` ingredient IDs from the demo catalog |

The server generates time, UUID, and sequence when browser controls select a fixture. A browser cannot supply a “verified Ring” provenance claim. Observations older than five minutes or more than five seconds in the future are refused. Deployments must replace these simulator sources with an explicitly authenticated adapter contract; do not relabel them as trusted camera identity.

`PutRawEvents` uses a JSON payload, the home as `EventGroupId`, and the event ID as `DeduplicationId`. The publisher checks each entry's success code rather than treating HTTP 200 as success. The FIFO subscriber uses `RAW` transformation. Lambda verifies the returned event and content hash, stops a FIFO batch at its first failure, and reports partial failures. The receiver commits before deleting SQS messages and recomputes current privacy instead of trusting routed UI hints. Expired observations are discarded. Failed or tampered messages stay for retries and eventual dead-letter handling. A content hash detects mismatch; IAM establishes transport authority.

The browser endpoints inherit the web server's loopback Host/Origin and custom-header protections:

| Route | Purpose |
| --- | --- |
| `GET /api/canvas` | Current audience-filtered state; no conversation history |
| `POST /api/canvas/simulate` | Select a demo fixture with `request_id`, `kind`, `value` |
| `POST /api/canvas/action` | Fixed UI action with `request_id`, `intent`, optional `product` |
| `POST /api/canvas/dismiss` | Dismiss a currently eligible `note_id` |
| `POST /api/chat`, `scenario_id: "canvas"` | Bedrock interpretation using the existing session and reply cache |

Alexa's normal dialogue interpreter also routes notes, recipes, scene shopping, and room previews to this shared service. Changing to a canvas topic clears an old unconfirmed gate/alarm question; it preserves previously submitted Presence handoffs. Speech synthesis uses server-selected replies from the same conversation cache.

## Deploy the optional AWS supervisor

[`infra/firetv/ambient-canvas.yaml`](../infra/firetv/ambient-canvas.yaml) supplies the encrypted V2 bus, ordered subscriber, input/output queues and failure queues, published Guardrails version, private AgentCore runtime and named endpoint, Lambda bridge, logs, and alarms. It does not create household identity, media rights, device credentials, payment integration, a VPC, or an artifact repository.

Before deploying, select a supported region, an account with enabled Bedrock tool/image inference, an ARM64 ECR repository, an existing private versioned S3 artifact bucket in that region, and private subnets/security groups with the required AWS connectivity. Use a stack name of at most 48 characters for the log-delivery names. Inspect private network egress, the AgentCore service-linked role, CloudTrail audit coverage, and the region's resource availability. These account-aware checks have not run in this phase.

Build artifacts from the project root:

```bash
docker build --platform linux/arm64 -f infra/firetv/Dockerfile -t homebound-canvas:review .
python scripts/build_canvas_worker.py
```

The Dockerfile-specific ignore file keeps local environment files, audit data, dependencies, and home state out of the build context. The container runs as a non-root user on port 8080, exposes `/ping` and `/invocations`, and emits no access log containing requests. Push the reviewed image to your ECR repository, scan it, and use its immutable `@sha256:` URI. Upload `.homebound/canvas-worker.zip` to the private artifact bucket and record its returned object version. The worker packages a pinned SDK instead of relying on Lambda's bundled version.

Prepare CloudFormation parameters for the artifact locations, model ID, **exact model/inference-profile ARNs** (including routed model regions), subnet IDs, security groups, and a unique runtime name. No account IDs or household credentials are hard-coded in the template. Runtime IAM grants inference and screening only; the bridge grants access only to its queues and deployed runtime endpoint. KMS grants include the new custom bus's branch-key actions. The deployment role needs the corresponding key-management checks during creation; publishers need `events:PutRawEvents` and `kms:Decrypt` for this bus/key.

Create and review a CloudFormation change set with `CAPABILITY_IAM`. Run service pre-deployment validation and inspect findings before execution. `EnableConsumer` defaults to `false`. Check that the runtime and `canvas` endpoint are ready, invoke its typed event and plan operations with IAM, verify model/Guardrails permissions and application-log delivery, then update that parameter to `true`. `/ping` verifies process health; it is not an inference or credentials check. Wire the three alarms to an approved operator destination; the template does not send notifications automatically.

For this web process to use the deployed runtime/receiver, configure:

```dotenv
HOMEBOUND_CANVAS_RUNTIME_ARN=<runtime-arn>
HOMEBOUND_CANVAS_EVENT_QUEUE_URL=<output-queue-url>
HOMEBOUND_CANVAS_GUARDRAIL_ID=<guardrail-id>
HOMEBOUND_CANVAS_GUARDRAIL_VERSION=<published-version>
HOMEBOUND_CANVAS_REQUIRE_GUARDRAIL=true
```

Use the normal AWS SDK credential chain. The receiver needs `sqs:ReceiveMessage`, `sqs:DeleteMessage`, and `kms:Decrypt` for its output queue/key; the planner needs `bedrock-agentcore:InvokeAgentRuntime` for the runtime and returned `canvas` endpoint ARN; the local screen needs `bedrock:ApplyGuardrail`. No credentials enter the browser. `boto3` calls the new service `eventbridgev2`; the current AWS CLI calls it `eventsv2`, and IAM uses `events:`.

Publish a labelled demo event only after the cloud route is ready:

```bash
python -m app.cli.ambient_event --bus-arn "$CANVAS_BUS_ARN" --person leo --sequence 100 --region us-east-1
```

Sequence numbers must continue from the source's persisted watermark; this example's `100` is illustrative. Use fresh observations and new IDs. SDK transport retries preserve the exact event. Do not replay old presence to clear a guest or replay a commercial break after the program changed. The bus and queues retain data for diagnosis; their retention does not extend observation validity.

A subscriber replacement should be deployed alongside the old subscriber, verified, and then cut over. The new custom-bus subscriber resource can delete its old instance before creating a replacement, so a blind replacement risks a delivery gap. The retained event bus and queues support controlled diagnosis/replay. Retained queues, logs, bus, and KMS key continue to exist after stack deletion and can continue to incur charges.

## Validation

Local tests cover guest and stale-audience redaction, explicit recipients, note expiry/restart, delayed and duplicate events, old playback signals, pantry freshness, draft-only purchases, room restoration, scene changes during inference, Guardrails failures/policy changes, API boundaries, and Alexa topic changes. AWS tests use botocore's current service models and explicit fixtures; they do not represent a deployed AWS run.

```bash
python -m pytest -q
node --test tests/voice-activity.test.cjs tests/voice-listener.test.cjs tests/program-player.test.cjs
```

Use cfn-lint `1.57.2` and cfn-guard `3.2.1` (installed separately with approval). This checkout keeps them in the ignored `.homebound` directory. The rule-fetch script downloads only pinned AWS rule data with checked hashes; it does not install or run tools.

```bash
python scripts/fetch_canvas_guard_rules.py
.homebound/cfn-tools/bin/cfn-lint --format json --template infra/firetv/ambient-canvas.yaml --regions us-east-1 eu-west-1
.homebound/cfn-guard/bin/cfn-guard validate --rules .homebound/aws-guard-rules --rules infra/firetv/canvas.guard --data infra/firetv/ambient-canvas.yaml --output-format json --show-summary none
```

Local schema validation passes in both listed regions. Guard reports zero violations: seven applicable AWS rules and nine HomeBound rules pass; the Lambda public-permission rule is inapplicable because no such resource is created. Deliberately changing the runtime to public networking, permitting wildcard role actions, removing log encryption, or using `DRAFT` causes the custom checks to fail. These checks do not prove IAM effectiveness, live connectivity, model entitlement, or cloud deployment readiness. Service pre-deployment checks and a deployed end-to-end run remain separate work.

The full Python suite passes 182 tests, and the existing voice/AgentSafe JavaScript suites pass 22. The Lambda zip was built and imported without access to the developer environment's site packages. Live local Bedrock requests exercised note creation, illustrated cooking/jacket interpretation, a contextual cart follow-up, and reading mode. A request through Alexa's normal dialogue route saved a note visible on the TV and returned Deepgram speech successfully. Browser checks covered guest redaction, media attention, pantry updates, restoration, remote focus, long-note containment, and 390/1440/1920-pixel layouts. The Docker daemon did not respond to its version probe, so the ARM64 container image build remains unverified; no container or cloud deployment was attempted.

## Platform and API references

- [Fire TV web apps](https://developer.amazon.com/docs/fire-tv/getting-started-with-web-apps.html) and [Fire OS picture-in-picture boundaries](https://developer.amazon.com/docs/fire-tv/fire-os-6.html): a deployable app needs supported platform APIs. This prototype does not overlay arbitrary third-party apps or capture their protected frames.
- [EventBridge custom buses](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus.html), [SDK/CLI naming](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus-names.html), [publishing](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus-publish.html), [subscribers](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus-subscribers.html), and [KMS permissions](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-custom-bus-encryption.html).
- [AgentCore invocation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html), [private VPC configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html), [runtime endpoints](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-runtimeendpoint.html), and [observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html).
- [AWS Guard rules registry](https://github.com/aws-cloudformation/aws-guard-rules-registry), pinned by commit and content hashes in the infrastructure directory.
