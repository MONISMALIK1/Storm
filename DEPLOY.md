# TOW Intelligence Platform — Production Deployment Guide

> **Architecture summary:** All 5 layers (scraping → ingest → storage → API → dashboard) run on
> **one machine** because they share a SQLite file and an in-process event bus. Do not split them
> across machines until you have replaced SQLite with Postgres and the event bus with Redis.

---

## Option A — VPS + Nginx + systemd (recommended)

**Best for:** full control, cheapest, matches the single-process SQLite architecture perfectly.  
**Recommended VPS:** Hetzner CX22 (€4/mo, 2 vCPU, 4 GB RAM, Ubuntu 24.04) or DigitalOcean Basic.

---

### 1. Provision the server

```bash
# On your LOCAL machine — copy your SSH key to the new server
ssh-copy-id root@<server-ip>
ssh root@<server-ip>
```

```bash
# ON THE SERVER — update, create a non-root user, harden SSH
apt update && apt upgrade -y
useradd -m -s /bin/bash storm
usermod -aG sudo storm
mkdir -p /home/storm/.ssh
cp ~/.ssh/authorized_keys /home/storm/.ssh/
chown -R storm:storm /home/storm/.ssh
chmod 700 /home/storm/.ssh && chmod 600 /home/storm/.ssh/authorized_keys

# Disable password login (key-only)
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd
```

---

### 2. Install system dependencies

```bash
apt install -y python3.12 python3.12-venv python3-pip nginx certbot python3-certbot-nginx git
```

---

### 3. Deploy the application

```bash
# Clone (or rsync) the project
mkdir -p /opt/storm
git clone https://github.com/YOUR_ORG/storm.git /opt/storm
# -- OR -- rsync from your laptop:
# rsync -avz --exclude='.git' --exclude='*.db' --exclude='.env' \
#   ~/Desktop/storm/ storm@<server-ip>:/opt/storm/

chown -R storm:storm /opt/storm
```

```bash
# Switch to the storm user for everything app-related
su - storm
cd /opt/storm

# Create isolated virtualenv
python3.12 -m venv .venv
source .venv/bin/activate

# Install pipeline dependencies
pip install --upgrade pip
pip install -r requirements-pipeline.txt

# (Optional) install agent dependencies if you want the LangGraph agent
# pip install -r requirements-agent.txt
```

---

### 4. Configure environment variables

```bash
# Still as user storm
cp .env.example .env
chmod 600 .env      # readable only by storm user
nano .env
```

Fill in these fields — **do not skip any**:

| Variable | What to set |
|---|---|
| `INTEL_DB_PATH` | `/opt/storm/intel.db` |
| `INTEL_JWT_SECRET` | Run `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` and paste |
| `INTEL_ALLOWED_ORIGINS` | `https://intel.theorganicworld.in` (your domain) |
| `INTEL_ENV` | `production` |
| `ANTHROPIC_API_KEY` | Only if using the agent |

---

### 5. Initialise the database and create the first admin

```bash
# As storm user, with .venv active
source .venv/bin/activate

# Create all DB tables (safe to rerun — idempotent)
python -m intel.manage init-db

# Create the admin account (you'll be asked for a password if you omit --password)
python -m intel.manage create-admin --email admin@theorganicworld.in --role admin

# Pull your existing CSVs into the DB
python -m intel.manage ingest

# Run a first alert pass
python -m intel.manage scan
```

---

### 6. Install systemd services

```bash
# As root
cp /opt/storm/deploy/intel-api.service     /etc/systemd/system/
cp /opt/storm/deploy/intel-ingest.service  /etc/systemd/system/
cp /opt/storm/deploy/intel-ingest.timer    /etc/systemd/system/
cp /opt/storm/deploy/intel-scan.service    /etc/systemd/system/
cp /opt/storm/deploy/intel-scan.timer      /etc/systemd/system/

systemctl daemon-reload

# Start and enable the API (starts now + on every boot)
systemctl enable --now intel-api

# Enable the scheduled jobs
systemctl enable --now intel-ingest.timer
systemctl enable --now intel-scan.timer

# Verify
systemctl status intel-api
journalctl -u intel-api -f          # live logs
systemctl list-timers --all          # check timer schedules
```

---

### 7. Configure Nginx + TLS

