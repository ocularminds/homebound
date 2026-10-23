# HomeBound hackathon submission

**Primary track: Fire TV.** Alexa+ supplies the complementary simulated voice
experience. **Mini challenge: AWS Builder.**

HomeBound is a shared TV canvas that adapts notes, recipes, shopping suggestions,
and room previews to the audience and viewing moment.

## Submission materials

- [Project description](project-description.md): copy-ready project story.
- [Product feedback](product-feedback.md): tooling feedback and linked friction logs.
- [Narration](narration.md) and [capture plan](video-shot-list.md): Fire TV demo.
- [Project status](status.md): verified work and remaining submission gates.
- [Deployment guide](../deployment.md): local runtime, containers, and AWS supervisor.
- [Fire TV / Vega app](../../apps/firetv/README.md): build and run on the simulator.
- [Full friction log](../../friction-log/): technical details for the feedback bonus.

The official deadline is **23 October 2026, 21:00 Europe/Stockholm**
(12:00 PDT). The [official requirements](https://amazonappdev2026.devpost.com/)
and [rules](https://amazonappdev2026.devpost.com/rules) were reviewed on 23 October.

The final entry needs the public GitHub repository with its MIT license, the
project description, tool feedback, track selection, and a public English
YouTube/Vimeo demo under three minutes. Fire TV footage must show an actual
Fire TV device or Vega Virtual Device. A desktop browser preview alone is
insufficient. Keep the project available through judging.

**[Watch the public demo (2:51)](https://youtu.be/lGNDMxiiN_4).** The installed
Vega app was captured directly, with the owner's narration and readable captions.
The cartoon is playing before the first note or companion interaction.

## Run the public preview

Python 3.12 or 3.13 and Node.js 22.14+ are the tested setup. The release pins
Node 22.23.2. From the source checkout or extracted submission ZIP:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
npm ci --prefix agentsafe
python -m app.cli.web
```

Open [the TV canvas](http://127.0.0.1:8300/tv?play=park_chase).
Choose **Demo signals → Leo**, then play the cartoon. His reminder appears
during commercials at 20 and 42 seconds. Add a guest to see redaction.

This preview needs no keys for video and demo controls. Natural-language
interpretation, voice, and authority calls require the configured live services;
the preview does not fabricate those results.

The container alternative is `docker compose up --build`. It publishes only
`127.0.0.1:8300` and includes the media and Node executor. Its default preview
has no external credentials. Stop with `docker compose down`; named volumes
retain preview notes.

## Run the configured experience

Follow [web setup](../web-simulator.md) for local configuration and use:

```sh
fnm exec --using=22.23.2 ./scripts/run-demo.sh --with-services
```

Use the existing AWS profile and enabled Bedrock model. Deepgram is optional for
typed interaction. The Ring execution simulator requires Decionis, AgentSafe,
and private home-policy configuration. No secrets or private audit data are
provided in the public bundle. AWS Secrets Manager references must be resolved
with `asm-exec`; never print or embed credentials in the submission.

For the Fire TV demo, use the [Vega instructions](../../apps/firetv/README.md)
to forward port 8300 to the simulator and run the installed app. The Alexa
companion at `/` shares this backend's home state with the TV at `/tv`.

## Validate and package

From a Git checkout:

```sh
make check
make package
```

The source ZIP, file manifest, and SHA-256 checksum are written to `dist/`.
The manifest records the source commit, whether the checkout contained changes,
and the hash of every packaged file. Local configuration, caches, household
databases, audit records, dependencies, and symlinks are excluded or rejected.
The ZIP contains the complete source; a Python wheel alone does not include the
repository-level Node service launcher and is not the full demo distribution.

The local delivery directory also includes `dist/firetv/` release packages for
aarch64, armv7, and x86_64, and `dist/submission-video/` with the final MP4,
captions, transcript, contact sheet, edit list, and provenance manifest. Generated
artifacts are excluded from Git; the native package can be rebuilt with the
[Vega build instructions](../../apps/firetv/README.md).
