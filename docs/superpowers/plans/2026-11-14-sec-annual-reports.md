# SEC Annual Reports Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Dockerised FastAPI app that keeps a SQLite table of every original annual report (10-K, 10-KT, 20-F, 40-F) filed in the last 20 years by AAPL JPM XOM SAP WMT CVNA, with the company's own fiscal year, refreshed every morning.

**Architecture:** One network module (`edgar_client.py`) wraps edgartools + SEC's ticker map; pure modules turn its DataFrames into rows (`fiscal.py`) and store them (`db.py`); `job.py` orchestrates one idempotent run; `main.py` exposes it via FastAPI + APScheduler. A validated seed DB ships in the image and is copied to the host-mounted data dir on first start.

**Tech Stack:** Python 3.12, uv, edgartools 6.1.0, pandas, httpx, FastAPI, uvicorn, APScheduler 3.x, pydantic-settings, sqlite3 (stdlib), pytest, Docker, GitHub Actions, GHCR.

**Spec:** `docs/superpowers/specs/2026-11-14-sec-annual-reports-design.md`

## Global Constraints

- Forms: `["10-K", "10-KT", "20-F", "40-F"]`, `amendments=False`.
- Range: filings with `filing_date >= today - 20 years`.
- Seed companies (ticker, cik): AAPL 320193, JPM 19617, XOM 34088, SAP 1000184, WMT 104169, CVNA 1690820.
- `fy_source` values: `xbrl`, `inferred`, `verified`, `unknown` (fiscal_year NULL).
- `verified` rows are never modified by the job. `inferred`/`unknown` rows are upgraded when a trusted `xbrl` value appears.
- DB path fixed: `/app/data/reports.db`; seed: `/app/seed/reports.db` (repo path `seed/reports.db`).
- Env vars, inline in compose only (no `.env` files): `SEC_IDENTITY`, `TZ` (default `Europe/Amsterdam`), `RUN_TIME` (`HH:MM`, default `07:00`).
- Tests never call SEC; CI has no network-dependent tests.
- Image: `ghcr.io/<owner>/sec-annual-reports:latest`, public. GitHub repo public.
- No emojis in code or commits. Commits without Claude attribution, default git settings.

## Review Focus

1. Manual `POST /refresh` while the scheduled job runs: two concurrent runs must not both write; the second returns 409.
2. SEC/edgartools failure for one CIK (timeout, 404, CompanyFactsNotFound): the run records the error, other CIKs still process, earlier rows untouched, run status `partial`.
3. Invalid `RUN_TIME` (e.g. `7am`, `25:00`): app fails at startup with a clear message instead of silently never scheduling.
4. Garbage `reportDate` (WMT 2009-04-01) or missing `reportDate`: row gets `fiscal_year` NULL / `unknown`, never a guessed label.
5. Empty or missing `/app/data` mount on first start: seed is copied; existing DB on the mount is never overwritten.

---

## File Structure

```
pyproject.toml, uv.lock, .python-version
src/sec_reports/
  config.py        Settings + constants (forms, companies, paths)
  edgar_client.py  only module doing network: EdgarClient
  fiscal.py        pure: DataFrames -> ReportRow list with fiscal years
  db.py            sqlite schema, upsert, runs, companies, coverage queries
  job.py           run_update(): one idempotent run, drift detection
  main.py          FastAPI app factory, lifespan, scheduler, endpoints
scripts/backfill.py           builds seed/reports.db
scripts/apply_validation.py   applies seed/validation.csv -> verified
seed/reports.db, seed/validation.csv
tests/fixtures/{TICKER}_filings.csv, {TICKER}_fy_facts.csv
tests/conftest.py (FakeClient), tests/test_*.py
Dockerfile, docker-compose.yml, .dockerignore, .gitignore
.github/dependabot.yml, .github/workflows/deploy.yml
README.md, CLAUDE.md
```

---

### Task 1: Project scaffold, git, fixtures

**Files:**
- Create: `pyproject.toml`, `.python-version` (`3.12`), `.gitignore`, `src/sec_reports/__init__.py`, `tests/fixtures/*`, `CLAUDE.md`
- Test: `tests/test_fixtures.py`