```bash
# Point your DNS A record to the server IP first, then:

# Install the nginx config
cp /opt/storm/deploy/nginx.conf /etc/nginx/sites-available/storm
ln -s /etc/nginx/sites-available/storm /etc/nginx/sites-enabled/storm
rm -f /etc/nginx/sites-enabled/default     # remove the placeholder

nginx -t   # must print "syntax is ok"
systemctl reload nginx

# Get a free TLS certificate (replace with your real domain)
certbot --nginx -d intel.theorganicworld.in --non-interactive --agree-tos -m admin@theorganicworld.in

# Certbot auto-renews every 60 days via its own systemd timer
systemctl status certbot.timer
```

The dashboard is now live at `https://intel.theorganicworld.in`.

---

### 8. (Optional) Run the scraper scheduler on the server

Only do this if you want the scrapers to run automatically on the server.
They need Playwright and Chromium:

```bash
su - storm
source .venv/bin/activate
pip install playwright
playwright install chromium --with-deps
```

```bash
# As root
cp /opt/storm/deploy/intel-scheduler.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now intel-scheduler
```

---

### 9. Set up database backups

**Do this. SQLite is a single file. If the disk dies, everything is gone.**

```bash
# As root — daily backup at 3am, kept for 14 days
cat > /etc/cron.d/storm-backup << 'EOF'
0 3 * * * storm sqlite3 /opt/storm/intel.db ".backup '/opt/storm/backups/intel-$(date +\%Y\%m\%d).db'" && find /opt/storm/backups -name '*.db' -mtime +14 -delete
EOF

mkdir -p /opt/storm/backups
chown storm:storm /opt/storm/backups
```

Or use a managed backup service (DigitalOcean Spaces, AWS S3):

```bash
# Install rclone and configure an S3 remote, then:
cat > /etc/cron.d/storm-backup-s3 << 'EOF'
30 3 * * * storm rclone copy /opt/storm/intel.db s3remote:tow-backups/intel-$(date +\%Y\%m\%d).db
EOF
```

---

## Option B — Docker Compose

**Best for:** if you already have Docker on the server, or want easy rollbacks via image tags.

```bash
# On the server
git clone https://github.com/YOUR_ORG/storm.git /opt/storm
cd /opt/storm

cp .env.example .env && nano .env    # fill in secrets

# Build + start API and Nginx
docker compose -f deploy/docker-compose.yml up -d api nginx

# First-run setup
docker compose -f deploy/docker-compose.yml exec api \
    python -m intel.manage init-db

docker compose -f deploy/docker-compose.yml exec api \
    python -m intel.manage create-admin --email admin@tow.local

# Schedule ingest + scan from host cron (runs inside the container)
crontab -e
```

Add to crontab:
```
0 * * * *  docker compose -f /opt/storm/deploy/docker-compose.yml run --rm ingest
*/30 * * * *  docker compose -f /opt/storm/deploy/docker-compose.yml run --rm scan
```

### Upgrading with Docker (zero downtime):

```bash
git pull
docker compose -f deploy/docker-compose.yml build api
docker compose -f deploy/docker-compose.yml up -d --no-deps api
# Old container keeps serving until the new one passes its healthcheck
```

---

## Option C — Railway / Render (zero-ops PaaS)

**Works, but has one limitation:** these platforms use ephemeral filesystems. You must mount a
persistent volume and set `INTEL_DB_PATH` to point inside it, otherwise the database is wiped
on every deploy.

### Railway:
1. Connect your GitHub repo
2. Set all env vars from `.env.example` in the Railway dashboard
3. Set the start command: `uvicorn intel.api:app --host 0.0.0.0 --port $PORT --workers 1`
4. Add a persistent Volume, mount it at `/data`, set `INTEL_DB_PATH=/data/intel.db`
5. For scheduled ingest + scan: add Railway Cron Jobs pointing to the same service
   with commands `python -m intel.manage ingest` and `python -m intel.manage scan`

### Render:
Same approach — use a Render Disk (persistent volume), set `INTEL_DB_PATH` to the mount path.

---

## What can break and how to prevent it

