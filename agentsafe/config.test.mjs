import assert from "node:assert/strict";
import test from "node:test";

import { ExecutorConfigLoader } from "@decionis/agentsafe";

function managedEnvironment() {
  return {
    NODE_ENV: "development",
    EXECUTOR_MODE: "ENFORCEMENT",
    EXECUTOR_BIND_ADDRESS: "127.0.0.1",
    PORT: "8100",
    EXECUTOR_TENANT_ID: "123e4567-e89b-12d3-a456-426614174000",
    EXECUTOR_ACTOR_ID: "homebound-bedrock-agent",
    EXECUTOR_ACTOR_TYPE: "SERVICE",
    EXECUTOR_ACTOR_RUNTIME: "homebound",
    EXECUTOR_INTENT_TTL_SECONDS: "290",
    EXECUTOR_ESCALATION: "MANAGED",
    EXECUTOR_POSTURE: "DEVELOPMENT",
    EXECUTOR_ALLOW_PLAINTEXT_LISTENER: "true",
    EXECUTOR_JOURNAL_DIR: "/tmp/homebound-agentsafe-test-journal",
    DECIONIS_API_URL: "https://api.decionis.com",
    DECIONIS_API_KEY: "unit-test-value-not-a-tenant-credential",
    EXECUTOR_CALLER_TOKEN: "unit-test-value-not-a-caller-token",
    PRESENCE_APPROVER_ID: "unit-test-household-approver",
    PRESENCE_APPROVER_ROLE: "APPROVER",
    PRESENCE_VERIFICATION_LEVEL: "HIGH_CONFIDENCE",
    PRESENCE_VERIFICATION_METHODS: "WEBAUTHN,ACTIVE_LIVENESS",
    DOWNSTREAM_URL: "https://ring-adapter.disabled.invalid/actions",
    DOWNSTREAM_SYSTEM: "ring-simulator",
    DOWNSTREAM_OPERATION: "governed-action",
    DOWNSTREAM_ENVIRONMENT: "local",
    DOWNSTREAM_CREDENTIAL_HEADER: "x-homebound-disabled",
    DOWNSTREAM_CREDENTIAL: "unit-test-value-not-a-provider-credential",
    DOWNSTREAM_TIMEOUT_MS: "1000",
  };
}

test("managed mode delegates Presence to Decionis without a Presence API key", () => {
  const config = ExecutorConfigLoader.load(managedEnvironment());

  assert.equal(config.escalation.mode, "MANAGED");
  assert.equal(config.escalation.approverId, "unit-test-household-approver");
  assert.equal(config.authority.baseUrl, "https://api.decionis.com");
  assert.equal(config.secrets.required.includes("DECIONIS_API_KEY"), true);
  assert.equal(config.secrets.required.includes("PRESENCE_API_KEY"), false);
});

test("AgentSafe refuses managed mode without its required trusted approver identity", () => {
  const environment = managedEnvironment();
  delete environment.PRESENCE_APPROVER_ID;

  assert.throws(
    () => ExecutorConfigLoader.load(environment),
    /CONFIG_INVALID: PRESENCE_APPROVER_ID/,
  );
});
