import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  assessDossierIssuer,
  assessDossierReproducibility,
  assessJwksTrustAnchor,
  extractDossierPayload,
  fetchVerificationJson,
  stableJsonStringify,
  verifyDossierProofBundle,
} from "@decionis/verify";

const MAX_DOSSIER_BYTES = 2 * 1024 * 1024;
const OFFICIAL_JWKS = "https://api.decionis.com/v1/.well-known/decision-dossier-jwks.json";

export class DossierArchive {
  constructor({
    apiBase,
    apiKey,
    tenantId,
    directory,
    fetchImpl = fetch,
    verifier = verifyDossierProofBundle,
    jwksFetcher = fetchVerificationJson,
  }) {
    const base = new URL(apiBase);
    if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash) {
      throw new Error("DECIONIS_API_URL must be an absolute HTTPS base URL");
    }
    if (!apiKey?.trim() || !tenantId?.trim()) {
      throw new Error("DECIONIS_API_KEY and EXECUTOR_TENANT_ID are required for dossier archiving");
    }
    this.apiBase = base.toString().replace(/\/$/, "");
    this.apiKey = apiKey;
    this.tenantId = tenantId;
    this.directory = path.resolve(directory);
    this.fetch = fetchImpl;
    this.verifier = verifier;
    this.jwksFetcher = jwksFetcher;
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
    const dossierRecord = record(rawDossier.dossier);
    if (payload.dossier_id !== dossierId || dossierRecord.org_id !== this.tenantId) {
      throw new Error("DOSSIER_ID_OR_TENANT_MISMATCH");
    }
    const proofPacketUrl = new URL(
      `${this.apiBase}/v1/protocol/dossiers/${encodeURIComponent(dossierId)}/proof-packet`,
    );
    proofPacketUrl.searchParams.set("org_id", this.tenantId);
    const proofPacketResponse = await this.fetch(proofPacketUrl, {
      method: "GET",
      headers: { accept: "application/json", authorization: `Bearer ${this.apiKey}` },
      redirect: "error",
      signal: AbortSignal.timeout(15_000),
    });
    const proofPacketBytes = await boundedBody(proofPacketResponse);
    if (!proofPacketResponse.ok) throw new Error(`DOSSIER_PROOF_PACKET_HTTP_${proofPacketResponse.status}`);
    const proofPacket = JSON.parse(proofPacketBytes.toString("utf8"));
    const subject = record(proofPacket.subject);
    const checkedPayload = extractDossierPayload(proofPacket);
    if (
      proofPacket.packet_type !== "decionis.decision_dossier.proof_packet" ||
      subject.dossier_id !== dossierId ||
      subject.org_id !== this.tenantId ||
      checkedPayload.dossier_id !== dossierId ||
      stableJsonStringify(checkedPayload) !== stableJsonStringify(payload)
    ) {
      throw new Error("DOSSIER_PROOF_PACKET_SUBJECT_MISMATCH");
    }
    const publicJwks = await this.jwksFetcher(OFFICIAL_JWKS, {
      fetch: this.fetch,
      timeoutMs: 15_000,
    });
    const checked = await this.verifier({ dossier_payload: checkedPayload, public_jwks: publicJwks });
    const trustAnchor = assessJwksTrustAnchor(OFFICIAL_JWKS);
    const verifiedPaths = new Set(checked.verified_artifact_paths ?? []);
    const issuer = assessDossierIssuer(checkedPayload, verifiedPaths);
    const reproducibility = assessDossierReproducibility(
      checkedPayload,
      verifiedPaths,
    );
    const signatureVerified = checked.verified === true;
    const requiredCoverageVerified = checked.required_artifact_coverage_verified === true;
    const verified = signatureVerified && requiredCoverageVerified && trustAnchor.trusted;
    const reference = `dossier-${safeId(dossierId)}`;

    await this.persist(reference, dossierBytes, proofPacketBytes, {
      dossier_id: dossierId,
      correlation_id: correlationId,
      archived_at: new Date().toISOString(),
      source: "GET /v1/protocol/dossiers/:dossierId?org_id=...",
      proof_packet_source: "GET /v1/protocol/dossiers/:dossierId/proof-packet?org_id=...",
      verifier: "@decionis/verify",
      proof_bundle: record(record(checkedPayload.integrity).proof_bundle),
      verification: checked,
      trust_anchor: trustAnchor,
      issuer,
      reproducibility,
      raw_dossier_sha256: `sha256:${createHash("sha256").update(dossierBytes).digest("hex")}`,
      raw_proof_packet_sha256: `sha256:${createHash("sha256").update(proofPacketBytes).digest("hex")}`,
    });

    return {
      dossier_id: dossierId,
      correlation_id: correlationId,
      reference,
      verified,
      signature_verified: signatureVerified,
      required_artifact_coverage_verified: requiredCoverageVerified,
      trust_anchor: trustAnchor.status,
      issuer: issuer.label,
      reproducibility: reproducibility.posture,
      verifier: "@decionis/verify",
    };
  }

  async persist(reference, dossierBytes, proofPacketBytes, verificationRecord) {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const base = path.join(this.directory, reference);
    const dossierPath = `${base}.json`;
    const proofPacketPath = `${base}.proof-packet.json`;
    const metadataPath = `${base}.verification.json`;
    await persistImmutable(dossierPath, dossierBytes, "DOSSIER_ARCHIVE_IMMUTABLE_CONFLICT");
    await persistImmutable(proofPacketPath, proofPacketBytes, "DOSSIER_PROOF_PACKET_IMMUTABLE_CONFLICT");
    const metadata = `${JSON.stringify(verificationRecord, null, 2)}\n`;
    const tempMetadata = `${metadataPath}.${process.pid}.tmp`;
    await writeFile(tempMetadata, metadata, { mode: 0o600 });
    await rename(tempMetadata, metadataPath);
  }
}

async function persistImmutable(filePath, bytes, conflictCode) {
  try {
    const previous = await readFile(filePath);
    if (!previous.equals(bytes)) throw new Error(conflictCode);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    const temporary = `${filePath}.${process.pid}.tmp`;
    await writeFile(temporary, bytes, { mode: 0o600, flag: "wx" });
    await rename(temporary, filePath);
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