| Risk | What happens | Prevention |
|---|---|---|
| **No `INTEL_JWT_SECRET`** | Every server restart logs out all users (secret regenerates) | Always set this env var before first deploy |
| **Relative `INTEL_DB_PATH`** | DB created in wrong directory if you `cd` elsewhere; two DBs diverge | Set absolute path `/opt/storm/intel.db` |
| **CORS `allow_origins=["*"]`** | Any website can send authenticated requests from a user's browser | Set `INTEL_ALLOWED_ORIGINS` to your exact domain |
| **`/docs` endpoint public** | Leaks your entire API surface + schema | Set `INTEL_ENV=production` to disable it |
| **Running as root** | Any code execution bug = full server compromise | Use the `storm` user; systemd `User=storm` enforces this |
| **No TLS** | JWT tokens travel in cleartext; WebSocket tokens in URL visible in logs | Always use Nginx + Let's Encrypt before any public access |
| **No DB backup** | Disk failure = all data gone | Set up the cron backup from Step 9 before anything else |
| **`--reload` in production** | Uvicorn watches for file changes and restarts constantly; event bus state lost | Never pass `--reload` in production; remove it from the service file |
| **Multiple Uvicorn workers** | The in-process event bus is not shared between processes; WebSocket clients on worker 2 miss events published on worker 1 | Keep `--workers 1` until you migrate the bus to Redis |
| **Ingest + API writing SQLite simultaneously** | SQLite WAL mode handles this fine for reads; concurrent *writes* can get `database is locked` | systemd timers run short bursts; WAL mode gives 5 second retry window — acceptable for this scale |
| **Scrapers write to wrong path** | `ingest.py` uses `ROOT = Path(__file__).parent.parent` — it auto-discovers CSVs relative to the code | Keep all CSV files in `/opt/storm/` (the project root); don't move them |
| **Old `intel.db-shm` / `intel.db-wal` files** | WAL files left behind after an unclean shutdown can prevent SQLite from opening | Let SQLite recover them automatically on next open; never manually delete `-wal`/`-shm` files |

---

## Deployment checklist (run before going live)

```
☐ INTEL_JWT_SECRET is set to a 64-char random string
☐ INTEL_DB_PATH is an absolute path
☐ INTEL_ENV=production (disables /docs, /redoc, /openapi.json)
☐ INTEL_ALLOWED_ORIGINS set to your exact domain (not *)
☐ Default admin password changed from ChangeMe1234
☐ HTTPS is working (nginx -t + curl -I https://yourdomain.com)
☐ WebSocket works (open dashboard → check the ● indicator is green)
☐ DB backup cron is active (crontab -l | grep storm)
☐ systemctl status intel-api shows "active (running)"
☐ systemctl list-timers shows intel-ingest and intel-scan timers
☐ journalctl -u intel-api shows no errors
```

---

## Day-to-day operations

```bash
# View live API logs
journalctl -u intel-api -f

# Restart the API (e.g. after a code change)
sudo systemctl restart intel-api

# Deploy a code update
cd /opt/storm
git pull
sudo systemctl restart intel-api   # old process drains, new one starts

# Manually trigger an ingest (outside the timer schedule)
sudo systemctl start intel-ingest.service

# Manually trigger an alert scan
sudo systemctl start intel-scan.service

# Add a new user from the CLI
sudo -u storm /opt/storm/.venv/bin/python -m intel.manage create-admin \
    --email analyst@theorganicworld.in --role analyst

# List all users
sudo -u storm /opt/storm/.venv/bin/python -m intel.manage users

# Check SQLite file size and WAL status
ls -lh /opt/storm/intel.db*
sudo -u storm sqlite3 /opt/storm/intel.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Restore from backup (server down scenario)
systemctl stop intel-api
cp /opt/storm/backups/intel-20260515.db /opt/storm/intel.db
systemctl start intel-api
```

---

## When to move beyond SQLite

The ARCHITECTURE.md already lists the upgrade path. Here's when to actually do it:

| Signal | Action |
|---|---|
| DB file > 2 GB | Run `VACUUM` first; if still > 2 GB, migrate to Postgres |
| `database is locked` errors in logs | Migrate event bus to Redis and increase Uvicorn workers |
| > 5 simultaneous dashboard users | Nginx can cache `/dashboard/summary` for 30s to reduce DB load |
| You want to run scrapers on a different machine | Migrate to Postgres (shared network DB) + Redis pub/sub |
