#!/usr/bin/env bash
# Update production code only — keeps server .env, database, media, venv.
# Usage (from repo root):
#   ./scripts/deploy_update.sh
# With your SSH key:
#   export DEPLOY_SSH_OPTS='-i ~/.ssh/your_key -o IdentitiesOnly=yes'
#   export RSYNC_RSH="ssh ${DEPLOY_SSH_OPTS}"
#   ./scripts/deploy_update.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/deploy_production.sh" "$@"
