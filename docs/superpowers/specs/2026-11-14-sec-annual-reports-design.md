# SEC annual reports tracker - design

## Intent
Take-home for In Practise (data team). Analysts need to know which annual reports exist per followed company and which fiscal year each covers. Deliver a Python job, safe to run every morning, as a PR on GitHub, built in under an hour on screen.

Tickers come from `data.csv`: AAPL JPM XOM SAP WMT CVNA.

## Goals
- One table with every annual report these 6 companies filed with the SEC in the last 20 years, plus the fiscal year it covers.
- Fiscal year = the company's own label (e.g. WMT period ending Jan 2025 = FY2025).
- Daily run is idempotent: rerunning never duplicates or corrupts rows.
- Packaged as a Docker container running a FastAPI app with an in-app scheduler.

## Non-goals
- Amendments (10-K/A, 20-F/A, 40-F/A): excluded.
- Parsing report contents or financials.
- Tickers beyond `data.csv`.

## Anti-goals
- Wrong fiscal year labels (the core value to analysts).
- Hammering SEC: respect 10 req/s and a declared User-Agent.
- Daily updates lost on container rebuild.

## Constraints
- Source: SEC EDGAR, free, no key. User-Agent required, set via `SEC_IDENTITY` env var.
- Library: `edgartools`.
- Storage: SQLite.
- Pattern follows `../vps-fastapi`: FastAPI, APScheduler `AsyncIOScheduler` cron job started in app lifespan, `pydantic-settings` config, `uv` Dockerfile, `TZ` env var.

## Approaches considered
- Fiscal year for pre-XBRL filings:
  - **Chosen: learn per-company rule from XBRL-era filings, extrapolate.** Offset = company `fy` label minus year of period end, per period-end month. Rows marked `fy_source = xbrl | inferred`. Cheap (companyfacts: 1 request per company).
  - Rejected: parse every filing's XBRL. Hundreds of downloads, still blank pre-2009.
- Scheduling:
  - **Chosen: FastAPI app with APScheduler**, matching the user's existing setup, and room for endpoints.
  - Rejected: run-once container + host cron (no API surface).
- Storage: **SQLite** (chosen, ships in the container) over Postgres/CSV.
- Seed DB: **seed into host-mounted data dir** (chosen) over baked-into-image (daily inserts lost on recreate).

## Data model
Table `annual_reports`:
| column | notes |
|---|---|
| accession_no | PK |
| ticker, cik | |
| form | 10-K, 10-KT, 20-F, 40-F (originals only; 10-K405 ended 2003, out of range) |
| filing_date | |
| period_of_report | fiscal period end date |
| fiscal_year | company's own label |
| fy_source | `xbrl`, `inferred` or `verified` |
| url | filing index URL |

Writes are upserts on `accession_no` so reruns are safe. Only change allowed on an existing row: an `inferred` fiscal year is replaced by the XBRL `fy` once companyfacts has it (my call; no extra requests, companyfacts is fetched each run anyway). Plus a small `runs` table (started_at, finished_at, status, new_rows) for `/health`.

## Two phases
1. **Backfill (in this PR):** last 20 years per ticker, including older submission pages. Same fetch code as the daily job, without the recent-only shortcut. Fiscal year from XBRL where present, else the learned rule. Result is a seed SQLite file committed/shipped in the image.
2. **Daily job (main logic):** for each ticker, fetch recent filings (1 request each), filter forms, insert accessions not yet stored. Fiscal year from companyfacts `fy` for that accession; if not yet available, apply the learned rule and mark `inferred`.

## Data gathering (edgartools 6.1.0, verified by live spike 2026-11-14)
- Identity: `set_identity(SEC_IDENTITY)` at startup. edgartools throttles to SEC's 10 req/s. Set `EDGAR_CACHE_DIR` to a path inside the container.
- Companies are configured by CIK, not resolved by ticker: XOM's ticker now resolves to the new holding company (CIK 2115436, 0 annual reports yet); history is under Exxon Mobil Corp (CIK 34088). Mapping: AAPL 320193, JPM 19617, XOM 34088 (+2115436 once it files), SAP 1000184, WMT 104169, CVNA 1690820.
- Filings: `Company(cik).get_filings(form=["10-K","10-KT","20-F","40-F"], amendments=False, filing_date="<today-20y>:").to_pandas()`. `trigger_full_load` defaults to True and returned the full 20 years (AAPL 21, JPM/XOM/SAP/WMT 20, CVNA 9). Columns: `accession_number`, `form`, `filing_date`, `reportDate`, `primaryDocument`, `isXBRL`.
- Fiscal year: `Company(cik).get_facts().to_dataframe(include_metadata=True, pit_mode=True)`, rows with `fiscal_period == "FY"`, group by `accession` -> `fiscal_year`. Exactly one value per accession in the spike.
  - Covered: US companies FY2009 onward, SAP FY2017 onward.
  - Missing (`inferred`, then validated): 3 per US company (FY2006-2008, CVNA none), SAP 11 (FY2006-2016). ~26 rows.
