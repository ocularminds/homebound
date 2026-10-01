import assert from "node:assert/strict";
import test from "node:test";

import { ringActions, ringHandlers } from "./server.mjs";

test("registers only the three declared Ring actions", () => {
  const registered = new Map();
  const names = ringHandlers({
    registry: {
      register(name, handler) {
        registered.set(name, handler);
        return this;
      },
    },
  });

  assert.deepEqual(names, ["unlockDoor", "disarmSystem", "viewStream"]);
  assert.deepEqual([...registered.keys()], ringActions);
});

test("Phase 2 handler fails before the AgentSafe dispatch boundary", async () => {
  const registered = new Map();
  ringHandlers({ registry: { register: (name, handler) => registered.set(name, handler) } });
  const handler = registered.get("unlockDoor");
  let dispatchCalled = false;

  await assert.rejects(
    handler.execute({
      dispatch: {
        run: async () => {
          dispatchCalled = true;
        },
      },
    }),
    /RING_SIMULATOR_NOT_ATTACHED_PHASE_2/,
  );
  assert.equal(dispatchCalled, false);
});

test("action schemas reject missing or additional envelope fields", () => {
  const registered = new Map();
  ringHandlers({ registry: { register: (name, handler) => registered.set(name, handler) } });
  const schema = registered.get("disarmSystem").parametersSchema;
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
