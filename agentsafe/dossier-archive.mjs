import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  assessDossierIssuer,
  assessDossierReproducibility,
  extractDossierPayload,
  verifyDossierFromUrls,
} from "@decionis/verify";

const MAX_DOSSIER_BYTES = 2 * 1024 * 1024;
const OFFICIAL_JWKS = "https://api.decionis.com/v1/.well-known/decision-dossier-jwks.json";

export class DossierArchive {
  constructor({ apiBase, apiKey, tenantId, directory, fetchImpl = fetch, verifier = verifyDossierFromUrls }) {
    const base = new URL(apiBase);
    if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash) {
      throw new Error("DECIONIS_API_URL must be an absolute HTTPS base URL");
    }
    if (!apiKey?.trim() || !tenantId?.trim()) {
      throw new Error("DECIONIS_API_KEY and EXECUTOR_TENANT_ID are required for dossier archiving");
    }
    this.apiBase = base.toString().replace(/\/$/, "");
    this.apiOrigin = base.origin;
    this.apiKey = apiKey;
    this.tenantId = tenantId;
    this.directory = path.resolve(directory);
    this.fetch = fetchImpl;
    this.verifier = verifier;
  }

  async archive(dossierId, correlationId = "") {
    if (typeof dossierId !== "string" || !/^[A-Za-z0-9_-]{1,180}$/.test(dossierId)) {
      throw new Error("DOSSIER_ID_INVALID");
    }
    const dossierUrl = new URL(
      `${this.apiBase}/v1/protocol/dossiers/${encodeURIComponent(dossierId)}`,
    );
    dossierUrl.searchParams.set("org_id", this.tenantId);
    const response = await this.fetch(dossierUrl, {
      method: "GET",
      headers: { accept: "application/json", authorization: `Bearer ${this.apiKey}` },
      redirect: "error",
      signal: AbortSignal.timeout(15_000),
    });
    const dossierBytes = await boundedBody(response);
    if (!response.ok) throw new Error(`DOSSIER_RETRIEVAL_HTTP_${response.status}`);

    const rawDossier = JSON.parse(dossierBytes.toString("utf8"));
    const payload = extractDossierPayload(rawDossier);
    if (payload.dossier_id !== dossierId) throw new Error("DOSSIER_ID_MISMATCH");
    const verification = record(payload.verification);
    const verificationUrl = verification.verification_url;
    if (typeof verificationUrl !== "string") throw new Error("DOSSIER_VERIFICATION_URL_MISSING");
    const verificationLink = new URL(verificationUrl);
    const dossierRoute = `/v1/public/decision-dossiers/${encodeURIComponent(dossierId)}`;
    const expectedProofPath = `${dossierRoute}/proof-bundle`;
    if (
      verificationLink.protocol !== "https:" ||
      verificationLink.origin !== this.apiOrigin ||
      ![`${dossierRoute}/verify`, expectedProofPath].includes(verificationLink.pathname) ||
      !verificationLink.searchParams.has("sig")
    ) {
      throw new Error("DOSSIER_VERIFICATION_URL_REFUSED");
    }
    // The verifier package consumes Decionis' signed proof-bundle route. The
    // documented public `/verify` link carries the same signed `sig` value.
    const proofUrl = new URL(expectedProofPath, this.apiOrigin);
    verificationLink.searchParams.forEach((value, name) => proofUrl.searchParams.set(name, value));

    const checked = await this.verifier({
      dossierUrl: proofUrl.toString(),
      jwksUrl: OFFICIAL_JWKS,
      timeoutMs: 15_000,
    });
    const checkedPayload = extractDossierPayload(checked.payload);
    if (checkedPayload.dossier_id !== dossierId) throw new Error("VERIFIED_DOSSIER_ID_MISMATCH");
    const issuer = assessDossierIssuer(checkedPayload, new Set(checked.result.verified_artifact_paths ?? []));
    const reproducibility = assessDossierReproducibility(
      checkedPayload,
      new Set(checked.result.verified_artifact_paths ?? []),
    );
    const trusted = checked.trust_anchor?.trusted === true;
    const verified = checked.result?.verified === true && trusted;
    const reference = `dossier-${safeId(dossierId)}`;

    await this.persist(reference, dossierBytes, {
      dossier_id: dossierId,
      correlation_id: correlationId,
      archived_at: new Date().toISOString(),
      source: "GET /v1/protocol/dossiers/:dossierId?org_id=...",
      verifier: "@decionis/verify",
      proof_bundle: checkedPayload,
      verification: checked.result,
      trust_anchor: checked.trust_anchor,
      issuer,
      reproducibility,
      raw_dossier_sha256: `sha256:${createHash("sha256").update(dossierBytes).digest("hex")}`,
    });

    return {
      dossier_id: dossierId,
      correlation_id: correlationId,
      reference,
      verified,
      signature_verified: checked.result?.verified === true,
      required_artifact_coverage_verified:
        checked.result?.required_artifact_coverage_verified === true,
      trust_anchor: checked.trust_anchor?.status ?? "UNAVAILABLE",
      issuer: issuer.label,
      reproducibility: reproducibility.posture,
      verifier: "@decionis/verify",
    };
  }

  async persist(reference, dossierBytes, verificationRecord) {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const base = path.join(this.directory, reference);
    const dossierPath = `${base}.json`;
    const metadataPath = `${base}.verification.json`;
    try {
      const previous = await readFile(dossierPath);
      if (!previous.equals(dossierBytes)) throw new Error("DOSSIER_ARCHIVE_IMMUTABLE_CONFLICT");
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const temporary = `${dossierPath}.${process.pid}.tmp`;
      await writeFile(temporary, dossierBytes, { mode: 0o600, flag: "wx" });
      await rename(temporary, dossierPath);
    }
    const metadata = `${JSON.stringify(verificationRecord, null, 2)}\n`;
    const tempMetadata = `${metadataPath}.${process.pid}.tmp`;
    await writeFile(tempMetadata, metadata, { mode: 0o600 });
    await rename(tempMetadata, metadataPath);
  }
}

async function boundedBody(response) {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_DOSSIER_BYTES) {
    throw new Error("DOSSIER_BODY_TOO_LARGE");
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const body = Buffer.from(await response.arrayBuffer());
    if (body.length > MAX_DOSSIER_BYTES) throw new Error("DOSSIER_BODY_TOO_LARGE");
    return body;
  }
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_DOSSIER_BYTES) {
      await reader.cancel();
      throw new Error("DOSSIER_BODY_TOO_LARGE");
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks);
}

function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function safeId(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}