- [ ] **Step 1:** `git init`, branch `main`; commit the existing `brief.md`, `data.csv`, `docs/` as the initial commit.
- [ ] **Step 2:** `uv init --package --name sec-reports` layout under `src/`; deps: `edgartools==6.1.0 pandas httpx fastapi uvicorn "apscheduler>=3.10,<4" pydantic-settings`; dev: `pytest`. `uv sync`.
- [ ] **Step 3:** `.gitignore` per global rules plus `data/`, `.edgar_cache/`. Do not ignore `seed/`.
- [ ] **Step 4:** Build fixtures from the spike outputs in the scratchpad (`out/{T}_filings.csv`, XOM from `out/XOM34088_filings.csv`, and `out/{T}_facts_pit.parquet`) with a one-off command (not committed):
  - filings: keep columns `accession_number, form, filing_date, reportDate, primaryDocument`.
  - facts: rows with `fiscal_period == "FY"`, columns `accession, fiscal_year, fiscal_period, period_end, form_type`, drop duplicates on `(accession, fiscal_year)`.
- [ ] **Step 5: Write test** `test_fixture_counts`: filings rows AAPL 21, JPM 20, XOM 20, SAP 20, WMT 20, CVNA 9; every facts accession has one `fiscal_year`.
- [ ] **Step 6:** `uv run pytest -q` -> PASS.
- [ ] **Step 7:** `CLAUDE.md` (5-10 lines: layout, `uv run pytest`, never call SEC in tests, verified rows immutable). Commit `chore: scaffold project and test fixtures`.

### Task 2: config

**Files:** Create `src/sec_reports/config.py`; Test `tests/test_config.py`

**Interfaces — Produces:**
- `FORMS: list[str]`, `SEED_COMPANIES: dict[str, list[int]]` (`{"AAPL": [320193], ...}`), `DB_PATH = Path("/app/data/reports.db")`, `SEED_PATH = Path("/app/seed/reports.db")`, `YEARS_BACK = 20`, `OVERDUE_DAYS = 395`.
- `class Settings(BaseSettings)`: `sec_identity: str`, `tz: str = "Europe/Amsterdam"`, `run_time: str = "07:00"`; property `run_hour_minute -> tuple[int, int]`. Validator rejects anything not `HH:MM` with 0<=H<24, 0<=M<60.

- [ ] **Step 1: Tests** `test_run_time_parsed` (`"07:30"` -> `(7, 30)`), `test_run_time_invalid` (`"7am"`, `"25:00"` raise `ValidationError`), `test_sec_identity_required`.
- [ ] **Step 2:** Run -> FAIL. **Step 3:** Implement. **Step 4:** Run -> PASS. **Step 5:** Commit `feat: settings and constants`.

### Task 3: fiscal year logic

**Files:** Create `src/sec_reports/fiscal.py`; Test `tests/test_fiscal.py`

**Interfaces — Produces:**
- `@dataclass ReportRow`: `accession_no: str, ticker: str, cik: int, form: str, filing_date: str, period_of_report: str | None, fiscal_year: int | None, fy_source: str, url: str`.
- `normalize_period(d: date) -> tuple[int, int]`: (year, month) of the fiscal period end; dates on day 1-7 roll back to the previous month (52/53-week years).
- `learn_offsets(pairs: list[tuple[date, int]]) -> dict[int, int]`: per period-end month, majority of `fiscal_year - normalized_year`.
- `build_rows(ticker: str, cik: int, filings: pd.DataFrame, fy_facts: pd.DataFrame) -> list[ReportRow]`.
- `filing_url(cik: int, accession: str) -> str` = `https://www.sec.gov/Archives/edgar/data/{cik}/{accession without dashes}/{accession}-index.htm`.

`build_rows` algorithm: map accession -> XBRL fiscal_year; learn offsets from rows that have both; a row is `xbrl` only if its XBRL value equals the rule for its month, otherwise (outlier, e.g. WMT 2010-2014) it gets the rule value as `inferred`; rows without XBRL get the rule value as `inferred`; no rule for the month or no/unparseable `reportDate` -> `fiscal_year=None`, `fy_source="unknown"`, log warning. Forms filtered to `FORMS` (defence in depth).

