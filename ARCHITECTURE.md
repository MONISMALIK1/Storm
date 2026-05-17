# Competitive & Market Intelligence — System Architecture

**Project:** The Organic World (TOW) Hyderabad — Competitive Intelligence Platform
**Status:** v0.1 — single-tenant, local-first, SQLite-based
**Scope:** Replaces the ad-hoc CSV-based prototype with a layered pipeline (DB → analysis → alerts → API → realtime → dashboard) without disrupting the existing scrapers.

---

## 1. Design principles

1. **Right-sized for the business.** Single chain, ~14 daily jobs, thousands of records. No Kafka, no Flink, no microservices. One Python process + SQLite + FastAPI is enough.
2. **Layered, not monolithic.** Each layer has one job and a clear interface, so we can replace SQLite with Postgres, in-process pub/sub with Redis, or VADER with a transformer model — without touching anything else.
3. **Existing scrapers untouched.** `agent.py`, `direct_collector.py`, `scheduler.py`, and the Google Maps Playwright scraper keep writing their files. The new pipeline reads their outputs and writes to a unified database.
4. **Idempotent ingestion.** Content hashes (SHA-256) + SimHash near-duplicate detection prevent double-storage across reruns.
5. **Auth from day one.** No public endpoints. JWT + RBAC enforced on every route.
6. **Audit everything that mutates.** Logins, user creation, alert acks all go into `audit_log`.

---

## 2. High-level diagram

