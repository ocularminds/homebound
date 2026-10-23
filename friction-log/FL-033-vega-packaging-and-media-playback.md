# FL-033 - Vega packaging, debugger access, and video compatibility

**Area:** Fire TV / Vega SDK 0.24.12112, WebView 4.0.2, Apple Silicon VVD

**Observed (23 October 2026):** The generated app built and installed successfully,
but the default manifest blocked the local HTTP development bridge. WebView 4.0.2
requires a cleartext allowlist. The simulator process also exited when the
noninteractive command runner cleaned up descendants after the launcher returned.

**Resolved:** Allow only `127.0.0.1` and `localhost`, reverse-forward port 8300 with
VDA, and keep the launching terminal session alive. The application opens directly
into the real cartoon before note or Alexa interactions. No credentials are
embedded in the package. Add the documented media session/audio services and
caption accessibility privilege to the manifest.

**Playback:** The original H.264 High export stalled near three seconds in this
VVD despite a buffered stream and no media error. A 720p24 Constrained Baseline
encode using one reference frame and no B frames played through the 20-second
and 42-second ad cues, including separate commercial playback and program
resume. AAC stereo and the original edit, soundtrack, captions, and durations
are retained. This is a tested compatibility workaround; the underlying SDK
codec defect has not been established.

**Debugging:** The documented WebView inspector port 9229 accepted forwarding but
returned an empty response. The React Native debugger remained available through
Metro. A temporary development-only WebView bridge let us inspect actual media
state; it is removed from the release source. Native window recording captured
the running VVD, with VDA/emulator control authorized by the owner.

**Product feedback:** Provide a tested web-media manifest and codec sample,
clear errors for blocked HTTP and decoder stalls, and reliable WebView inspector
access on the distributed VVD image. An explicit CLI foreground/keep-alive mode
would improve automation. The build output and native WebView made it practical
to reuse the existing TV canvas, and we would build on Vega again with these
packaging and playback constraints covered by device checks.

References:
- [Build Web Apps with WebView](https://developer.amazon.com/docs/vega/0.24/develop-your-app-with-webview)
- [Amazon media-service manifest guidance](https://community.amazondeveloper.com/t/audio-and-video-not-working-in-webview/24676)
- [WebView inspector report](https://community.amazondeveloper.com/t/webview-chrome-devtools-inspector-is-broken/29016)