- Data quality found:
  - WMT XBRL `fiscal_year` is one lower for filings 2010-2014 (period Jan 2014 -> 2013) than for 2015+ (period Jan 2015 -> 2015). Walmart calls the year ending Jan 2014 "fiscal 2014", so the XBRL label is wrong there. Rule: a company's XBRL labels must give a constant offset per period-end month; outliers are flagged for validation, not trusted.
  - WMT filing 2009-04-01 has `reportDate` 2009-04-01 (should be 2009-01-31). Validation also checks period dates that do not match the company's fiscal year end.
- Learned rule: offset = fiscal_year - year(period end), per period-end month, taken from the majority of XBRL rows; 52/53-week dates shifted to the nearest month-end.
- Requests per daily run: ~13 (6 filings + 6 facts + 1 ticker map), more when a ticker has several CIKs.
- Spike outputs (filings CSV + facts parquet per company) become the test fixtures.

## Identity drift (ticker vs CIK)
- CIK = permanent SEC id of one legal entity; ticker = exchange symbol that can move between entities (XOM -> new holding company 2115436), be renamed, or be reused. A ticker maps to one or more CIKs over time.
- Table `companies(ticker, cik, name, source, added_at)`: seeded with the CIKs in Data gathering (`source = seed`). `annual_reports` stores `cik` per row.
- Daily: resolve each ticker via SEC's ticker map (`company_tickers.json`, 1 request). If it returns a CIK not in `companies`: add it (`source = auto`), fetch both CIKs from then on, keep the old CIK's history, and report the change on `/health`.
- Staleness: `/coverage` and `/health` flag a ticker whose latest period end is > ~13 months ago (overdue annual report), the symptom of an unnoticed entity change.

## Testing
- Offline only: fixtures from the spike. CI never calls SEC.
- Cover: form filter + amendment exclusion, FY from facts, learned rule incl. 52/53-week dates, idempotency (two runs, same rows), inferred -> xbrl upgrade, verified rows untouched.

## CI/CD (copy of vps-fastapi / terstel-fastapi pattern)
- `.github/dependabot.yml`: uv, docker, github-actions weekly; minor/patch grouped.
- `.github/workflows/deploy.yml`: `test` (uv sync --locked, pytest) on push/PR -> `automerge` Dependabot minor/patch after tests pass, then dispatch deploy -> `build` on push to main: build and push `ghcr.io/<owner>/sec-annual-reports:latest`. No self-hosted deploy job.
- GHCR package public.
- GitHub repo: create with `gh repo create --public`; repo and image both public so reviewers can access them.

## Runtime behaviour
- Scheduler cron at `RUN_TIME` in `TZ`.
- Catch-up: on startup, run the job if the last successful run is older than 24h (or none).
- Compose: `image:` from GHCR plus `build: .` fallback; healthcheck on `/health`.

## Build order (one-hour budget)
1. Fixtures from the spike. 2. Core: fetch, SQLite, daily job, API, Docker/Compose. 3. Backfill + seed DB. 4. Tests + CI. 5. Backfill validation agent (ship gate).

## Endpoints
- `GET /reports?ticker=&fiscal_year=` list reports.
- `POST /refresh` run the daily job now.
- `GET /coverage` per ticker: fiscal years present and gaps.
- `GET /health` liveness + last successful run.

## Deployment
- `docker-compose.yml` is the entry point: clone, set `SEC_IDENTITY`, `docker compose up -d`.
- All config as inline `environment:` in compose; no `.env` / `.env.example` (user's call, identity is just a contact email). Variables: `SEC_IDENTITY` (placeholder value in repo), `TZ` (default Europe/Amsterdam), `RUN_TIME` (HH:MM, default 07:00, read by the app's APScheduler cron).
- DB path is fixed in the image, not configurable: `/app/data/reports.db`.
- Compose bind-mounts a host folder onto `/app/data` (default `./data:/app/data`); the user only changes the host side.
- Seed DB lives outside the mount (`/app/seed/reports.db`), because the bind mount hides whatever the image has in `/app/data`. On startup it is copied to `/app/data/reports.db` only if no DB exists there.
- Port 8000 published for the API.

## Fiscal year edge cases (my calls)
- 10-KT / transition reports: use XBRL `fy` when present; otherwise inferred like any other filing.
- The learned rule applies only within the same period-end month, so a fiscal year-end change shows up as a missing rule (log a warning, leave `fiscal_year` NULL) instead of a silent wrong label.

## Backfill validation (in scope, gate for shipping)
- After the backfill, a dedicated agent checks every row (~120) against the filing's own cover page: fiscal year, period end date, form, company.
- Confirmed or corrected rows get `fy_source = verified`; corrections (label, period date) are applied to the seed DB with a short note per change.
- Ship only when every row in the 20-year range is `verified`.
- Daily job never changes `verified` rows; new rows arrive as `xbrl` or `inferred`.

## Left to the builder
- Exact edgartools calls (verify against installed version; untested assumptions so far).
- Per-period-end-month offset derivation details, including edge case of 52/53-week years (period ends a few days into the next month).
- Test approach for the fiscal year rule and idempotency.
