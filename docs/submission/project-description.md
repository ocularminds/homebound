# HomeBound

## Tagline

A Fire TV canvas that brings the right home context to the right audience at
the right moment, with Alexa-style voice alongside it.

## Inspiration

A television is shared by a household and sometimes its guests. A useful personal
note can become an interruption during a film or a privacy problem when another
person is watching. We wanted the living-room screen to help without behaving
like an oversized phone notification feed.

## What it does

HomeBound brings several everyday tasks into a Fire TV viewing experience:

- **Personal notes at useful moments.** A child's homework reminder waits while
  the program plays, then appears beside a commercial. Pause to read and return
  to the saved playhead.
- **Audience-aware privacy.** Recipient-only notes are removed from the server's
  response when a guest, mixed audience, unknown audience, or stale presence
  signal makes disclosure inappropriate.
- **Cooking context and pantry help.** Ask what is cooking in the illustrated
  scene, see a matching recipe, and check the ingredients against the demo pantry.
  Restocking updates an already-open recipe.
- **Scene shopping without accidental purchase.** Ask about a jacket in the
  movie scene, then continue with “add that to my cart.” The catalog and prices
  are illustrative; the result is a draft, with no checkout.
- **A coordinated reading preview.** Keep the game in the background while
  previewing captions, muted audio, and a reading-friendly room setup. Restore
  the previous preview with a follow-up request.
- **Complementary voice.** An Alexa-style companion can dictate a note for Mom
  into the same home state. The TV reveals it when Mom is the eligible viewer.

## How we built it

The TV canvas runs as an installable Amazon Vega application using React Native
for Vega and WebView. Its HTML, CSS, and JavaScript interface plays an original
H.264 cartoon with separate commercial clips. The demo is screen-recorded from
Amazon Vega Virtual Device on Apple Silicon, with the cartoon playing before
any Alexa or notes interaction. A Python Starlette service owns the shared home
state and filters every projection before it reaches the TV. SQLite retains
notes, expiry, playback state, and event watermarks.

Amazon Bedrock Converse interprets requests and the simulator's own scene
images. A closed proposal schema feeds bounded Context, Media, and Shopping
components. Deterministic code owns audience eligibility, freshness, ordering,
cart totals, and permitted state transitions. The model supplies data for fixed
components, never arbitrary executable UI.

The complementary Alexa simulation uses Deepgram speech and the same Bedrock
and home-state services. A separate real Streamable HTTP MCP path captures
consequential home proposals for the official Decionis AgentSafe executor.
Decionis remains the authority and signed dossier evidence is verified before
simulated execution. This boundary supports future device adapters; gate
opening is not the focus of the Fire TV demonstration.

The repository also supplies an ARM64 AgentCore supervisor container and
CloudFormation for EventBridge V2, FIFO SQS transport, a Lambda bridge,
published Bedrock Guardrails, encrypted logs, and alarms. Consult the status
page for the difference between packaged infrastructure and a verified live
cloud deployment.

## What makes it different

HomeBound combines viewing attention, recipient privacy, and conversational
context in a single TV canvas. The same commercial that creates room for a note
does not grant permission to disclose it. The same model that suggests a product
does not gain authority to buy it. Useful assistance and explicit boundaries
are parts of the same product experience.

## Current boundaries

The household, pantry, catalog, scene and presence signals are labelled demo
data. There is no authenticated camera recognition, physical Ring control,
third-party streaming overlay, Amazon Pay checkout, or Alexa+ partner connection.
Room controls are previews. Decionis-managed parent approval is implemented but
the configured tenant's Presence connection remains unresolved.

## Challenges and what we learned

A shared TV needs server-side privacy checks, not just hidden cards. We learned
to treat audience freshness, playback state, and shopping authorization as
separate deterministic decisions around Bedrock interpretation.

Vega packaging exposed practical issues: loopback HTTP needs an explicit
allowlist, automation must keep the simulator process alive, and a simpler
H.264 encoding was needed for uninterrupted playback in the virtual device.
Our public friction log records the failures, working fixes, and product feedback.

## Built during the hackathon

The repository's October 2026 work added Bedrock/MCP orchestration, the governed
executor and evidence archive, the Alexa-style companion, approval lifecycle,
Fire TV ambient canvas, original cartoon and commercials, AWS supervisor
infrastructure, and submission packaging. The linked phase pull requests and
Git history identify the work; no pre-hackathon product maturity is claimed.

## Next steps

Connect authenticated household signals, validate on physical Fire TV hardware,
add an owner-managed household setup, and connect real device adapters only
through the existing execution authority. Extend the catalog and content
integrations after the rights and purchasing boundaries are in place.
