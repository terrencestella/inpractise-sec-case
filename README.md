# SEC annual reports tracker

Keeps a SQLite table of every original annual report (10-K, 10-KT, 20-F, 40-F; no amendments) filed in the last 20 years by AAPL, JPM, XOM, SAP, WMT and CVNA, with the fiscal year each covers (the company's own label). Refreshes every morning; reruns are idempotent.

## Quickstart

```bash
git clone https://github.com/terrencestella/inpractise-sec-case && cd inpractise-sec-case
# edit docker-compose.yml: SEC_IDENTITY (your name + email, required by SEC), optionally TZ, RUN_TIME and the host side of the volume
docker compose up -d
curl localhost:8000/health
```

The image ships a validated 20-year backfill (`seed/reports.db`); on first start it is copied to the mounted `./data/reports.db`. An existing DB there is never overwritten.

| env | default | meaning |
|---|---|---|
| `SEC_IDENTITY` | placeholder | User-Agent for SEC requests |
| `TZ` | `Europe/Amsterdam` | timezone of the schedule |
| `RUN_TIME` | `07:00` | daily run time (HH:MM) |

## API

```bash
curl "localhost:8000/reports?ticker=WMT&fiscal_year=2014"   # list reports (filters optional)
curl localhost:8000/coverage                                # fiscal years per ticker, gaps, overdue flag
curl localhost:8000/health                                  # last run, auto-added CIKs, overdue tickers
curl -X POST localhost:8000/refresh                         # run the update now (409 if one is running)
```

## How it works
- Filings: edgartools `Company(cik).get_filings(...)`; fiscal years from the company's XBRL facts (`fiscal_period == "FY"`) per accession.
- XBRL labels are trusted only if they fit the company's pattern (fiscal year minus period-end year, per period-end month); otherwise, and for pre-XBRL filings, the learned rule applies (`fy_source = inferred`). Unparseable periods stay `unknown`.
- Upsert on accession number: reruns change nothing; `inferred`/`unknown` upgrade to `xbrl`; `verified` rows are never touched.
- Ticker drift: tickers are re-resolved daily against SEC's ticker map; a new CIK is added and tracked alongside the old one (XOM -> CIK 2115436 already). `/coverage` flags tickers with no report period in the last ~13 months.
- On startup, a run is triggered if the last successful run is older than 24h.

See `docs/validation.md` for the backfill validation and data findings, and `docs/superpowers/` for design and plan.

## Development

```bash
uv sync
uv run pytest                     # offline, fixtures only
SEC_IDENTITY="Name email" uv run python scripts/backfill.py --out seed/reports.db
uv run python scripts/apply_validation.py seed/validation.csv seed/reports.db
```

CI (`.github/workflows/deploy.yml`): tests on every push/PR, Dependabot minor/patch auto-merge after green tests, image pushed to `ghcr.io/terrencestella/sec-annual-reports` on `main`.
