# AWS canvas rollout

HomeBound has a dedicated private AWS foundation and a staged application
deployment. The Fire TV app and private home store stay on the local home
runtime. AgentCore interprets public scene context; EventBridge V2, FIFO queues
and Lambda transport the three labelled simulator event types.

## Foundation and artifacts

Use a current AWS CLI with `eventsv2` and AgentCore support, Docker with ARM64
build support, and the locked Python environment. Authenticate through the
normal AWS credential chain. This deployment uses profile `Decionis` in
`us-east-1`; select your own profile/account when reproducing it.

```sh
export AWS_PROFILE=Decionis
export AWS_REGION=us-east-1
make canvas-image canvas-worker validate-infra
```

Create a reviewed CloudFormation change set for
[`foundation.yaml`](../infra/firetv/foundation.yaml), with `CAPABILITY_IAM`.
The foundation creates a dedicated VPC, two private subnets, an S3 gateway
endpoint, interface endpoints for ECR API/ECR Docker/Bedrock Runtime/Logs, a
versioned private artifact bucket, immutable ECR repository, rotating KMS key,
VPC flow logs, and a multi-region CloudTrail audit trail. It has no internet
gateway or NAT gateway.

The foundation parameters are:

| Parameter | Selection |
| --- | --- |
| `VpcCidr` | An available private range; default `10.83.0.0/16`. |
| `FirstAvailabilityZoneId`, `SecondAvailabilityZoneId` | Two AgentCore-supported AZ IDs; this run uses `use1-az1` and `use1-az2`. |
| `S3PrefixListId` | The regional S3 managed prefix list; `pl-63a5400a` in this run. |
| `RuntimeName` | The same name used by the application, `homebound_canvas`. |
| `ModelResourceArns` | The exact inference profile and every regional foundation-model ARN it routes to. |

Resolve supported AZ IDs and service availability in the target account before
using another region. CloudFormation parameters use a JSON array of
`{"ParameterKey":"name","ParameterValue":"value"}` objects. Keep deployment
parameter files and AWS outputs under the ignored `.homebound/cloud-deployment/`.

This run uses `us.amazon.nova-lite-v1:0`, with its account-specific inference
profile ARN in `us-east-1` and the `amazon.nova-lite-v1:0` foundation-model ARNs
in `us-east-1`, `us-east-2`, and `us-west-2`. Confirm enabled model access in the
destination account; a model identifier alone does not grant access.

After reviewing and executing the foundation change set, obtain its outputs
with `aws cloudformation describe-stacks`. Verify the VPC endpoints are
`available` and `aws cloudtrail get-trail-status` reports `IsLogging: true`.

Push the ARM64 image using an immutable release tag. Pass the ECR login password
directly from `aws ecr get-login-password` to `docker login --password-stdin`;
do not print or save it. Record the pushed image digest and the ECR scan results.
`make canvas-image` disables the separate provenance manifest so the artifact
is a single ARM64 image. Deploy its `RepositoryUri@sha256:...` reference.

Upload `.homebound/canvas-worker.zip` to the foundation artifact bucket using
`aws s3api put-object`, `--server-side-encryption aws:kms`, the foundation's
`ArtifactKeyArn`, and `--checksum-algorithm SHA256`. Use a content-hash release
prefix and retain the returned `VersionId`. The Lambda function references
that exact version, not a mutable object key alone.

## Application stages

[`ambient-canvas.yaml`](../infra/firetv/ambient-canvas.yaml) creates the encrypted
bus/queues, published Guardrails policy, private IAM-authenticated runtime,
versioned endpoint, Lambda bridge, usage telemetry and three CloudWatch alarms.

Prepare the application parameter file:

| Parameter | Value/source |
| --- | --- |
| `RuntimeName` | Match the foundation. |
| `ContainerImageUri` | Immutable ECR image digest. |
| `EcrRepositoryArn` | Foundation `RepositoryArn`. |
| `ModelId`, `ModelResourceArns` | Enabled model and exact ARN set used by the foundation. |
| `PrivateSubnetIds`, `RuntimeSecurityGroupIds` | Foundation outputs with the same names. |
| `WorkerArtifactBucket`, `WorkerArtifactKey`, `WorkerArtifactVersion` | Uploaded ZIP bucket/key/version. |
| `CreateRuntimeEndpoint` | Initially `false`. |
| `EndpointRuntimeVersion` | Initially `1`; later the verified READY version. |
| `EnableConsumer` | Initially `false`. |
| `ReserveWorkerConcurrency` | `false` for accounts that cannot retain 100 unreserved Lambda executions. |

For each stage, create a change set, inspect its actions and
`aws cloudformation describe-events --change-set-name ... --filters FailedEvents=true`,
then execute only the reviewed change set. Keep existing parameter values when
updating. Do not replace the retained event bus or FIFO subscriber as a routine
release operation.

1. Deploy the runtime with `CreateRuntimeEndpoint=false` and
   `EnableConsumer=false`. Wait for stack completion and check
   `aws bedrock-agentcore-control get-agent-runtime` reports `READY`.