```
┌──────────────────────────── SCRAPING LAYER (existing) ────────────────────────────┐
│                                                                                    │
│  gmap agent/        agent.py          direct_collector.py    scheduler.py          │
│  (Playwright)       (LangChain+DDG)   (DDG, no LLM)          (cron loop)           │
│        │                  │                   │                    │               │
│        ▼                  ▼                   ▼                    ▼               │
│   reviews.db         tow_reviews.csv    tow_news.csv         (orchestrates)        │
│   gmap CSV           tow_competitors    tow_pricing                                │
│                      tow_intel.csv                                                 │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   │ python -m intel.manage ingest
                                   ▼
┌──────────────────── INGESTION LAYER  (intel/ingest.py) ──────────────────────────┐
│  • Reads CSVs + gmap SQLite                                                       │
│  • Computes content_hash (SHA-256) → dedupes                                      │
│  • Computes simhash → enables near-duplicate detection                            │
│  • Calls analysis layer to attach sentiment_score + sentiment label               │
│  • Publishes events (review.created, news.created, intel.created) to bus          │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
┌─────────────────────── STORAGE LAYER  (intel/db.py) ──────────────────────────────┐
│  SQLite (WAL mode, foreign keys on) — file: intel.db                              │
│                                                                                    │
│  Tables: reviews · competitors · news · pricing · intel ·                          │
│          alerts · users · audit_log                                                │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
┌────────────── ANALYSIS LAYER  (intel/analysis.py, intel/dedup_simhash.py) ────────┐
│  • Sentiment scoring (VADER if available, lexicon fallback)                       │
│  • Keyword extraction (tokenized, stopword-filtered)                              │
│  • Trend computation (7d / 30d windows)                                           │
│  • SimHash + Hamming distance for near-duplicates                                 │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
┌────────────────── ALERT ENGINE  (intel/alerts.py) ────────────────────────────────┐
│  Rules:                                                                           │
│   1. LOW_RATING_REVIEW       — any review ≤ 2★ (CRITICAL/HIGH)                    │
│   2. SENTIMENT_DROP          — 7d avg falls > 0.2 below prior baseline            │
│   3. COMPETITOR_NEWS         — any competitor news in last 24h                    │
│   4. PRICE_THREAT            — competitor ≥ 15% cheaper                            │
│   5. STRATEGIC_THREAT        — any intel of type='threat' in last 24h             │
│  Output: rows in `alerts` table + `alert.created` event on the bus                │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
┌─────────────── EVENT BUS  (intel/events.py) ──────────────────────────────────────┐
│  In-process asyncio pub/sub. `publish_sync()` safe from sync code.                │
│  Subscribers get an asyncio.Queue (max 1000) and stream events.                   │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
┌────────────── AUTH & API LAYER  (intel/auth.py, intel/api.py) ────────────────────┐
│  FastAPI app                                                                      │
│  • OAuth2 password flow → JWT (bcrypt-hashed passwords)                           │
│  • RBAC: super_admin > admin > analyst > viewer                                   │
│  • REST endpoints: /reviews /news /competitors /pricing /intel /alerts            │
│  • Admin endpoints: /admin/users /admin/ingest /alerts/scan                       │
│  • Dashboard summary: /dashboard/summary                                          │
│  • WebSocket: /ws?token=<JWT> — streams events from the bus                       │
│  • Static mount: serves the dashboard from /                                      │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
┌──────────────────── DASHBOARD  (dashboard/index.html + app.js) ───────────────────┐
│  Single-page admin UI (vanilla JS, no build step):                                │
│   • Login screen                                                                  │
│   • KPI tiles (reviews, rating, news 24h, intel 24h, competitors, alerts)         │
│   • Tabs: Overview / Alerts / Reviews / News / Competitors / Pricing / Intel     │
│   • Admin tab: trigger ingest, run alert scan, create users                       │
│   • Live event feed (WebSocket)                                                   │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory structure

```
<repo root>/
├── ARCHITECTURE.md                ← this document
├── requirements-pipeline.txt      ← new pipeline deps
│
├── intel/                          ← all new code lives here
│   ├── __init__.py
│   ├── db.py                       ← SQLAlchemy models + engine + session
│   ├── dedup_simhash.py            ← content_hash + simhash + hamming_distance
│   ├── analysis.py                 ← sentiment, keywords, trend helpers
│   ├── alerts.py                   ← rule engine + ack + format
│   ├── ingest.py                   ← CSV + gmap SQLite → unified DB adapters
│   ├── events.py                   ← in-process pub/sub bus
│   ├── auth.py                     ← JWT, bcrypt, RBAC dependencies, audit
│   ├── schemas.py                  ← Pydantic models for the API
│   ├── api.py                      ← FastAPI app + WebSocket + static mount
│   └── manage.py                   ← CLI: init-db, create-admin, ingest, serve
│
├── dashboard/                      ← static SPA, served by FastAPI
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── change_detector.py              ← UPDATED — thin shim → intel.alerts
│
├── agent.py                        ← UNCHANGED
├── direct_collector.py             ← UNCHANGED
├── scheduler.py                    ← UNCHANGED (uses change_detector shim)
├── daily_jobs.py                   ← UNCHANGED
├── dedup.py · dedup_clean.py       ← UNCHANGED (legacy CSV dedup)
├── cli.py                          ← UNCHANGED
├── seed_data.py                    ← UNCHANGED
│
└── (data files — written by scrapers, read by intel/ingest.py)
    tow_reviews.csv  tow_competitors.csv  tow_news.csv
    tow_pricing.csv  tow_intel.csv
    intel.db                        ← unified store (created by init-db)
