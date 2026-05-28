# Deploy to Hetzner (Al Najah production)

**Server:** `root@37.27.16.210`  
**Git repo:** https://github.com/gearupae/alnajahfireerp.git  
**App path:** `/var/www/alnajahfireerp`

This is the recommended flow so you do **not** paste GitHub tokens on the server and you **do not** overwrite production `.env`.

## 1. Recommended: rsync + deploy script (from your Mac)

From the repo root:

```bash
export DEPLOY_HOST=root@37.27.16.210
export DEPLOY_PATH=/var/www/alnajahfireerp

# Code only (keeps server db.sqlite3 and .env)
./scripts/deploy_production.sh

# Code + replace SQLite with your local DB (small / dev setups only)
./scripts/deploy_production.sh --with-db
```

What the script does:

- **Rsync** project files to `DEPLOY_PATH`, with `--delete` to remove stale files.
- **Never copies** `erp_project/.env` or root `.env` — the server keeps its secrets.
- **Skips** `venv`, `.git`, `media`, `staticfiles`, `backups` (and `db.sqlite3` unless `--with-db`).
- On the server: `pip install`, `migrate`, `collectstatic`, `systemctl restart gunicorn`.

Ensure on the server:

- App lives at `/var/www/alnajahfireerp` with `venv/` and `erp_project/`.
- `erp_project/.env` exists **once**, edited on the server (use `.env.example` as a template).
- `gunicorn` systemd unit points at `WorkingDirectory=/var/www/alnajahfireerp/erp_project` (or your layout).

## 2. Optional: `git pull` on the server (no PAT in URLs)

HTTPS + personal access token on the server is fragile (tokens expire, leak in logs). Prefer **SSH deploy keys**.

### On the server

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_alnajahfireerp_deploy -N "" -C "alnajahfireerp-hetzner-deploy"
cat ~/.ssh/github_alnajahfireerp_deploy.pub
```

Add GitHub’s host key once (avoids “Host key verification failed”):

```bash
ssh-keyscan -t ed25519,rsa github.com >> ~/.ssh/known_hosts
```

### In GitHub

Repo **gearupae/alnajahfireerp** → **Settings** → **Deploy keys** → **Add deploy key**  
Paste the public key. Enable **Allow write access** only if this server must `git push` (usually leave read-only).

### SSH config on the server

`~/.ssh/config`:

```
Host github.com-alnajahfireerp
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_alnajahfireerp_deploy
    IdentitiesOnly yes
```

### Point the repo at GitHub over SSH

```bash
cd /var/www/alnajahfireerp
git config --global --add safe.directory /var/www/alnajahfireerp
git remote set-url origin git@github.com-alnajahfireerp:gearupae/alnajahfireerp.git
git fetch origin
git checkout main
git reset --hard origin/main
```

After that, deploys can be “pull on server” instead of rsync, **or** you keep using `./scripts/deploy_production.sh` from your laptop (simplest).

## 3. GitHub credentials

- **Rotate** any password or PAT that was shared in chat or committed; create a **new fine-grained PAT** with repo scope only, short expiry, or use **SSH keys** / **deploy keys** only.
- Do **not** store PATs in `git remote` URLs on the server.

## 4. Database

- **SQLite**: use `./scripts/deploy_production.sh --with-db` when you intend to replace production data, or follow `erp_project/DEPLOY_DATA.md`.
- **PostgreSQL** (recommended for real production): keep DB on the server; deploy code only; use dumps/migrations as in `DEPLOY_DATA.md`.

## 5. `db.sqlite3` in Git

`db.sqlite3` is listed in `.gitignore` but may still be **tracked** if it was added before. To stop tracking (optional):

```bash
git rm --cached erp_project/db.sqlite3
git commit -m "Stop tracking SQLite DB; use deploy script or DEPLOY_DATA.md"
```

Keep using `--with-db` when you still want to push a copy from your laptop.