- [ ] **Step 1: Tests** (on fixtures):
  - `test_normalize_period`: `2026-09-26 -> (2026, 9)`, `2008-10-02 -> (2008, 9)`, `2025-01-31 -> (2025, 1)`.
  - `test_aapl_rows`: 21 rows; 2006 report (period 2006-09-30) `fiscal_year=2006, fy_source="inferred"`; 2025-09-27 -> `2025, "xbrl"`.
  - `test_wmt_outliers_corrected`: period 2014-01-31 -> `2014, "inferred"`; 2025-01-31 -> `2025, "xbrl"`.
  - `test_wmt_bad_period_unknown`: accession of filing 2009-04-01 -> `fiscal_year None, "unknown"`.
  - `test_sap_inferred_pre_2017`: period 2010-12-31 -> `2010, "inferred"`; 2024-12-31 -> `2024, "xbrl"`.
  - `test_amendment_dropped`: filings frame with an extra `10-K/A` row -> not in output.
  - `test_url`: `filing_url(320193, "0000320193-25-000079")` exact string.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: fiscal year derivation`.

### Task 4: database

**Files:** Create `src/sec_reports/db.py`; Test `tests/test_db.py`

**Interfaces — Produces:**
- `connect(path: Path) -> sqlite3.Connection` (creates parent dir, `row_factory=Row`, runs `init_schema`).
- Schema: `annual_reports` (columns of `ReportRow`, PK `accession_no`, plus `note TEXT`, `updated_at`), `companies(ticker, cik, name, source, added_at, PK(ticker, cik))`, `runs(id, started_at, finished_at, status, new_rows, updated_rows, message)`.
- `seed_companies(conn, mapping: dict[str, list[int]]) -> None` (insert-or-ignore, `source="seed"`).
- `company_ciks(conn) -> dict[str, list[int]]`; `add_company(conn, ticker, cik, name, source="auto") -> None`.
- `upsert_reports(conn, rows: list[ReportRow]) -> tuple[int, int]` (new, updated). `ON CONFLICT(accession_no) DO UPDATE` only `WHERE annual_reports.fy_source IN ('inferred','unknown') AND excluded.fy_source = 'xbrl'`.
- `start_run(conn) -> int`, `finish_run(conn, run_id, status, new_rows, updated_rows, message) -> None`, `last_success(conn) -> datetime | None`.
- `list_reports(conn, ticker: str | None, fiscal_year: int | None) -> list[dict]`.
- `coverage(conn, today: date) -> list[dict]`: per ticker `{ticker, ciks, fiscal_years, missing_years, latest_period, overdue, by_source}`; `overdue = today - latest_period > OVERDUE_DAYS`.
- `seed_if_missing(seed: Path, target: Path) -> bool` (copies only when target absent).

- [ ] **Step 1: Tests:** `test_upsert_idempotent` (same rows twice -> second returns `(0, 0)`, count unchanged), `test_inferred_upgraded_to_xbrl`, `test_verified_untouched` (verified row + xbrl row with other year -> unchanged), `test_xbrl_not_downgraded` (xbrl row + inferred row -> unchanged), `test_coverage_gaps_and_overdue` (years 2020, 2022 -> missing `[2021]`; latest period 400 days ago -> overdue), `test_seed_if_missing` (copies when absent; leaves existing file byte-identical).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: sqlite storage`.

### Task 5: EDGAR client

**Files:** Create `src/sec_reports/edgar_client.py`; Test `tests/conftest.py` (FakeClient), `tests/test_client_contract.py`

**Interfaces — Produces:**
- `class EdgarClient(identity: str)`: calls `edgar.set_identity(identity)`; sets `EDGAR_CACHE_DIR` to `/app/data/.edgar_cache` if unset.
  - `fetch_filings(cik: int, since: date, full: bool) -> pd.DataFrame` via `Company(cik).get_filings(form=FORMS, amendments=False, filing_date=f"{since}:", trigger_full_load=full).to_pandas()`, columns as fixtures.
  - `fetch_fy_facts(cik: int) -> pd.DataFrame` via `get_facts().to_dataframe(include_metadata=True, pit_mode=True)` filtered as in Task 1; empty frame if facts not found.
  - `resolve_tickers(tickers: list[str]) -> dict[str, tuple[int, str]]`: one `httpx.get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": identity}, timeout=30)`; returns ticker -> (cik, title). Live map, not edgartools' bundled one.
