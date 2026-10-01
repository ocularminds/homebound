import { serve } from "@decionis/agentsafe";
import { z } from "zod";
import { pathToFileURL } from "node:url";

export const ringActions = Object.freeze([
  "unlockDoor",
  "disarmSystem",
  "viewStream",
]);

const parametersSchema = z.strictObject({
  homebound_purpose: z.string().trim().min(1).max(240),
  context_signals: z.record(z.string(), z.unknown()),
  device_parameters: z.record(z.string(), z.unknown()),
});

/** Register HomeBound's fixed actions in the official AgentSafe executor. */
export function ringHandlers({ registry }) {
  for (const action of ringActions) {
    registry.register(action, {
      parametersSchema,
      // Phase 2 validates the real authority and approval path. The only
      // physical handler lands in Phase 3; failing before dispatch means an
      // ALLOW cannot accidentally call an unconfigured Ring service.
      execute: async () => {
        throw new Error("RING_SIMULATOR_NOT_ATTACHED_PHASE_2");
      },
    });
  }
  return ringActions;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await serve(ringHandlers);
}
