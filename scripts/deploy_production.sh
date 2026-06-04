#!/usr/bin/env bash
# Deploy Al Najah Fire ERP to production over SSH + rsync.
# - Never uploads local .env (server keeps its own secrets).
# - By default syncs code only; use --with-db to also push SQLite (dev/small setups).
#
# Usage:
#   export DEPLOY_HOST=root@37.27.16.210
#   export DEPLOY_PATH=/var/www/alnajahfireerp
#   export RSYNC_RSH='ssh -i ~/.ssh/alnajah_hetzner -o IdentitiesOnly=yes'
#   export DEPLOY_SSH_OPTS='-i ~/.ssh/alnajah_hetzner -o IdentitiesOnly=yes'
#   ./scripts/deploy_production.sh
#   ./scripts/deploy_production.sh --with-db
#   DEPLOY_RUN_PIP=1 ./scripts/deploy_production.sh   # optional pip install on server
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${DEPLOY_HOST:-root@37.27.16.210}"
REMOTE="${DEPLOY_PATH:-/var/www/alnajahfireerp}"
SSH_OPTS="${DEPLOY_SSH_OPTS:--o StrictHostKeyChecking=accept-new}"
RSYNC_SSH="${RSYNC_RSH:-ssh ${SSH_OPTS}}"
WITH_DB=false

for arg in "$@"; do
  case "$arg" in
    --with-db) WITH_DB=true ;;
    -h|--help)
      echo "Usage: $0 [--with-db]"
      echo "  DEPLOY_HOST (default root@37.27.16.210)  DEPLOY_PATH (default /var/www/alnajahfireerp)"
      echo "  Git repo: https://github.com/gearupae/alnajahfireerp.git"
      exit 0
      ;;
  esac
done

RSYNC_EXCLUDES=(
  -e "${RSYNC_SSH}"
  --archive
  --delete
  --exclude '.git'
  --exclude 'venv'
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.DS_Store'
  --exclude 'backups'
  --exclude 'erp_project/.env'
  --exclude '.env'
  --exclude 'media'
  --exclude 'staticfiles'
  --exclude 'erp_project/staticfiles'
)

if [[ "$WITH_DB" != true ]]; then
  RSYNC_EXCLUDES+=(--exclude 'erp_project/db.sqlite3')
fi

echo "==> Rsync to ${HOST}:${REMOTE}"
echo "    with-db: ${WITH_DB}"
rsync "${RSYNC_EXCLUDES[@]}" "${ROOT}/" "${HOST}:${REMOTE}/"

echo "==> Remote: migrate, collectstatic, restart (pip: ${DEPLOY_RUN_PIP:-0})"
ssh ${SSH_OPTS} "$HOST" bash -s << EOF
set -euo pipefail
APP="${REMOTE}"

[[ -f "\${APP}/venv/bin/activate" ]] || { echo "Missing venv at \${APP}/venv"; exit 1; }

chown -R www-data:www-data "\${APP}"
cd "\${APP}"
source venv/bin/activate
if [[ "\${DEPLOY_RUN_PIP:-}" == "1" ]]; then
  pip install -q -r requirements.txt || echo "WARN: pip install failed; continuing with existing venv"
fi
cd "\${APP}/erp_project"
python manage.py migrate --no-input
python manage.py collectstatic --no-input
systemctl restart gunicorn
sleep 1
systemctl is-active gunicorn
EOF

echo "==> Done."
