# Deploy Local Data to Main Server

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

2. **Copy to server** (replace `user@server` and `/path/to/erp` with your values):
   ```bash
   scp erp_project/db.sqlite3 user@server:/path/to/erp/erp_project/
   ```

3. **On the server**, stop the app, replace the DB, run migrations, restart:
   ```bash
   cd /path/to/erp/erp_project
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
