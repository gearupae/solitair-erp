#!/usr/bin/env bash
# Deploy Gearup ERP to production over SSH + rsync.
# - Never uploads local .env (server keeps its own secrets).
# - By default syncs code only; use --with-db to also push SQLite (dev/small setups).
#
# Usage:
#   export DEPLOY_HOST=root@89.167.54.227
#   export DEPLOY_PATH=/var/www/gearuperp
#   export RSYNC_RSH='ssh -i ~/.ssh/your_key -o IdentitiesOnly=yes'
#   export DEPLOY_SSH_OPTS='-i ~/.ssh/your_key -o IdentitiesOnly=yes'
#   ./scripts/deploy_production.sh
#   ./scripts/deploy_production.sh --with-db
#   DEPLOY_RUN_PIP=1 ./scripts/deploy_production.sh   # optional pip install on server
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${DEPLOY_HOST:-root@89.167.54.227}"
REMOTE="${DEPLOY_PATH:-/var/www/gearuperp}"
SSH_OPTS="${DEPLOY_SSH_OPTS:--o StrictHostKeyChecking=accept-new}"
RSYNC_SSH="${RSYNC_RSH:-ssh ${SSH_OPTS}}"
WITH_DB=false

for arg in "$@"; do
  case "$arg" in
    --with-db) WITH_DB=true ;;
    -h|--help)
      echo "Usage: $0 [--with-db]"
      echo "  DEPLOY_HOST (default root@89.167.54.227)  DEPLOY_PATH (default /var/www/gearuperp)"
      echo "  Git repo: https://github.com/gearupae/gearuperp.git"
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
echo "    NEVER overwrites: erp_project/.env, .env, venv/, media/, staticfiles/"
echo "    NEVER overwrites: db.sqlite3 (unless --with-db)"
rsync "${RSYNC_EXCLUDES[@]}" "${ROOT}/" "${HOST}:${REMOTE}/"

echo "==> Remote: migrate, collectstatic, restart (pip: always)"
ssh ${SSH_OPTS} "$HOST" bash -s << EOF
set -euo pipefail
APP="${REMOTE}"

[[ -f "\${APP}/venv/bin/activate" ]] || { echo "Missing venv at \${APP}/venv"; exit 1; }

chown -R www-data:www-data "\${APP}"
cd "\${APP}"
source venv/bin/activate
pip install -q -r requirements.txt || echo "WARN: pip install failed; continuing with existing venv"
cd "\${APP}/erp_project"
python manage.py migrate --no-input
python manage.py collectstatic --no-input --clear
systemctl restart gunicorn
sleep 1
systemctl is-active gunicorn
EOF

echo "==> Done."
