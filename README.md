# 🌿 TOW Intelligence Platform

> **Competitive & market intelligence dashboard for The Organic World, Hyderabad.**
> Aggregates store reviews, app reviews, competitor signals, news, and pricing into a
> single real-time dashboard — with analytics charts, live event streaming, and an
> AI-powered LangGraph agent for daily briefings.

---

## What it does

| Layer | What it does |
|---|---|
| **Scraping** | Collects Google Maps reviews (Playwright), news & competitor signals (LangChain + DuckDuckGo), pricing data |
| **Ingestion** | Deduplicates with SHA-256 content hashes + SimHash near-duplicate detection; enriches with VADER sentiment |
| **Alert Engine** | Rule-based detection — low ratings, sentiment drops, competitor news, price threats, strategic signals |
| **API** | JWT-authenticated FastAPI REST + WebSocket live event stream |
| **Dashboard** | 7-tab analytics SPA (vanilla JS, Chart.js) served directly from FastAPI |
| **AI Agent** | LangGraph + Claude — generates daily executive briefs, alert scans, strategic recommendations |

---

## Dashboard tabs

| Tab | Charts & data |
|---|---|
| **Overview** | KPI tiles, store sentiment donut, app topic bar, keyword cloud, recent alerts |
| **App Experience** | Star rating distribution, sentiment donut, platform split, topic bar, review list |
| **Product Quality** | Stock status donut, avg price by category, products-per-category bar, discount leaderboard, 1,791-product searchable table |
| **Store Reviews** | Rating distribution bar, sentiment donut, filterable review list |
| **Market Intel** | TOW vs competitor price comparison bar, news-by-tag bar, competitor cards, price threat list |
| **Review Explorer** | Full-text search across store + app reviews |
| **Live Feed** | Real-time WebSocket event stream (review / news / intel / alert events) |

---

## Tech stack

```
Backend        FastAPI 0.110 + Uvicorn
Database       SQLite (WAL mode) via SQLAlchemy 2.0
Auth           JWT (python-jose) + bcrypt (passlib) + RBAC
Sentiment      VADER + lexicon fallback
Dedup          SHA-256 content hash + SimHash (Hamming distance)
Event bus      In-process asyncio pub/sub → WebSocket push
AI Agent       LangGraph + Anthropic Claude
Frontend       Vanilla JS SPA — zero build step
Charts         Chart.js 4.4 (CDN)
Deployment     Uvicorn + Nginx + systemd (or Railway / Docker Compose)
```

---

## Project structure

```
storm/
├── intel/                     ← core pipeline (all new code)
│   ├── db.py                  ← SQLAlchemy models + engine
│   ├── ingest.py              ← CSV + SQLite → unified DB
│   ├── analysis.py            ← sentiment, keywords, trends
│   ├── alerts.py              ← rule-based alert engine
│   ├── events.py              ← in-process pub/sub bus
│   ├── auth.py                ← JWT, bcrypt, RBAC, audit log
│   ├── api.py                 ← FastAPI app + WebSocket + static mount
│   ├── schemas.py             ← Pydantic schemas
│   ├── manage.py              ← CLI: init-db, ingest, scan, serve, agent
│   └── agent/                 ← LangGraph CI agent
│       ├── graph.py           ← agent graph topology
│       ├── nodes.py           ← agent node implementations
│       ├── tools.py           ← DB query tools for the agent
│       └── prompts.py         ← system prompt + output formatters
│
├── dashboard/                 ← static SPA (served by FastAPI)
│   ├── index.html             ← 7-tab layout with 13 chart canvases
│   ├── styles.css             ← light green theme
│   └── app.js                 ← full tab logic + Chart.js engine + WebSocket
│
├── deploy/                    ← production deployment config
│   ├── intel-api.service      ← systemd unit (Uvicorn)
│   ├── intel-ingest.{service,timer}  ← hourly ingest job
│   ├── intel-scan.{service,timer}    ← 30-min alert scan
│   ├── nginx.conf             ← reverse proxy + TLS + rate limiting
│   ├── Dockerfile             ← multi-stage Docker image
│   └── docker-compose.yml     ← API + Nginx + cron jobs
│
├── agent.py                   ← existing LangChain scraper (unchanged)
├── scheduler.py               ← existing cron orchestrator (unchanged)
├── change_detector.py         ← thin shim → intel.alerts
├── requirements-pipeline.txt  ← API + DB dependencies
├── requirements-agent.txt     ← LangGraph + Anthropic dependencies
├── .env.example               ← environment variable template
├── ARCHITECTURE.md            ← full system design document
└── DEPLOY.md                  ← production deployment guide
```

---

## Quick start (local)

### 1. Install dependencies
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-pipeline.txt

# Optional — only needed for the AI agent
pip install -r requirements-agent.txt
```

### 2. Set environment variables
```bash
cp .env.example .env
# Edit .env — at minimum set INTEL_JWT_SECRET to a random string
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 3. Initialise the database and load data
```bash
python -m intel.manage init-db
python -m intel.manage ingest
python -m intel.manage scan
```

