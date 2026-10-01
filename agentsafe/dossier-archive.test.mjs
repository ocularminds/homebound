import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { DossierArchive } from "./dossier-archive.mjs";

test("retrieves the org-scoped dossier, independently verifies its signed proof, and preserves it", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "homebound-dossier-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const raw = JSON.stringify({
    dossier_id: "dd-123",
    verification: {
      verification_url:
        "https://api.decionis.com/v1/public/decision-dossiers/dd-123/proof-bundle?sig=signature-token",
    },
  });
  const requests = [];
  const archive = new DossierArchive({
    apiBase: "https://api.decionis.com",
    apiKey: "real-key-provided-at-runtime",
    tenantId: "123e4567-e89b-12d3-a456-426614174000",
    directory,
    fetchImpl: async (url, init) => {
      requests.push({ url: new URL(url), init });
      return new Response(raw, { status: 200, headers: { "content-type": "application/json" } });
    },
    verifier: async (input) => {
      assert.equal(
        input.dossierUrl,
        "https://api.decionis.com/v1/public/decision-dossiers/dd-123/proof-bundle?sig=signature-token",
      );
      assert.equal(input.jwksUrl, "https://api.decionis.com/v1/.well-known/decision-dossier-jwks.json");
      return {
        payload: { dossier_id: "dd-123", verification: { verification_url: input.dossierUrl } },
        result: {
          verified: true,
          required_artifact_coverage_verified: true,
          verified_artifact_paths: ["/portable_artifact"],
        },
        trust_anchor: { status: "DECIONIS_OFFICIAL", trusted: true },
      };
    },
  });

  const result = await archive.archive("dd-123", "correlation-1");
  assert.equal(result.verified, true);
  assert.equal(result.signature_verified, true);
  assert.equal(result.trust_anchor, "DECIONIS_OFFICIAL");
  assert.equal(requests[0].url.pathname, "/v1/protocol/dossiers/dd-123");
  assert.equal(requests[0].url.searchParams.get("org_id"), "123e4567-e89b-12d3-a456-426614174000");
  assert.equal(requests[0].init.headers.authorization, "Bearer real-key-provided-at-runtime");
  const stored = await readFile(path.join(directory, `${result.reference}.json`), "utf8");
  assert.equal(stored, raw);
  const metadata = JSON.parse(
    await readFile(path.join(directory, `${result.reference}.verification.json`), "utf8"),
  );
  assert.equal(metadata.dossier_id, "dd-123");
  assert.equal(metadata.correlation_id, "correlation-1");
  assert.equal(metadata.verification.verified, true);
});

test("refuses a proof URL outside the configured Decionis origin", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "homebound-dossier-reject-"));
  try {
    const archive = new DossierArchive({
      apiBase: "https://api.decionis.com",
      apiKey: "real-key-provided-at-runtime",
      tenantId: "123e4567-e89b-12d3-a456-426614174000",
      directory,
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            dossier_id: "dd-123",
            verification: { verification_url: "https://attacker.example/proof?sig=x" },
          }),
          { status: 200 },
        ),
    });
    await assert.rejects(archive.archive("dd-123"), /DOSSIER_VERIFICATION_URL_REFUSED/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