- `FakeClient` in `tests/conftest.py` with the same three methods, reading fixtures; `resolve_tickers` returns a configurable dict (default: XOM -> 2115436, others their seed CIK); can be told to raise for a given CIK.

- [ ] **Step 1: Test** `test_fake_matches_real_signature`: `inspect.signature` of each FakeClient method equals EdgarClient's.
- [ ] **Step 2:** FAIL. **Step 3:** Implement both. **Step 4:** PASS. **Step 5:** Manual smoke (one run, not in CI): `uv run python -c "...EdgarClient(id).fetch_filings(320193, date(2025,1,1), False)"` returns 2 rows. **Step 6:** Commit `feat: edgar client`.

### Task 6: update job

**Files:** Create `src/sec_reports/job.py`; Test `tests/test_job.py`

**Interfaces — Consumes:** Tasks 2-5. **Produces:**
- `@dataclass RunResult: status: str ("ok"|"partial"|"failed"), new_rows: int, updated_rows: int, added_ciks: list[tuple[str, int]], errors: list[str]`.
- `run_update(conn, client, today: date, full: bool = False) -> RunResult`: seed companies; `resolve_tickers` -> add unknown CIKs (`source="auto"`, recorded in `added_ciks`); for each (ticker, cik): fetch filings since `today - 20y`, fetch facts, `build_rows`, upsert; per-CIK exceptions go to `errors` and status `partial`; ticker-map failure is an error, not fatal. Wraps everything in `start_run`/`finish_run`.
- Module-level `RUN_LOCK = threading.Lock()`; `run_update_locked(...) -> RunResult | None` returns None if already running.

