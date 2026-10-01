#!/bin/sh
set -eu

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/agentsafe/.env"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Create agentsafe/.env from agentsafe/.env.example first." >&2
  exit 2
fi

set -a
. "$CONFIG_FILE"
set +a

PYTHON_BIN="$(command -v python || command -v python3)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Activate the HomeBound Python environment first." >&2
  exit 2
fi
exec env -i \
  PATH="$PATH" \
  PYTHONPATH="$PROJECT_ROOT" \
  HOMEBOUND_AUDIT_DIRECTORY="$PROJECT_ROOT/audit" \
  HOMEBOUND_SIMULATOR_HOST=127.0.0.1 \
  HOMEBOUND_SIMULATOR_PORT=8200 \
  HOMEBOUND_SIMULATOR_TOKEN="${DOWNSTREAM_CREDENTIAL:-}" \
  HOMEBOUND_SIMULATOR_DEMO_TOKEN="${HOMEBOUND_SIMULATOR_DEMO_TOKEN:-}" \
  HOMEBOUND_DOSSIER_ARCHIVER_URL="http://${HOMEBOUND_DOSSIER_ARCHIVER_HOST:-127.0.0.1}:${HOMEBOUND_DOSSIER_ARCHIVER_PORT:-8101}" \
  HOMEBOUND_DOSSIER_ARCHIVER_TOKEN="${HOMEBOUND_DOSSIER_ARCHIVER_TOKEN:-}" \
  "$PYTHON_BIN" -m app.cli.ring_simulator
