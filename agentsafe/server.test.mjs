import assert from "node:assert/strict";
import test from "node:test";

import { homeActions, ringHandlers } from "./server.mjs";

test("registers only the three vendor-neutral home capabilities", () => {
  const registered = new Map();
  const names = ringHandlers({
    registry: {
      register(name, handler) {
        registered.set(name, handler);
        return this;
      },
    },
  });

  assert.deepEqual(names, ["home.entry.unlock", "home.security.disarm", "home.camera.view_stream"]);
  assert.deepEqual([...registered.keys()], homeActions);
});

function fixture(verified = true) {
  const registered = new Map();
  const calls = [];
  ringHandlers(
    {
      registry: { register: (name, handler) => registered.set(name, handler) },
      downstream: {
        url: "http://127.0.0.1:8200/actions",
        lookupUrl: "http://127.0.0.1:8200/evidence/{idempotency_key}",
      },
      credential: {
        async headersFor(request) {
          calls.push({ kind: "credential", request });
          return { "x-homebound-simulator-token": "simulator-token" };
        },
      },
      async fetch(input, init) {
        const url = new URL(input);
        calls.push({ kind: url.pathname === "/actions" ? "action" : "evidence", url, init });
        return {
          ok: verified || url.pathname === "/actions",
          status: verified || url.pathname === "/actions" ? 200 : 409,
          async json() {
            return url.pathname === "/actions"
              ? { action: "unlockDoor", result: "executed" }
              : {
                  dossier_id: "dossier-1",
                  verified,
                  reference: "dossier-audit-ref",
                  trust_anchor: "DECIONIS_OFFICIAL",
                };
          },
        };
      },
    },
  );
  return { registered, calls };
}

const executionContext = () => ({
  intent: {
    intent: {
      action: "home.entry.unlock",
      target: "side_gate",
      parameters: {
        homebound_purpose: "delivery",
        context_signals: { delivery_expected: true },
        device_parameters: { unlock_duration_seconds: 30 },
      },
      intentId: "intent-1",
      intentHash: "sha256:intent-1",
      idempotencyKey: "idem-1",
      correlationId: "corr-1",
    },
    intentHash: "sha256:intent-1",
  },
  parameters: {},
  authorization: {
    decisionId: "decision-1",
    dossierId: "dossier-1",
    grantId: "grant-1",
    intentHash: "sha256:intent-1",
    expiresAt: "2030-01-01T00:00:00Z",
    claimAttestation: "eyJhbGciOiJFZERTQSJ9.claim.signature",
  },
  dispatch: {
    idempotencyKey: "idem-1",
    async run(operation) {
      return operation("idem-1");
    },
  },
});

test("archives and verifies the exact dossier before the one dispatch", async () => {
  const { registered, calls } = fixture(true);
  const result = await registered.get("home.entry.unlock").execute(executionContext());

  assert.equal(result.result, "executed");
  assert.deepEqual(calls.map((call) => call.kind), ["credential", "evidence", "credential", "action"]);
  assert.equal(calls[1].url.pathname, "/evidence/dossier-1");
  assert.equal(calls[3].init.headers["x-agent-safe-grant-id"], "grant-1");
  assert.equal(
    calls[3].init.headers["x-agent-safe-authorization-expires-at"],
    "2030-01-01T00:00:00Z",
  );
  assert.equal(
    JSON.parse(calls[3].init.body).authorization_expires_at,
    "2030-01-01T00:00:00Z",
  );
  assert.equal(calls[3].init.headers["x-agent-safe-claim-attestation"], "eyJhbGciOiJFZERTQSJ9.claim.signature");
  assert.equal(calls[3].init.body.includes('"target":"side_gate"'), true);
});

test("an absent or invalid signed dossier prevents physical dispatch", async () => {
  const { registered, calls } = fixture(false);
  let dispatchCalled = false;

  await assert.rejects(
    registered.get("home.entry.unlock").execute({
      ...executionContext(),
      dispatch: {
        async run() {
          dispatchCalled = true;
        },
      },
    }),
    /DECISION_DOSSIER_NOT_VERIFIED_BEFORE_DISPATCH/,
  );
  assert.equal(dispatchCalled, false);
  assert.equal(calls.some((call) => call.kind === "action"), false);
});

test("action schemas reject missing or additional envelope fields", () => {
  const registered = new Map();
  ringHandlers({ registry: { register: (name, handler) => registered.set(name, handler) } });
  const schema = registered.get("home.security.disarm").parametersSchema;
  assert.equal(
    schema.safeParse({
      homebound_purpose: "child requested disarm",
      context_signals: { user: "child" },
      device_parameters: {},
    }).success,
    true,
  );
  assert.equal(schema.safeParse({ context_signals: {}, device_parameters: {} }).success, false);
  assert.equal(
    schema.safeParse({
      homebound_purpose: "delivery",
      context_signals: {},
      device_parameters: {},
      tenant_id: "agent-supplied-tenant",
    }).success,
    false,
  );
});
