# HomeBound deployment and packaging

## Local home runtime

The backend is a localhost service shared by the TV canvas and Alexa companion.
Use Python 3.12/3.13 and Node 22.23.2, the locked dependencies, and the source
checkout. See [judge setup](submission/README.md).

`scripts/run-demo.sh --with-services` loads the ignored root configuration and
starts the web service plus AgentSafe, dossier archive, Ring simulator, and MCP.
The launcher never prints configuration values. Use the existing local service
configuration and the repository's Secrets Manager / `asm-exec` rules.
The frontend never receives the execution credentials.

For Fire TV simulator access, reverse-forward the backend's port rather than
opening the authority services on the network. The [Vega package](../apps/firetv/README.md)
loads the same localhost origin inside the simulator. The development backend
keeps its Host/Origin checks, session isolation and action binding.

## Docker preview

```sh
docker compose up --build
```

The Dockerfile includes Python, the pinned Node runtime, the official Node
executor dependencies, the source and public media. Docker's internal listener
uses `--container`; the HTTP boundary still accepts only localhost Host/Origin.
Compose publishes only `127.0.0.1:8300`, runs as an unprivileged user, drops
capabilities, uses a read-only root filesystem, and persists notes/audit state
in named volumes. The preview does not contain credentials and does not fake
Bedrock, voice, or Decionis responses.

The configured full-stack recording uses the host launcher so existing AWS
login, server-side voice configuration and authority configuration remain in
their normal local locations. Do not expose the localhost simulator publicly
without an authenticated deployment boundary.

## AWS supervisor artifacts

```sh
make canvas-image
make canvas-worker
make validate-infra
```

The container is ARM64 and uses `requirements.lock`. The worker ZIP packages
its pinned pure-Python AWS dependencies. Only public app source enters either
artifact; local configuration and household state are outside their build
contexts. The supervisor listens on 8080 with `/ping` and `/invocations`.

The [application template](../infra/firetv/ambient-canvas.yaml) preserves
private AgentCore networking, IAM invocation, exact model ARN parameters,
encrypted transport/storage, a published Guardrails version, and a disabled
consumer until the route has been validated. It passes the selected AWS region
to the runtime explicitly and exports the named endpoint ARN for client IAM.

The [foundation template](../infra/firetv/foundation.yaml) supplies the dedicated
private network, service endpoints, artifact storage, ECR repository, and audit
logging. Deploy with enabled Bedrock inference, an immutable ECR image digest,
and a versioned S3 worker object. The [staged rollout](cloud-deployment.md)
documents runtime readiness, endpoint creation, platform log configuration,
and consumer enablement.

The `us-east-1` deployment passed live checks on 23 October 2026 after the
hackathon submission: model-backed recipe planning, published Guardrails,
all three event types, duplicate handling, guest privacy, and program/break/
resume reached a disposable home receiver through the actual AWS pipeline.
The three alarms remain in CloudWatch without notification destinations.
See the rollout guide for costs and unresolved base-image scan findings.

For this checkout, `scripts/run-demo.sh --cloud --with-services` loads the
generated non-secret `.homebound/cloud-deployment/runtime.env` after the normal
local configuration. Select the pinned Node version first.

Local template checks, a container build, and a deployed end-to-end run are
separate results. `/ping` only proves the process is alive. Record an actual
planning invocation, Guardrails behavior, and an ordered event reaching the
home receiver before describing the cloud route as deployed and working.

Retained queues, logs, bus data and KMS keys survive stack deletion and may
continue to incur charges. Do not delete retained data or shared networking as
part of routine demo shutdown.

## Submission bundle

`make package` writes `dist/homebound-submission.zip`, its SHA-256 file, and
a manifest. The bundle includes source, public media, Node lockfile, configuration
examples, infrastructure, tests, docs, narration and friction logs. It excludes
local data and dependencies. File bytes, permissions, and commit/dirty status
are recorded; repeated builds of the same snapshot have the same ZIP checksum.

The source bundle is the complete distribution for judging. A Python wheel
includes the Python application and static media, but the full service launcher
also needs the repository-level `agentsafe/` directory.
