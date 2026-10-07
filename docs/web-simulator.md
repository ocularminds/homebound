# Alexa-style web simulator

Amazon advised using a simulated frontend while Alexa+ MCP partner access is unavailable. HomeBound now supplies a full-screen Alexa-style experience: a home-local clock, time-based greeting, animated voice ring, continuous conversation, and spoken replies. There is no sidebar or scene picker. Conversation history, device execution snapshots, and action evidence open from compact controls. The screen identifies itself as a HomeBound simulation.

```text
Browser microphone -> Deepgram speech-to-text -> captured user request
                                                  |
Typed request ------------------------------------+
                                                  v
                                      Amazon Bedrock Converse
                                                  |
                                    HomeBound MCP -> AgentSafe
                                                  |
                                     Decionis / managed Presence
                                                  |
                                  authorized local Ring simulation
                                                  |
Browser action record <- structured MCP result ----+
Browser audio        <- Deepgram text-to-speech <- evidenced reply
```

The web server does not import a Ring adapter or receive its execution credential. Spoken or typed messages first go to Bedrock's dialogue interpreter, which can only extract conversation facts. The server gathers missing context and binds a ready request before a separate Bedrock tool-use turn calls MCP. Deepgram supplies speech; Decionis remains the authority.

## Start

Install the existing Python development dependencies and, for the full local stack, the pinned AgentSafe Node dependencies. The web frontend has no JavaScript build step.

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
fnm use 22.23.2
(cd agentsafe && npm ci)
set -a
source .env
set +a
python -m app.cli.web --with-services
```

Open [localhost:8300](http://127.0.0.1:8300). `homebound-web` is the equivalent installed command. `--with-services` starts the existing executor, dossier archiver, Ring simulator, and MCP service, and shuts those child processes down when the web command stops. Use it only when those services are not already running. Their existing settings in the root `.env` and `agentsafe/.env` must be configured as described in the main README. The simulator runner expects the project Python environment to be active.

If the governed services are already running, omit `--with-services`. The same command without any service configuration opens the interface for inspection and reports missing configuration when a request is submitted. It does not invent an authority result.

The AWS CLI session must be valid for the configured Bedrock model. The web process creates its Bedrock client lazily, so an expired AWS session does not prevent the page from opening. All AWS and voice errors are shown as service failures; none is converted to an authorization decision.

## Voice configuration

Set `DEEPGRAM_API_KEY` in the server environment using your secret injection mechanism, or keep it in the existing ignored `agentsafe/.env`. The web server reads only that named value from the file; it does not source the executor's environment or import its other credentials. A nonempty environment value takes precedence. `HOMEBOUND_VOICE_ENV_FILE` selects a different file; an empty path disables the file fallback. Restart the web command after changing the key.

When using AWS Secrets Manager, supply a dynamic reference to the existing secret in the environment and launch with `asm-exec`, following the repository's secret-handling rules. Substitute your actual secret identifier and JSON field name; the example below does not provision a secret.

```bash
export DEEPGRAM_API_KEY='{{resolve:secretsmanager:YOUR_SECRET_ID:SecretString:api_key}}'
asm-exec -- python -m app.cli.web --with-services
```

`asm-exec` must already be installed and configured for your Secrets Manager environment. An unresolved reference leaves voice disabled. No key is sent to the browser or exposed by the bootstrap API. The default speech models are `nova-3` and `aura-2-thalia-en`; `DEEPGRAM_STT_MODEL` and `DEEPGRAM_TTS_MODEL` override them. See the official [speech-to-text REST reference](https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded) and [text-to-speech REST reference](https://developers.deepgram.com/reference/text-to-speech/speak-request).

On load, the screen prepares the microphone and greets you with **Good morning**, **Good afternoon**, **Good evening**, or **Good night**, followed by **What else can I help with?** The greeting uses the configured home's timezone: morning 05:00–11:59, afternoon 12:00–17:59, evening 18:00–21:59, and night 22:00–04:59. Its text is selected by the server and spoken with Deepgram.

Browser microphone permission and autoplay rules still apply. Allow the microphone when prompted. If the browser requires an initial audio gesture, choose **Start talking** once. The application attempts startup automatically; it does not bypass browser permissions. If voice is unavailable, **Type** remains usable.

Speak, then pause for about 1.5 seconds to submit. The microphone connection stays open between turns. Listening resumes when the spoken reply finishes; capture is suspended while Alexa speaks so the reply does not become another request. Local audio-level analysis ignores short noises and brief hesitations. Each recording is limited to 45 seconds, and quiet buffers are discarded locally and renewed without a transcription request. **Mic on** mutes, discards an unfinished recording, and releases the microphone; **Start talking** reconnects. Opening a detail panel or the text composer pauses capture. Closing the page releases the microphone.

Speech-containing audio is sent to the server as a browser-native WebM, MP4, or Ogg recording, then to Deepgram. The transcript takes the same path as typed text and moves immediately into the conversation. Playback can be stopped, disabled in the Conversation panel, or replayed with **Read reply**. After a completed request, Alexa asks **What else can I help with?** Clarifying questions are spoken on their own. This implementation records utterances before transcription; it does not implement wake-word recognition or interruption while Alexa speaks.

The web server does not persist raw audio. Conversations and speech reply references are in bounded server memory for one hour of inactivity. Requests and execution evidence still use HomeBound's existing private governance audit. Upstream services receive the audio, transcript, or request needed for their part of the flow.

## Conversation and results

Examples:

- “Open the side gate.” Alexa asks whether this is for a delivery or someone at home. “It's an expected delivery” carries that request forward; Alexa then asks whether the simulated camera recognizes the courier. “Yes” completes the captured context and submits the original request once.
- “There's a delivery.” Alexa offers to open the gate. Mentioning a delivery alone does not request an unlock or imply that the courier is expected or recognized.
- “Disable the alarm.” Alexa asks whether this is for an adult or a child home alone. A stated adult or parent is a conversation claim, never an authenticated parent role.
- “Cancel that.” A pending conversational request is cleared. It cannot be resumed by a later bare “yes.” Completed or already dispatched requests are not undone.

The interpreter has no device tools and cannot call MCP. Its output is validated before it changes session context. The server binds the chosen tool, target, context, and parameters; the execution model cannot change them. Each new gate request gathers fresh visitor facts, and a completed action is consumed before dispatch so an uncertain response cannot make the next utterance replay it. Conversation state is isolated by browser session and cleared by **Start a new conversation**. Every gate request uses the policy's 30-second duration.

The clock comes from `HOMEBOUND_HOME_TIMEZONE`, defaulting to `Europe/Stockholm`. Merely mentioning delivery does not select the old 16:00 fixture. For a timed demo, explicitly say “For this demo, simulate 4 pm”; the resulting context records that time as a demo override. “Use the real clock” removes it. The greeting always uses actual home-local time. Camera recognition confirmed during the conversation populates a labelled simulation fixture, with `recognition_simulated=true` and `signal_source=web_conversation_simulation`; it is not a real observation or independent identity proof. **Home details** exposes these claims and the exact captured request.

The original fixed scenarios remain available to explicit API callers and existing tests, but are not used by the conversational screen.

The UI reports the returned decision and execution state. It does not assume the child will escalate, the courier will be allowed, or the late courier will be blocked. If model narration contradicts a structured result, the displayed and spoken action reply uses the structured result. A lost MCP response is reported as uncertain because the action may already have reached the executor. The web client never automatically retries an action; duplicate request IDs within the session return the retained result, and reuse with changed content is refused.

The execution assistant describes the captured context and device parameters with explicit object schemas. This lets Nova return ordinary JSON objects, while server validation still checks the exact values and device limits before calling MCP. Model planning sections are removed before replies reach the browser, conversation history, or speech service. Quoted or HTML-encoded scalar labels from the dialogue interpreter are normalized before strict validation; unknown facts remain unknown.

An `ESCALATE` result creates a visible approval card with the request, returned status, and expiry. Approval is completed in Decionis Presence. Quiet automatic checks, the **Check approval** button, and “check approval” by voice all resume only the same conversation's saved handoff through MCP. Pending checks keep microphone capture running and do not fill the conversation; a terminal result is announced once. “Mum approved it” can only trigger a status check. An outage retains the handoff and stops automatic checks; a lost execution result requires review. See the [approval lifecycle and live setup requirement](escalation.md).

The live tenant currently returns `PRESENCE_TENANT_CONNECTION_NOT_CONFIGURED` before creating a handoff. No approval card is invented for that failure. Configure the Decionis tenant's managed Presence connection before validating a real parent ceremony.

Device cards start with an unknown state. After a performed action, they display the state in the latest MCP execution event. They are execution snapshots, not live telemetry. Clearing the conversation does not reset devices. For example, a blocked late-courier request does not relock a gate that an earlier allowed request unlocked. The existing CLI demo remains the workflow that resets the simulator between isolated scenarios.

Clearing conversation removes model history and visible conversation while retaining action records, duplicate-request records, and pending handoffs. Export record downloads the session's displayed request and evidence metadata as JSON; it is not a substitute for the signed dossier retained by the trusted executor. After a server restart or session expiry, durable pending handoffs can still be checked with the existing escalation CLI.

## Local boundary and verification

The interface binds only to loopback and refuses production mode. It checks the Host and Origin, rejects cross-site browser requests, and requires a custom header on mutations. Session cookies are HttpOnly and SameSite Strict. There is no cross-origin API, direct simulator route, browser-provided policy context, or browser-supplied TTS text. Text, JSON, recording size, conversation count, and retained history are bounded. This is a local demo, not a remotely authenticated household UI.

Run the existing suite plus the web boundary and speech-adapter tests:

```bash
python -m pytest -q
node --check app/web/static/app.js
node --check app/web/static/voice-listener.js
node --test tests/voice-activity.test.cjs tests/voice-listener.test.cjs
(cd agentsafe && fnm exec --using=22.23.2 npm run check)
```

Tests use fixtures for Bedrock, MCP results, and Deepgram. They exercise context gathering, cancellation, greeting boundaries, explicit demo times, context mutation, replay, session isolation, lost execution responses, Presence resume, secret-safe output, and result-driven speech. Voice tests cover pauses, brief hesitations, noise, silent buffer renewal, reuse of one microphone connection, stopping late permission results, and suspension during playback. Live validation needs an active AWS session, configured governance services, and a working Deepgram key.
