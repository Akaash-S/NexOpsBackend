#!/usr/bin/env bash
# NexOps Post-Deploy Health & Smoke Verification Runner
# Usage:
#   HEALTH_CHECK_SECRET="your-secret" BASE_URL="https://api.nexops.asolvitra.tech" ./scripts/post_deploy_smoke.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CMD="python3"

if ! command -v "$PYTHON_CMD" &> /dev/null; then
    PYTHON_CMD="python"
fi

exec "$PYTHON_CMD" "${SCRIPT_DIR}/post_deploy_smoke.py" "$@"