### 4. Create an admin account
```bash
python -m intel.manage create-admin --email admin@tow.local --role admin
# Enter password when prompted
```

### 5. Start the server
```bash
python -m intel.manage serve
```

Open **http://localhost:8000** and sign in.

---

## CLI reference

```bash
python -m intel.manage init-db                          # create DB tables (idempotent)
python -m intel.manage create-admin --email EMAIL       # create a user
python -m intel.manage users                            # list all users
python -m intel.manage ingest                           # pull CSVs → DB
python -m intel.manage scan                             # run alert detection
python -m intel.manage serve --host 0.0.0.0 --port 8000

# AI Agent
python -m intel.manage agent --brief                    # daily executive briefing
python -m intel.manage agent --alerts                   # alert scan via LLM
python -m intel.manage agent --strategy                 # strategic recommendations
python -m intel.manage agent --task "What are the top competitor threats this week?"
python -m intel.manage agent                            # interactive REPL
```

---

## API overview

All endpoints require `Authorization: Bearer <token>` except `/health` and `/auth/login`.

| Method | Path | Role | Purpose |
|---|---|---|---|
| `POST` | `/auth/login` | — | Get JWT (form: username + password) |
| `GET` | `/dashboard/summary` | viewer | KPIs, sentiment split, top keywords |
| `GET` | `/dashboard/app-summary` | viewer | App review analytics |
| `GET` | `/dashboard/product-summary` | viewer | Stock, category, discount breakdown |
| `GET` | `/reviews` | viewer | Store reviews (filter by sentiment, rating) |
| `GET` | `/app-reviews` | viewer | App reviews (filter by platform, topic) |
| `GET` | `/products` | viewer | Product catalogue (search, filter) |
| `GET` | `/news` | viewer | News items |
| `GET` | `/competitors` | viewer | Competitor list |
| `GET` | `/pricing` | viewer | Price comparison records |
| `GET` | `/intel` | viewer | Intel signals |
| `GET` | `/alerts` | viewer | Alerts (filter unacknowledged) |
| `POST` | `/alerts/{id}/ack` | analyst | Acknowledge alert |
| `POST` | `/alerts/scan` | analyst | Trigger detection pass |
| `POST` | `/admin/ingest` | admin | Trigger full ingest |
| `POST` | `/admin/users` | admin | Create user |
| `WS` | `/ws?token=JWT` | viewer | Real-time event stream |

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `INTEL_JWT_SECRET` | **Yes** | random (breaks on restart) | JWT signing key — generate with `secrets.token_urlsafe(64)` |
| `INTEL_DB_PATH` | No | `intel.db` | Absolute path to SQLite file |
| `INTEL_ENV` | No | `development` | Set to `production` to disable `/docs` |
| `INTEL_ALLOWED_ORIGINS` | No | `*` | Comma-separated CORS origins for production |
| `INTEL_TOKEN_TTL_MIN` | No | `240` | JWT lifetime in minutes |
| `ANTHROPIC_API_KEY` | Agent only | — | Claude API key for the LangGraph agent |

---

## Data model (key tables)

```
reviews        — store reviews (Google Maps, Justdial, CSV)
app_reviews    — App Store + Play Store reviews
products       — TOW product catalogue (1,791 products)
competitors    — competitor profiles
news           — market news items
pricing        — TOW vs competitor price records
intel          — strategic intel signals
alerts         — rule-triggered alerts (CRITICAL / HIGH / MEDIUM / LOW)
users          — dashboard users (bcrypt passwords, RBAC roles)
audit_log      — every privileged action logged
```

---

## RBAC roles

| Role | Permissions |
|---|---|
| `viewer` | Read all data, subscribe to WebSocket |
| `analyst` | + Acknowledge alerts, trigger alert scan |
| `admin` | + Create users, trigger ingest |
| `super_admin` | Reserved for future destructive operations |

---

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for the complete guide covering:
- VPS + Nginx + systemd (recommended, ~₹350/month on Hetzner)
- Railway (zero-ops PaaS, ~₹850/month)
- Docker Compose

**TL;DR for production:**
```bash
# Set these in .env before deploying:
INTEL_JWT_SECRET=<64-char random string>
INTEL_DB_PATH=/opt/storm/intel.db
INTEL_ENV=production
INTEL_ALLOWED_ORIGINS=https://yourdomain.com
```

---

## Architecture decisions

- **SQLite over Postgres** — right-sized for single-tenant, ~14 daily jobs, thousands of records. WAL mode handles concurrent reads + one writer. Upgrade path documented.
- **In-process event bus** — asyncio queues push WebSocket events without Redis. Adequate for one Uvicorn worker. Redis upgrade path is a single interface swap.
- **No build step** — dashboard is vanilla JS + Chart.js CDN. Zero toolchain, deploys as static files.
- **Idempotent ingestion** — SHA-256 content hash on every row. Safe to run `ingest` unlimited times.
- **VADER sentiment** — fast, offline, no API cost. Accuracy is acceptable for operational intelligence; swap in a transformer when it matters.

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full design document.

---

## License

Private — internal use only. © The Organic World, Hyderabad.