- [ ] **Step 1: Tests:** `test_first_run_counts` (110 rows total with fixtures: 21+20+20+20+20+9), `test_second_run_no_changes` (`new_rows == 0 and updated_rows == 0`), `test_drift_adds_xom_holding_cik` (`("XOM", 2115436)` in `added_ciks`; second run adds nothing), `test_one_cik_failure_partial` (FakeClient raises for 19617: status `partial`, other tickers' rows present), `test_lock_blocks_second_run`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: idempotent update job with ticker drift detection`.

### Task 7: API and scheduler

**Files:** Create `src/sec_reports/main.py`; Test `tests/test_api.py`

**Interfaces — Produces:** `create_app(settings: Settings, client, db_path: Path = DB_PATH, seed_path: Path = SEED_PATH, start_scheduler: bool = True) -> FastAPI`; `build_app() -> FastAPI` = `create_app(Settings(), EdgarClient(settings.sec_identity))`, used by uvicorn `--factory` so importing the module in tests needs no env.

Lifespan: `seed_if_missing`, `connect`, `AsyncIOScheduler(timezone=settings.tz)` cron job at `run_hour_minute` (`coalesce=True, misfire_grace_time=3600`) running `run_update_locked` via `asyncio.to_thread`; catch-up: if `last_success` is None or older than 24h, schedule an immediate one-off run. Each thread opens its own connection.

Endpoints:
- `GET /reports?ticker=&fiscal_year=` -> list of rows.
- `POST /refresh` -> 200 `RunResult` as JSON, 409 if locked.
- `GET /coverage` -> `coverage(conn, today)`.
- `GET /health` -> `{status, last_success, last_run_status, auto_added_ciks, overdue_tickers}`.

- [ ] **Step 1: Tests** (TestClient, FakeClient, tmp paths, `start_scheduler=False`): `test_refresh_then_reports` (after refresh, `/reports?ticker=WMT&fiscal_year=2014` returns 1 row with `period_of_report == "2014-01-31"`), `test_refresh_conflict_409` (hold `RUN_LOCK`), `test_health_shows_drift` (after refresh, `auto_added_ciks` contains XOM 2115436), `test_coverage_shape`, `test_seed_copied_on_start`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: fastapi app with scheduler`.

### Task 8: Docker and compose

**Files:** Create `Dockerfile`, `.dockerignore`, `docker-compose.yml`

- Dockerfile: `FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, `uv sync --locked --no-install-project` layer, copy src + `seed/` to `/app/seed/`, `uv sync --locked`, `mkdir -p /app/data`, `EXPOSE 8000`, `CMD ["uv","run","--no-sync","uvicorn","--factory","sec_reports.main:build_app","--host","0.0.0.0","--port","8000"]`.
- Compose: service `sec-reports`, `image: ghcr.io/<owner>/sec-annual-reports:latest`, `build: .`, `ports: ["8000:8000"]`, `volumes: ["./data:/app/data"]`, `environment: SEC_IDENTITY: "Your Name your.email@example.com"`, `TZ: Europe/Amsterdam`, `RUN_TIME: "07:00"`, `restart: unless-stopped`, healthcheck `python -c "urllib.request.urlopen('http://localhost:8000/health')"` every 60s.

- [ ] **Step 1:** `docker compose build` -> success. **Step 2:** `docker compose up -d`, then `curl -s localhost:8000/health` -> JSON with `status`; `./data/reports.db` exists. **Step 3:** `docker compose down`. **Step 4:** Commit `feat: docker image and compose`.

### Task 9: Backfill seed DB

**Files:** Create `scripts/backfill.py`, `seed/reports.db`

`scripts/backfill.py --out seed/reports.db`: `run_update(connect(out), EdgarClient(identity), date.today(), full=True)`; prints counts per ticker and per `fy_source`. Identity from `SEC_IDENTITY` env.

- [ ] **Step 1:** Run once (live, ~13 requests). Expected: 110 rows (or more if a new 10-K landed), `unknown` only for WMT 2009-04-01 filing; print the per-source table. **Step 2:** Rebuild the image so `/app/seed/reports.db` is the backfill. **Step 3:** Commit `feat: 20-year backfill seed`.

### Task 10: Tests + CI/CD

**Files:** Create `.github/dependabot.yml`, `.github/workflows/deploy.yml`

- Dependabot: copy of `../vps-fastapi/.github/dependabot.yml` (uv at `/`).
- Workflow: copy of `../vps-fastapi/.github/workflows/deploy.yml` with: test step `uv run pytest -v` (no env secrets), build tag `ghcr.io/${{ github.repository_owner }}/sec-annual-reports:latest`, **no `deploy` job**.

- [ ] **Step 1:** `uv run pytest -q` full suite PASS locally. **Step 2:** `gh repo create <name> --public --source . --push` (confirm name with user first). **Step 3:** Push to a feature branch, open PR; workflow `test` job green. **Step 4:** After merge, `build` job pushes image; set GHCR package visibility public (`gh api` or UI; user confirms). **Step 5:** Commit `ci: tests, dependabot automerge, ghcr build`.

### Task 11: Backfill validation (ship gate)

**Files:** Create `seed/validation.csv`, `scripts/apply_validation.py`, `docs/validation.md`; modify `seed/reports.db`

- Dispatch one validation agent per ticker (6, in parallel). Each gets its rows (`accession_no, form, filing_date, period_of_report, fiscal_year, fy_source, url`) and checks each filing's cover page on sec.gov (fiscal year end date, "fiscal year ended ...", company's own fiscal year naming in the document). Output rows for `seed/validation.csv`: `accession_no, fiscal_year, period_of_report, status (confirmed|corrected), evidence` (quote from the cover page).
- `scripts/apply_validation.py seed/validation.csv seed/reports.db`: for each line, set `fiscal_year`, `period_of_report`, `fy_source='verified'`, `note=evidence`; fails if any accession is unknown or any row in the DB stays not `verified`.
- Test `tests/test_apply_validation.py`: `test_apply_sets_verified`, `test_unknown_accession_fails`, `test_incomplete_coverage_fails`.

- [ ] **Step 1:** Tests FAIL -> implement script -> PASS. **Step 2:** Run agents; review every `corrected` line (expected at least WMT 2009 period date). **Step 3:** Apply; `SELECT fy_source, count(*)` shows only `verified`. **Step 4:** `docs/validation.md`: counts and every correction. **Step 5:** Commit `data: validated backfill`.

### Task 12: README and wrap-up

- README: what it is, `docker compose up -d` quickstart (set `SEC_IDENTITY`, change host mount), endpoints with `curl` examples, data notes (XOM CIK change, WMT XBRL labels, validation), dev commands.
- [ ] **Step 1:** Write README. **Step 2:** Full suite + `docker compose up` check once more. **Step 3:** Commit, push, PR ready for review.
