"""SQLite storage: reports, companies, runs."""

import shutil
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from sec_reports.config import OVERDUE_DAYS
from sec_reports.fiscal import ReportRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS annual_reports (
    accession_no TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik INTEGER NOT NULL,
    form TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    period_of_report TEXT,
    fiscal_year INTEGER,
    fy_source TEXT NOT NULL,
    url TEXT NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_ticker_fy ON annual_reports(ticker, fiscal_year);
CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT NOT NULL,
    cik INTEGER NOT NULL,
    name TEXT,
    source TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (ticker, cik)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    new_rows INTEGER,
    updated_rows INTEGER,
    message TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def add_company(conn, ticker: str, cik: int, name: str | None, source: str = "auto") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO companies(ticker, cik, name, source, added_at) VALUES (?,?,?,?,?)",
        (ticker, cik, name, source, _now()),
    )
    conn.commit()


def seed_companies(conn, mapping: dict[str, list[int]]) -> None:
    for ticker, ciks in mapping.items():
        for cik in ciks:
            add_company(conn, ticker, cik, None, "seed")


def company_ciks(conn) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for r in conn.execute("SELECT ticker, cik FROM companies ORDER BY ticker, cik"):
        out.setdefault(r["ticker"], []).append(r["cik"])
    return out


_UPSERT = """
INSERT INTO annual_reports
    (accession_no, ticker, cik, form, filing_date, period_of_report,
     fiscal_year, fy_source, url, updated_at)
VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(accession_no) DO UPDATE SET
    period_of_report = excluded.period_of_report,
    fiscal_year = excluded.fiscal_year,
    fy_source = excluded.fy_source,
    updated_at = excluded.updated_at
WHERE annual_reports.fy_source IN ('inferred','unknown') AND excluded.fy_source = 'xbrl'
"""


def upsert_reports(conn, rows: list[ReportRow]) -> tuple[int, int]:
    new = updated = 0
    now = _now()
    with conn:
        for r in rows:
            existed = conn.execute(
                "SELECT 1 FROM annual_reports WHERE accession_no = ?", (r.accession_no,)
            ).fetchone()
            cur = conn.execute(
                _UPSERT,
                (r.accession_no, r.ticker, r.cik, r.form, r.filing_date,
                 r.period_of_report, r.fiscal_year, r.fy_source, r.url, now),
            )
            if cur.rowcount:
                if existed:
                    updated += 1
                else:
                    new += 1
    return new, updated


def start_run(conn) -> int:
    cur = conn.execute(
        "INSERT INTO runs(started_at, status) VALUES (?, 'running')", (_now(),)
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, status: str, new_rows: int, updated_rows: int,
               message: str | None) -> None:
    conn.execute(
        "UPDATE runs SET finished_at=?, status=?, new_rows=?, updated_rows=?, message=? WHERE id=?",
        (_now(), status, new_rows, updated_rows, message, run_id),
    )
    conn.commit()


def last_success(conn) -> datetime | None:
    r = conn.execute(
        "SELECT finished_at FROM runs WHERE status='ok' AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    return datetime.fromisoformat(r["finished_at"]) if r else None


def list_reports(conn, ticker: str | None, fiscal_year: int | None) -> list[dict]:
    sql, args = "SELECT * FROM annual_reports WHERE 1=1", []
    if ticker:
        sql += " AND ticker = ?"
        args.append(ticker.upper())
    if fiscal_year is not None:
        sql += " AND fiscal_year = ?"
        args.append(fiscal_year)
    sql += " ORDER BY ticker, filing_date DESC, accession_no"
    return [dict(r) for r in conn.execute(sql, args)]


def coverage(conn, today: date) -> list[dict]:
    ciks = company_ciks(conn)
    tickers = set(ciks) | {
        r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM annual_reports")
    }
    out = []
    for t in sorted(tickers):
        years = [r[0] for r in conn.execute(
            "SELECT DISTINCT fiscal_year FROM annual_reports "
            "WHERE ticker=? AND fiscal_year IS NOT NULL ORDER BY fiscal_year", (t,))]
        missing = (
            [y for y in range(years[0], years[-1] + 1) if y not in years] if years else []
        )
        latest = conn.execute(
            "SELECT MAX(period_of_report) FROM annual_reports WHERE ticker=?", (t,)
        ).fetchone()[0]
        overdue = (
            (today - date.fromisoformat(latest)).days > OVERDUE_DAYS if latest else True
        )
        by_source = {r["fy_source"]: r["n"] for r in conn.execute(
            "SELECT fy_source, COUNT(*) n FROM annual_reports WHERE ticker=? GROUP BY fy_source",
            (t,))}
        out.append({
            "ticker": t, "ciks": ciks.get(t, []), "fiscal_years": years,
            "missing_years": missing, "latest_period": latest,
            "overdue": overdue, "by_source": by_source,
        })
    return out


def seed_if_missing(seed: Path, target: Path) -> bool:
    target = Path(target)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(seed, target)
    return True
