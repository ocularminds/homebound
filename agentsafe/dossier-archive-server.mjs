import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";

import { DossierArchive } from "./dossier-archive.mjs";

const MAX_REQUEST_BYTES = 16 * 1024;

export function createArchiveServer({ archive, token, host = "127.0.0.1" }) {
  if (!isLoopback(host)) throw new Error("DOSSIER_ARCHIVE_HOST_MUST_BE_LOOPBACK");
  if (typeof token !== "string" || token.length < 32) {
    throw new Error("HOMEBOUND_DOSSIER_ARCHIVER_TOKEN must contain at least 32 characters");
  }
  return createServer(async (request, response) => {
    response.setHeader("cache-control", "no-store");
    response.setHeader("x-content-type-options", "nosniff");
    if (request.method === "GET" && request.url === "/healthz") {
      return json(response, 200, { status: "ok", service: "homebound-dossier-archive" });
    }
    if (request.method !== "POST" || request.url !== "/v1/archive") {
      return json(response, 404, { code: "NOT_FOUND" });
    }
    if (!authorized(request.headers.authorization, token)) {
      return json(response, 401, { code: "UNAUTHORIZED" });
    }
    try {
      const input = await readJson(request);
      if (
        !input ||
        typeof input !== "object" ||
        Array.isArray(input) ||
        Object.keys(input).some((key) => !["dossier_id", "correlation_id"].includes(key)) ||
        typeof input.dossier_id !== "string" ||
        (input.correlation_id !== undefined && typeof input.correlation_id !== "string")
      ) {
        return json(response, 400, { code: "REQUEST_INVALID" });
      }
      const result = await archive.archive(input.dossier_id, input.correlation_id ?? "");
      return json(response, 200, result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "DOSSIER_ARCHIVE_FAILED";
      const known = /^[A-Z][A-Z0-9_]{2,80}$/.test(message) ? message : "DOSSIER_ARCHIVE_FAILED";
      return json(response, 502, { code: known });
    }
  });
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_REQUEST_BYTES) throw new Error("REQUEST_TOO_LARGE");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function authorized(header, token) {
  if (typeof header !== "string" || !header.startsWith("Bearer ")) return false;
  const supplied = Buffer.from(header.slice(7));
  const expected = Buffer.from(token);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

function isLoopback(host) {
  return host === "127.0.0.1" || host === "localhost" || host === "::1";
}

function json(response, status, value) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(body);
}

async function main() {
  const archive = new DossierArchive({
    apiBase: process.env.DECIONIS_API_URL ?? "https://api.decionis.com",
    apiKey: process.env.DECIONIS_API_KEY,
    tenantId: process.env.EXECUTOR_TENANT_ID,
    directory:
      process.env.HOMEBOUND_DOSSIER_ARCHIVE_DIRECTORY ??
      process.env.EXECUTOR_EVIDENCE_DIR ??
      "../audit/dossiers",
  });
  const host = process.env.HOMEBOUND_DOSSIER_ARCHIVER_HOST ?? "127.0.0.1";
  const port = Number(process.env.HOMEBOUND_DOSSIER_ARCHIVER_PORT ?? "8101");
  const server = createArchiveServer({
    archive,
    token: process.env.HOMEBOUND_DOSSIER_ARCHIVER_TOKEN,
    host,
  });
  server.listen(port, host, () => {
    process.stdout.write(
      JSON.stringify({ event: "DOSSIER_ARCHIVER_LISTENING", host, port }) + "\n",
    );
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
