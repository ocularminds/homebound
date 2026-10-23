# Submission status - 23 October 2026

HomeBound was submitted to the **Build, Ship, Shape: Amazon Developer Hackathon**
on 23 October 2026 as **Decionis Inc (United States)**. Devpost confirmed
"Project submitted!" before the 19:00 UTC deadline.

This page records the submitted snapshot. The subsequent
[AWS cloud deployment](../cloud-deployment.md) is documented separately; the
uploaded video and judge bundle are unchanged.

- [Public submission](https://devpost.com/software/alexa-can-open-the-door-should-it)
- Primary track: **Fire TV**; mini challenges: **AWS Builder** and **Open Source**.
- [Final video](https://youtu.be/z0_36x-JmDA): 2:51, with captions.
- Five gallery images are saved, with cartoon playback as picture 0 and the cover.
- Uploaded judge bundle: `homebound-firetv-judge-bundle.zip`, 33,652,024 bytes.
  SHA-256: `381b88e424a0819657316d11e537f41a8cfe58dbbe33d156b60c344082437069`.
  It pins source commit `a74c80c8cada81d90dd7de1ac912185cccea1431` and includes
  the three native Vega packages.

## Verified in this session

- [PR #19](https://github.com/ocularminds/homebound/pull/19) merged into `master`
  as `ef8943bbd367e15bbe9aa15a6868dbf314dd6a87`; local `master` is synced.
  GitHub detects the MIT license on the public default branch. The submission
  branch is retained so the submitted source and setup links remain valid.
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
- [x] Publish and merge the latest code, verify public repository access and MIT detection, and pass both GitHub CI checks.
- [x] Save Fire TV as the primary track, with AWS Builder and Open Source; Alexa is complementary.
- [x] Attach the final judge bundle and complete Devpost's final submission.
