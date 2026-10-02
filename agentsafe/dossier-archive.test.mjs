import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { DossierArchive } from "./dossier-archive.mjs";

const ORG_ID = "123e4567-e89b-12d3-a456-426614174000";

test("retrieves the org-scoped proof packet, verifies its signature, and preserves both source responses", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "homebound-dossier-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const payload = {
    dossier_id: "dd-123",
    org_id: ORG_ID,
    integrity: { proof_bundle: { bundle_type: "decionis.decision_dossier.proof_bundle" } },
  };
  const rawDossier = Buffer.from(JSON.stringify({ dossier: payload }));
  const rawPacket = Buffer.from(
    JSON.stringify({
      packet_type: "decionis.decision_dossier.proof_packet",
      subject: { dossier_id: "dd-123", org_id: ORG_ID },
      dossier: payload,
      verification: { overall: "VERIFIED" },
    }),
  );
  const requests = [];
  const archive = new DossierArchive({
    apiBase: "https://api.decionis.com",
    apiKey: "real-key-provided-at-runtime",
    tenantId: ORG_ID,
    directory,
    fetchImpl: async (url, init) => {
      requests.push({ url: new URL(url), init });
      return new Response(url.pathname.endsWith("proof-packet") ? rawPacket : rawDossier, {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
    jwksFetcher: async (url, options) => {
      assert.equal(url, "https://api.decionis.com/v1/.well-known/decision-dossier-jwks.json");
      assert.equal(options.fetch instanceof Function, true);
      return { keys: [] };
    },
    verifier: async (input) => {
      assert.deepEqual(input.dossier_payload, payload);
      assert.deepEqual(input.public_jwks, { keys: [] });
      return {
        verified: true,
        required_artifact_coverage_verified: true,
        verified_artifact_paths: ["/portable_artifact"],
      };
    },
  });

  const result = await archive.archive("dd-123", "correlation-1");
  assert.equal(result.verified, true);
  assert.equal(result.signature_verified, true);
  assert.equal(result.trust_anchor, "DECIONIS_OFFICIAL");
  assert.equal(requests.length, 2);
  assert.equal(requests[0].url.pathname, "/v1/protocol/dossiers/dd-123");
  assert.equal(requests[1].url.pathname, "/v1/protocol/dossiers/dd-123/proof-packet");
  for (const request of requests) {
    assert.equal(request.url.searchParams.get("org_id"), ORG_ID);
    assert.equal(request.init.headers.authorization, "Bearer real-key-provided-at-runtime");
  }
  const stored = await readFile(path.join(directory, `${result.reference}.json`));
  const storedPacket = await readFile(path.join(directory, `${result.reference}.proof-packet.json`));
  assert.deepEqual(stored, rawDossier);
  assert.deepEqual(storedPacket, rawPacket);
  const metadata = JSON.parse(
    await readFile(path.join(directory, `${result.reference}.verification.json`), "utf8"),
  );
  assert.equal(metadata.dossier_id, "dd-123");
  assert.equal(metadata.correlation_id, "correlation-1");
  assert.equal(metadata.verification.verified, true);
});

test("refuses proof packets whose tenant-bound subject does not match", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "homebound-dossier-reject-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const payload = { dossier_id: "dd-123", org_id: ORG_ID, integrity: { proof_bundle: {} } };
  const archive = new DossierArchive({
    apiBase: "https://api.decionis.com",
    apiKey: "real-key-provided-at-runtime",
    tenantId: ORG_ID,
    directory,
    fetchImpl: async (url) =>
      new Response(
        JSON.stringify(
          url.pathname.endsWith("proof-packet")
            ? {
                packet_type: "decionis.decision_dossier.proof_packet",
                subject: { dossier_id: "dd-123", org_id: "123e4567-e89b-12d3-a456-426614174001" },
                dossier: payload,
              }
            : { dossier: payload },
        ),
        { status: 200 },
      ),
    jwksFetcher: async () => assert.fail("must reject before retrieving JWKS"),
    verifier: async () => assert.fail("must reject before verifying an unrelated packet"),
  });
  await assert.rejects(archive.archive("dd-123"), /DOSSIER_PROOF_PACKET_SUBJECT_MISMATCH/);
});

test("a valid signature without required authority coverage is not dispatch eligible", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "homebound-dossier-partial-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const payload = { dossier_id: "dd-123", org_id: ORG_ID, integrity: { proof_bundle: {} } };
  const archive = new DossierArchive({
    apiBase: "https://api.decionis.com",
    apiKey: "real-key-provided-at-runtime",
    tenantId: ORG_ID,
    directory,
    fetchImpl: async (url) =>
      new Response(
        JSON.stringify(
          url.pathname.endsWith("proof-packet")
            ? {
                packet_type: "decionis.decision_dossier.proof_packet",
                subject: { dossier_id: "dd-123", org_id: ORG_ID },
                dossier: payload,
              }
            : { dossier: payload },
        ),
        { status: 200 },
      ),
    jwksFetcher: async () => ({ keys: [] }),
    verifier: async () => ({ verified: true, required_artifact_coverage_verified: false }),
  });
  const result = await archive.archive("dd-123");
  assert.equal(result.signature_verified, true);
  assert.equal(result.required_artifact_coverage_verified, false);
  assert.equal(result.verified, false);
});