```

---

## 4. Data model

### `reviews`
| column | type | notes |
|---|---|---|
| id | int PK |  |
| store_location | str | indexed |
| store_city | str? | from gmap data |
| store_address | text? | from gmap data |
| store_url | text? | from gmap data |
| product_name | str? |  |
| reviewer_name | str? |  |
| rating | float? | indexed; nullable for text-only sources |
| review_text | text | required |
| review_date | str? | relative phrasing from gmap (“a year ago”) |
| helpful_votes | int? |  |
| owner_response | text? |  |
| source | str | "Google Maps" \| "Justdial" \| "manual" \| ... |
| sentiment | str? | "positive" \| "neutral" \| "negative" |
| sentiment_score | float? | [-1, 1] |
| content_hash | str **unique** | dedup key |
| simhash | int? | near-dup detection |
| scraped_at | datetime? |  |
| created_at | datetime | indexed |

### `competitors`, `news`, `pricing`, `intel`
Same shape as the existing CSVs, plus:
- `content_hash` (unique) for idempotent ingestion
- `sentiment` + `sentiment_score` on `news`
- `simhash` on `news`

### `alerts`
| column | type | notes |
|---|---|---|
| id | int PK |  |
| priority | str | CRITICAL / HIGH / MEDIUM / LOW |
| subject | str |  |
| detail | text |  |
| source_type | str | review / news / pricing / intel / trend |
| source_id | int? | id in the source table |
| fingerprint | str **unique** | rule-aware dedup |
| acknowledged | bool | indexed |
| acknowledged_by | int? FK → users.id |  |
| acknowledged_at | datetime? |  |
| created_at | datetime | indexed |

### `users`
| column | type | notes |
|---|---|---|
| id | int PK |  |
| email | str **unique** |  |
| password_hash | str | bcrypt |
| role | str | super_admin / admin / analyst / viewer |
| is_active | bool |  |
| last_login_at | datetime? |  |

### `audit_log`
Every privileged action (login, create_user, ack_alert, ingest, ...) is appended.

---

## 5. Authentication & RBAC

- **Login flow:** `POST /auth/login` with `username` (email) + `password` form-encoded → returns JWT bearer token. Token TTL configurable via `INTEL_TOKEN_TTL_MIN` (default 240 min).
- **Token verification:** `Authorization: Bearer <token>` on every protected route. `Depends(get_current_user)`.
- **Roles (ascending):** `viewer < analyst < admin < super_admin`.
- **Route guards:** `Depends(require_role("viewer"))` etc. Returns 403 if the user's rank is below the requirement.
- **Secret:** `INTEL_JWT_SECRET` env var. If unset, a random secret is generated per process (invalidates tokens on restart — set it explicitly in production).
- **Audit trail:** writes to `audit_log` for `login`, `create_user`, `ack_alert`.

| Role | Can do |
|---|---|
| viewer | Read all data + dashboard summary, subscribe to WS |
| analyst | + ack alerts, trigger alert scan |
| admin | + create users, trigger ingestion |
| super_admin | (reserved for future destructive ops) |

---

## 6. API surface

| Method | Path | Min role | Purpose |
|---|---|---|---|
| GET | `/health` | — | Liveness |
| POST | `/auth/login` | — | Get JWT |
| GET | `/auth/me` | viewer | Current user |
| GET | `/reviews` | viewer | Filter by store, sentiment, min_rating |
| GET | `/news` | viewer | Filter by tag, days |
| GET | `/competitors` | viewer |  |
| GET | `/pricing` | viewer |  |
| GET | `/intel` | viewer | Filter by intel_type |
| GET | `/alerts` | viewer | Recent + unacked |
| POST | `/alerts/{id}/ack` | analyst | Acknowledge an alert |
| POST | `/alerts/scan` | analyst | Force a detection pass |
| GET | `/dashboard/summary` | viewer | KPIs + sentiment split + keywords |
| GET | `/admin/users` | admin | List users |
| POST | `/admin/users` | admin | Create user |
| POST | `/admin/ingest` | admin | Trigger full ingest |
| WS | `/ws?token=<JWT>` | (any valid token) | Event stream |
| GET | `/` | — | Dashboard SPA |

Events on `/ws`:
- `hello` — connection ack
- `review.created` — new review ingested
- `news.created` — new news item ingested
- `intel.created` — new intel signal ingested
- `alert.created` — new alert raised

---

## 7. Data flow (end-to-end)

1. **Scrapers run** (gmap Playwright, LangChain agent, `direct_collector.py`). They write CSVs and `reviews.db` exactly like today — nothing changes.
2. **`intel/ingest.py` runs** (manually via `intel.manage ingest`, on a cron, or from the dashboard's admin tab). For each row:
   - Computes `content_hash`. If hash already exists in DB, skip.
   - Computes `simhash` for near-dup detection.
   - Calls `analysis.enrich_review` / `enrich_news` → sentiment label + score.
   - Inserts into the unified `intel.db`.
   - Publishes a `*.created` event on the in-process bus.
3. **`intel/alerts.py run_detection()`** sweeps the recent window and emits new alerts. Each alert has a stable `fingerprint`, so re-running the scan is idempotent. Each alert publishes `alert.created`.
4. **The API serves reads** straight from the unified DB. The WebSocket subscribes to the bus and pushes events to connected dashboards.
5. **The dashboard** loads KPIs from `/dashboard/summary`, listens on `/ws`, and updates tiles + the live feed in real time.

---

## 8. Running the system

Install dependencies:

```bash
pip install -r requirements-pipeline.txt
```

Initialize the DB:

```bash
python -m intel.manage init-db
```

Create the first admin user:

```bash
python -m intel.manage create-admin --email admin@tow.local --password ChangeMe1234
```

Pull existing data (CSVs + gmap SQLite) into the unified DB:

```bash
python -m intel.manage ingest
```

Run the alert engine over the recent window:

```bash
python -m intel.manage scan
```

Start the API + dashboard:

```bash
python -m intel.manage serve --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 and sign in.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `INTEL_DB_PATH` | Path to SQLite file | `intel.db` |
| `INTEL_JWT_SECRET` | JWT signing key | random (per-process) |
| `INTEL_TOKEN_TTL_MIN` | Access token TTL in minutes | `240` |

