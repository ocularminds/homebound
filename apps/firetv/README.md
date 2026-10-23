# HomeBound on Fire TV / Vega

This application uses Amazon's React Native for Vega and WebView to render the
HomeBound canvas on **Vega Virtual Device**. The installable `.vpkg` uses the native Vega WebView runtime. The household service runs on
the development Mac and is reverse-forwarded over the local device bridge.

## Prerequisites

- An Apple Silicon Mac supported by [Vega SDK 0.24](https://developer.amazon.com/docs/vega/0.24/install-vega-sdk).
- Vega SDK 0.24.12112 and its Virtual Device image.
- Node 22.23.2, npm, and the Python backend described in [deployment.md](../../docs/deployment.md).
- An active backend on `http://127.0.0.1:8300`. Cloud credentials remain on the host.

## Build and run

From the repository root, start the backend in a terminal and leave it running:

```bash
./scripts/run-demo.sh --with-services
```

For a visual preview without external service credentials, use
`.venv/bin/python -m app.cli.web` instead. Natural-language interpretation
requires Bedrock; the app does not substitute canned model responses.

In another terminal:

```bash
source "$HOME/vega/env"
cd apps/firetv
npm ci
npm run build:release
vega virtual-device start --gui --display-res 1920,1080
vega exec vda reverse tcp:8300 tcp:8300
vega run-app build/private/kepler/homebound-tv/undefined/vega/aarch64/Release/homebound-tv_aarch64.vpkg
```

The package id is `com.ocularminds.homebound`; the main component is
`com.ocularminds.homebound.main`. The release build also produces armv7 and
x86_64 packages. The aarch64 artifact is used on the Apple Silicon simulator.

If an automation runner terminates descendant processes when its command exits,
keep that runner's terminal session alive after `virtual-device start`. A normal
interactive terminal can remain open. Verify `vega virtual-device status` reports
`running: true` and `vega exec vda devices` lists a device before installing.

## Controls and network boundary

Use directional keys and Select/Enter to navigate, Back/Escape to close an open
panel or dialog, and Play/Pause during the cartoon. **Demo signals** changes
the illustrated scene, viewer, and pantry. The companion web page can provide
text or voice input to the same backend. This VVD returned `NotSupportedError`
for microphone capture; typed requests work. Use the desktop companion in a
browser with MediaRecorder and microphone support for speech. The submission
film uses typed requests and the owner's recorded voice over.

Only `127.0.0.1` and `localhost` cleartext traffic is allowed by the manifest,
for the local reverse tunnel. No broad cleartext exception, embedded credential,
public backend, certificate bypass, or direct physical device control is added.
Mixed content remains disabled. This development transport is not an Appstore
production deployment; a distributed app needs an authenticated HTTPS backend.

## Media compatibility

The included cartoon and commercial assets use H.264 Constrained Baseline, one
reference frame, no B frames, and AAC stereo. The original multi-reference encode
stalled in this VVD; the compatibility export plays through both real commercial
cues and resumes the same program playhead. See the [media manifest](../../media/park-chase/production.json).

## Validation

```bash
npm run lint
npx tsc --noEmit
npm run build:release
```

See [submission status](../../docs/submission/status.md) for the actual simulator
and live-service checks, and the [recording shot list](../../docs/submission/video-shot-list.md).
