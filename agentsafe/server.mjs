import { serve } from "@decionis/agentsafe";
import { z } from "zod";
import { pathToFileURL } from "node:url";

export const homeActionBindings = Object.freeze([
  Object.freeze({ authorityAction: "home.entry.unlock", deviceAction: "unlockDoor" }),
  Object.freeze({ authorityAction: "home.security.disarm", deviceAction: "disarmSystem" }),
  Object.freeze({ authorityAction: "home.camera.view_stream", deviceAction: "viewStream" }),
]);
export const homeActions = Object.freeze(
  homeActionBindings.map(({ authorityAction }) => authorityAction),
);

const parametersSchema = z.strictObject({
  homebound_purpose: z.string().trim().min(1).max(240),
  context_signals: z.record(z.string(), z.unknown()),
  device_parameters: z.record(z.string(), z.unknown()),
});

/** Register simulator actions behind AgentSafe's grant claim and dispatch boundary. */
export function ringHandlers({ registry, downstream, credential, fetch }) {
  for (const { authorityAction, deviceAction } of homeActionBindings) {
    registry.register(authorityAction, {
      parametersSchema,
      execute: async ({ intent: captured, authorization, dispatch }) => {
        const intent = captured.intent;
        if (!downstream.lookupUrl?.includes("{idempotency_key}")) {
          throw new Error("RING_SIMULATOR_LOOKUP_URL_NOT_CONFIGURED");
        }
        const evidenceUrl = new URL(
          downstream.lookupUrl.replace(
            "{idempotency_key}",
            encodeURIComponent(authorization.dossierId),
          ),
        );
        const evidenceHeaders = await credential.headersFor({
          method: "POST",
          url: evidenceUrl.toString(),
          body: null,
          idempotencyKey: intent.idempotencyKey,
          intentHash: captured.intentHash,
          grant: {
            id: authorization.grantId,
            decisionId: authorization.decisionId,
            ...(authorization.claimAttestation
              ? { claimAttestation: authorization.claimAttestation }
              : {}),
          },
        });
        const evidenceResponse = await fetch(evidenceUrl, {
          method: "POST",
          headers: {
            ...evidenceHeaders,
            accept: "application/json",
            "idempotency-key": intent.idempotencyKey,
            "x-agent-safe-decision-id": authorization.decisionId,
            "x-agent-safe-dossier-id": authorization.dossierId,
            "x-agent-safe-grant-id": authorization.grantId,
            "x-agent-safe-intent-hash": captured.intentHash,
            "x-homebound-correlation-id": intent.correlationId ?? "",
            ...(authorization.claimAttestation
              ? { "x-agent-safe-claim-attestation": authorization.claimAttestation }
              : {}),
          },
          redirect: "error",
        });
        const receivedEvidence = await evidenceResponse.json().catch(() => ({}));
        const evidence = receivedEvidence && typeof receivedEvidence === "object"
          ? receivedEvidence
          : {};
        if (!evidenceResponse.ok || evidence.verified !== true || evidence.dossier_id !== authorization.dossierId) {
          throw new Error("DECISION_DOSSIER_NOT_VERIFIED_BEFORE_DISPATCH");
        }

        return dispatch.run(async (idempotencyKey) => {
          const body = JSON.stringify({
            action: deviceAction,
            target: intent.target,
            parameters: intent.parameters,
            idempotency_key: idempotencyKey,
            correlation_id: intent.correlationId ?? "",
            intent_id: intent.intentId,
            intent_hash: captured.intentHash,
            decision_id: authorization.decisionId,
            dossier_id: authorization.dossierId,
            grant_id: authorization.grantId,
            authorization_expires_at: authorization.expiresAt,
            claim_attestation: authorization.claimAttestation ?? null,
            dossier_evidence: {
              verified: true,
              reference: evidence.reference,
              trust_anchor: evidence.trust_anchor,
            },
          });
          const headers = await credential.headersFor({
            method: "POST",
            url: downstream.url,
            body,
            idempotencyKey,
            intentHash: captured.intentHash,
            grant: {
              id: authorization.grantId,
              decisionId: authorization.decisionId,
              ...(authorization.claimAttestation
                ? { claimAttestation: authorization.claimAttestation }
                : {}),
            },
          });
          const response = await fetch(downstream.url, {
            method: "POST",
            headers: {
              ...headers,
              accept: "application/json",
              "content-type": "application/json",
              "idempotency-key": idempotencyKey,
              "x-agent-safe-decision-id": authorization.decisionId,
              "x-agent-safe-dossier-id": authorization.dossierId,
              "x-agent-safe-grant-id": authorization.grantId,
              "x-agent-safe-authorization-expires-at": authorization.expiresAt,
              "x-agent-safe-intent-id": intent.intentId,
              "x-agent-safe-intent-hash": captured.intentHash,
              "x-homebound-correlation-id": intent.correlationId ?? "",
              ...(authorization.claimAttestation
                ? { "x-agent-safe-claim-attestation": authorization.claimAttestation }
                : {}),
            },
            body,
            redirect: "error",
          });
          const result = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error("RING_SIMULATOR_REFUSED_EXECUTION");
          }
          return result;
        });
      },
      reconcile: async ({ idempotencyKey }) => {
        if (!downstream.lookupUrl?.includes("{idempotency_key}")) {
          return { status: "UNKNOWN" };
        }
        const lookup = new URL(
          downstream.lookupUrl.replace("{idempotency_key}", encodeURIComponent(idempotencyKey)),
        );
        const response = await fetch(lookup, { method: "GET", redirect: "error" });
        if (response.status === 404) return { status: "NOT_EXECUTED" };
        if (!response.ok) return { status: "UNKNOWN" };
        const result = await response.json().catch(() => null);
        if (!result || typeof result !== "object" || result.result !== "executed") {
          return { status: "UNKNOWN" };
        }
        return { status: "COMPLETED", result };
      },
    });
  }
  return homeActions;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await serve(ringHandlers);
}