---

## 9. Non-functional properties

- **Concurrency.** SQLite WAL mode permits multi-reader + single-writer. Adequate for one writer (the API + scheduler) at a time.
- **Idempotency.** Content hashes on every row + alert fingerprints. Safe to rerun ingestion or detection unlimited times.
- **Observability.** All writes go through SQLAlchemy → easy to add SQL logging. Audit log captures privileged actions.
- **Security defaults.** All routes auth-gated (no public reads). Bcrypt password hashing. CORS open by default — **tighten before exposing publicly** by setting `allow_origins=[...]` in `api.py`.
- **Failure modes.** WebSocket queue caps at 1000 events per subscriber, dropping oldest if a slow client backs up. Sentiment falls back to a lexicon if VADER is unavailable.

---

## 10. What we will revisit

- **SQLite → Postgres** when concurrent writers or > ~10M rows.
- **In-process bus → Redis pub/sub** when running multiple API processes.
- **Lexicon/VADER sentiment → fine-tuned transformer** when accuracy matters.
- **REST → GraphQL** if the dashboard grows complex enough to warrant it.
- **Single tenant → multi-tenant** by adding `tenant_id` to every table + row-level filtering in the auth dependency.

---

## 11. Build status

| Layer | File(s) | Status |
|---|---|---|
| Data | `intel/db.py` | ✅ Built |
| Dedup | `intel/dedup_simhash.py` | ✅ Built |
| Analysis | `intel/analysis.py` | ✅ Built |
| Event bus | `intel/events.py` | ✅ Built |
| Alerts | `intel/alerts.py` | ✅ Built |
| Ingestion | `intel/ingest.py` | ✅ Built |
| Auth | `intel/auth.py` | ✅ Built |
| API | `intel/api.py` + `intel/schemas.py` | ✅ Built |
| Dashboard | `dashboard/{index.html,styles.css,app.js}` | ✅ Built |
| Management CLI | `intel/manage.py` | ✅ Built |
| Legacy bridge | `change_detector.py` (shim) | ✅ Updated |
| Deps | `requirements-pipeline.txt` | ✅ Added |