2. Update `CreateRuntimeEndpoint=true` and `EndpointRuntimeVersion` to that
   READY version. Keep `EnableConsumer=false`. Verify the named `canvas`
   endpoint reports `READY` using `get-agent-runtime-endpoint`.
3. Configure the platform log groups and run the runtime checks below.
4. Update `EnableConsumer=true`; verify the event-source mapping is `Enabled`,
   then run the event check before starting another home receiver.

AgentCore can remain `CREATING` after CloudFormation makes its attributes
available. Creating a named endpoint in the initial operation can fail with
HTTP 409. The separate endpoint parameter also lets an image update finish
before moving the stable endpoint to its new version. Keep the old endpoint
version during image provisioning, verify the new version, then update
`EndpointRuntimeVersion`.

The SQS mapping always caps concurrency at two. A reserved Lambda concurrency
of two is optional because AWS requires at least 100 executions to remain
unreserved; a fresh account with a quota of ten cannot set that reservation.

## Runtime configuration and verification

AgentCore creates its DEFAULT diagnostic log group automatically. Declaring
that same name as a new CloudFormation resource causes an `AlreadyExists`
failure. The configuration helper applies the stack's KMS key and 14-day
retention to the platform-owned DEFAULT and canvas log groups, verifies the
result, and writes an owner-only file containing non-secret connection settings:

```sh
.venv/bin/python scripts/configure_canvas_cloud.py \
  --stack homebound-canvas --region us-east-1 --profile Decionis
.venv/bin/python scripts/verify_canvas_cloud.py \
  --stack homebound-canvas --region us-east-1 --profile Decionis \
  --report .homebound/cloud-deployment/runtime-verification.json
```

The runtime check invokes a typed event, obtains an actual Bedrock recipe
proposal, verifies the published Guardrails policy allows ordinary text and
blocks a synthetic email address, and checks platform-log encryption/retention.
The template supplies `USAGE_LOGS`. AgentCore `APPLICATION_LOGS` contains raw
invocation payloads, so the verifier refuses that log type for this runtime.
Application stdout/stderr contains startup diagnostics and generic failures.

After enabling the worker, run the following on an idle demo route with every
other home receiver stopped. It publishes labelled events through the actual
AWS pipeline and consumes them with a disposable in-memory home. It does not
read the developer's SQLite notes.

```sh
.venv/bin/python scripts/verify_canvas_cloud.py \
  --stack homebound-canvas --region us-east-1 --profile Decionis --events \
  --report .homebound/cloud-deployment/event-verification.json
```

The event check verifies arrival at the receiver, event integrity, bus
deduplication, older-presence rejection, guest redaction, pantry updates, and
the cartoon's program/break/resume sequence. Successful publication alone is
not delivery confirmation. The check does not benchmark production latency.

Start the local stack with the cloud configuration after verification:

```sh
./scripts/run-demo.sh --cloud --with-services
```

`--cloud` must be the first launcher argument. It loads the normal ignored root
configuration, then `.homebound/cloud-deployment/runtime.env`. Credentials stay
in the AWS SDK's normal credential chain. Keep the simulator's localhost port
forwarding and existing authority services; the cloud deployment does not
provide a public web server or household authentication.

## Operations, cost and recovery

The three alarms cover worker errors, exhausted processing retries, and failed
EventBridge deliveries. **CloudWatch only** is the current operator preference;
no SNS destination or email subscription is configured.

Four interface endpoint services in two AZs cost approximately **$58.40/month**
at $0.01 per endpoint network interface hour and 730 hours/month, before data
processing. KMS, storage, logs, alarms, Bedrock and AgentCore add charges. This
estimate is for continuously provisioned networking, not an AWS bill or a
guarantee of free-tier eligibility. See [PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/).

The initial ECR scan reported 3 high, 9 medium and 3 low base-library findings.
The available Debian stable package versions had no newer candidates at rollout.
High findings were [CVE-2026-19499](https://security-tracker.debian.org/tracker/CVE-2026-19499),
[CVE-2026-5435](https://security-tracker.debian.org/tracker/CVE-2026-5435), and
[CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091).
This is an unresolved release limitation. Rebuild and rescan when upstream
fixes are available. The runtime is private and unprivileged, but those
controls do not remove the findings.

Queues, event bus, log groups, S3 buckets, ECR images and KMS keys are retained
across stack deletion. Disabling the consumer stops polling but does not stop
networking or storage charges. Routine local shutdown does not delete retained
cloud data. Review actual retained resources and AgentCore ENIs before removing
the dedicated network; service-managed ENIs can remain for several hours.

When diagnosing CloudFormation failures, use `describe-events --filters
FailedEvents=true` and distinguish provider failures from cancellation effects.
The first rollout revealed platform log-group ownership, endpoint readiness,
and a scoped `logs:PutResourcePolicy` permission requirement. A failed initial
stack's eight retained data resources were recovered through an IMPORT change
set before reapplying the corrected application. Preserve their identifiers
and inspect the import plan rather than creating duplicate retained resources.

The hackathon submission and judge bundle remain the snapshot submitted on
23 October 2026. Cloud rollout evidence is recorded separately after submission.
