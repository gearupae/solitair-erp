#!/usr/bin/env bash
# Deploy Gearup ERP to production over SSH + rsync.
# - Never uploads local .env (server keeps its own secrets).
# - By default syncs code only; use --with-db to also push SQLite (dev/small setups).
#
# Usage:
#   export DEPLOY_HOST=root@89.167.54.227
#   export DEPLOY_PATH=/var/www/gearuperp
#   ./scripts/deploy_production.sh
#   ./scripts/deploy_production.sh --with-db
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${DEPLOY_HOST:-root@89.167.54.227}"
REMOTE="${DEPLOY_PATH:-/var/www/gearuperp}"
WITH_DB=false

for arg in "$@"; do
  case "$arg" in
    --with-db) WITH_DB=true ;;
    -h|--help)
      echo "Usage: $0 [--with-db]"
      echo "  DEPLOY_HOST (default root@89.167.54.227)  DEPLOY_PATH (default /var/www/gearuperp)"
      exit 0
      ;;
  esac
done

RSYNC_EXCLUDES=(
  -e "ssh -o StrictHostKeyChecking=accept-new"
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

echo "==> Remote: pip, migrate, collectstatic, restart"
ssh -o StrictHostKeyChecking=accept-new "$HOST" bash -s << EOF
set -euo pipefail
APP="${REMOTE}"

[[ -f "\${APP}/venv/bin/activate" ]] || { echo "Missing venv at \${APP}/venv"; exit 1; }

chown -R www-data:www-data "\${APP}"
cd "\${APP}"
source venv/bin/activate
pip install -q -r requirements.txt
cd "\${APP}/erp_project"
python manage.py migrate --no-input
python manage.py collectstatic --no-input
systemctl restart gunicorn
sleep 1
systemctl is-active gunicorn
EOF

echo "==> Done."
