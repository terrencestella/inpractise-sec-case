"""One idempotent update run: resolve tickers, fetch, build rows, upsert."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import date

from sec_reports.config import SEED_COMPANIES, YEARS_BACK
from sec_reports.db import (
    add_company, company_ciks, finish_run, seed_companies, start_run, upsert_reports,
)
from sec_reports.fiscal import build_rows

log = logging.getLogger(__name__)

RUN_LOCK = threading.Lock()


@dataclass
class RunResult:
    status: str  # ok | partial | failed
    new_rows: int = 0
    updated_rows: int = 0
    added_ciks: list[tuple[str, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - years, day=28)


def _detect_drift(conn, client, result: RunResult) -> None:
    known = company_ciks(conn)
    try:
        resolved = client.resolve_tickers(list(known))
    except Exception as e:
        log.exception("ticker map lookup failed")
        result.errors.append(f"ticker map: {e}")
        return
    for ticker, (cik, name) in resolved.items():
        if cik not in known.get(ticker, []):
            add_company(conn, ticker, cik, name, "auto")
            result.added_ciks.append((ticker, cik))
            log.warning("identity drift: %s now maps to new CIK %s (%s)", ticker, cik, name)


def run_update(conn, client, today: date, full: bool = False) -> RunResult:
    result = RunResult(status="ok")
    run_id = start_run(conn)
    try:
        seed_companies(conn, SEED_COMPANIES)
        _detect_drift(conn, client, result)
        since = years_ago(today, YEARS_BACK)
        attempted = failed = 0
        for ticker, ciks in company_ciks(conn).items():
            for cik in ciks:
                attempted += 1
                try:
                    # A CIK without stored rows (no seed, or newly added by drift) needs its full history.
                    has_rows = conn.execute(
                        "SELECT 1 FROM annual_reports WHERE cik = ? LIMIT 1", (cik,)
                    ).fetchone()
                    filings = client.fetch_filings(cik, since, full or not has_rows)
                    facts = client.fetch_fy_facts(cik)
                    new, upd = upsert_reports(conn, build_rows(ticker, cik, filings, facts))
                    result.new_rows += new
                    result.updated_rows += upd
                except Exception as e:
                    failed += 1
                    log.exception("update failed for %s CIK %s", ticker, cik)
                    result.errors.append(f"{ticker} CIK {cik}: {e}")
        if failed and failed == attempted:
            result.status = "failed"
        elif result.errors:
            result.status = "partial"
    except Exception as e:
        log.exception("update run crashed")
        result.status = "failed"
        result.errors.append(str(e))
    finish_run(conn, run_id, result.status, result.new_rows, result.updated_rows,
               "; ".join(result.errors) or None)
    return result


def run_update_locked(conn, client, today: date, full: bool = False) -> RunResult | None:
    if not RUN_LOCK.acquire(blocking=False):
        return None
    try:
        return run_update(conn, client, today, full)
    finally:
        RUN_LOCK.release()
