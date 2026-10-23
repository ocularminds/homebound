# Submission status - 23 October 2026

## Verified in this session

- Local `master` fast-forwarded to `05005f1`, including merged Fire TV and
  Runway media PRs #17 and #18. Work continues on
  `codex/hackathon-deployment-packaging`.
- 204 Python tests pass, including source-bundle privacy and reproducibility
  checks. The pinned runtime was installed in a fresh environment.
- 12 AgentSafe JavaScript tests and 20 browser JavaScript tests pass on Node 22.23.2.
- The existing AWS template passes cfn-lint in us-east-1/eu-west-1 and all
  applicable pinned AWS/custom cfn-guard checks.
- The ARM64 supervisor image and the complete local demo container build.
- Both local and container web servers answer health checks, serve real media
  with HTTP 206 byte ranges, and reject an untrusted Host with HTTP 403.
- MIT license added with the owner's authorization; dependency pins and a
  source-bundle builder are included.
- Vega lint, TypeScript checks, the generated render smoke test, and release
  builds pass. SDK 0.24.12112 produces aarch64, armv7, and x86_64 packages.
- The installed aarch64 release runs on Amazon Vega Virtual Device. Native
  Play/Pause and Back controls were checked through VDA.
- Real cartoon playback runs through both commercial cues; one-reference
  H.264 Constrained Baseline exports resolved a simulator playback stall.
- Live Bedrock requests demonstrated notes, pantry-aware recipes, a draft cart,
  and a reading preview that restores the same media and room state. A guest
  audience produced zero delivered and rendered private notes.
- The finished film is 171.2 seconds, 1920x1080 at 30 fps, H.264/AAC, with
  the owner's voice-over and corrected captions. Native simulator footage
  starts with the cartoon playing before any note or Alexa interaction.

## External integration limits

The live demo uses a local home backend with real Amazon Bedrock calls.
Household audience, pantry, catalog, and room controls are labelled demo data.
Shopping creates a draft; checkout is unavailable. Other media scenes are
illustrated previews. Microphone capture is unsupported in this VVD, so the
film uses typed requests and the owner's recorded narration.

Alexa+ partner access and physical Ring devices remain unconnected. The latest
documented managed Presence attempt failed before handoff because the Decionis
tenant connection was not configured. The child path remains closed.

AgentCore/EventBridge/SQS/Guardrails cloud infrastructure is supplied and
locally checked. No cloud stack or end-to-end cloud deployment is claimed.

## Submission gates

- [x] Run and capture the installed app on Vega Virtual Device.
- [x] Complete narration, simulator footage, captions, and the under-three-minute edit.
- [x] Publish and verify [the public video](https://youtu.be/z0_36x-JmDA).
- [x] Save the final video URL, source URL, and cartoon-first image gallery.
- [x] Publish the latest code and verify public repository access. [PR #19](https://github.com/ocularminds/homebound/pull/19) passes GitHub CI.
- [x] Save Fire TV as the primary track, with AWS Builder and Open Source; Alexa is complementary.
- [ ] Attach the final judge bundle and complete Devpost's final submission.
