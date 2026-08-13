# Deploy Local Data to Main Server (Solitair ERP)

**Server:** `root@178.105.89.41`  
**App path:** `/var/www/solitair`  
**Git repo:** https://github.com/gearupae/solitair-erp.git

For **full production deploy** (code, no `.env` overwrite, optional DB), use from repo root:

- `docs/DEPLOY_HETZNER.md`
- `scripts/deploy_production.sh`

To replace the main server database with your local data:

## Option 1: SQLite (default)

1. **On your local machine**, the database is at:
   ```
   erp_project/db.sqlite3
   ```
   A backup was created at:
   ```
   erp_project/backups/db_backup_YYYYMMDD_HHMMSS.sqlite3
   ```

2. **Copy to server**:
   ```bash
   scp erp_project/db.sqlite3 root@178.105.89.41:/var/www/solitair/erp_project/
   ```

3. **On the server**, stop the app, replace the DB, run migrations, restart:
   ```bash
   cd /var/www/solitair/erp_project
   # Backup existing server DB first (optional)
   mv db.sqlite3 db.sqlite3.old
   # Copy the uploaded file as db.sqlite3 (or it was uploaded directly)
   python manage.py migrate
   # Restart your app (gunicorn, systemd, etc.)
   ```

## Option 2: PostgreSQL

1. **On local** (dump):
   ```bash
   python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission -o backup.json
   ```
   Or full dump:
   ```bash
   pg_dump -U your_user your_db > backup.sql
   ```

2. **On server** (restore):
   ```bash
   # Clear existing data and restore
   psql -U your_user your_db < backup.sql
   # Or for dumpdata:
   python manage.py flush --no-input
   python manage.py loaddata backup.json
   ```

## After deploy

- Run `python manage.py migrate` to apply any new migrations
- Run `python manage.py collectstatic --noinput` if using static files
- Restart the application server
