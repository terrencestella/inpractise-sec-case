"""Turn EDGAR filings + XBRL facts into report rows with the company's fiscal year."""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from sec_reports.config import FORMS

log = logging.getLogger(__name__)


@dataclass
class ReportRow:
    accession_no: str
    ticker: str
    cik: int
    form: str
    filing_date: str
    period_of_report: str | None
    fiscal_year: int | None
    fy_source: str  # xbrl | inferred | verified | unknown
    url: str


def filing_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def normalize_period(d: date) -> tuple[int, int]:
    """(year, month) of the fiscal period end; days 1-7 roll back (52/53-week years)."""
    if d.day <= 7:
        d = d.replace(day=1) - timedelta(days=1)
    return d.year, d.month


def learn_offsets(pairs: list[tuple[date, int]]) -> dict[int, int]:
    """Per period-end month, the majority of fiscal_year - normalized year."""
    by_month: dict[int, Counter] = {}
    for d, fy in pairs:
        year, month = normalize_period(d)
        by_month.setdefault(month, Counter())[fy - year] += 1
    return {m: c.most_common(1)[0][0] for m, c in by_month.items()}


def _parse_date(value) -> date | None:
    if value is None or pd.isna(value):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_rows(
    ticker: str, cik: int, filings: pd.DataFrame, fy_facts: pd.DataFrame
) -> list[ReportRow]:
    filings = filings[filings["form"].isin(FORMS)]
    xbrl: dict[str, int] = {}
    if len(fy_facts):
        xbrl = {
            str(acc): int(fy)
            for acc, fy in fy_facts.groupby("accession")["fiscal_year"].first().items()
        }
    periods = {
        acc: _parse_date(rd) for acc, rd in zip(filings["accession_number"], filings["reportDate"])
    }
    offsets = learn_offsets(
        [(periods[a], xbrl[a]) for a in periods if periods[a] is not None and a in xbrl]
    )

    rows = []
    for rec in filings.itertuples(index=False):
        acc = rec.accession_number
        period = periods[acc]
        fy, source = None, "unknown"
        if period is None:
            log.warning("%s %s: missing or unparseable reportDate, fiscal_year left NULL", ticker, acc)
        else:
            year, month = normalize_period(period)
            if month not in offsets:
                log.warning(
                    "%s %s: no fiscal year rule for period-end month %d, fiscal_year left NULL",
                    ticker, acc, month,
                )
            else:
                fy = year + offsets[month]
                source = "xbrl" if xbrl.get(acc) == fy else "inferred"
                if acc in xbrl and source == "inferred":
                    log.warning(
                        "%s %s: XBRL fiscal_year %d differs from rule %d, using rule",
                        ticker, acc, xbrl[acc], fy,
                    )
        rows.append(
            ReportRow(
                accession_no=acc,
                ticker=ticker,
                cik=cik,
                form=rec.form,
                filing_date=str(rec.filing_date)[:10],
                period_of_report=period.isoformat() if period else None,
                fiscal_year=fy,
                fy_source=source,
                url=filing_url(cik, acc),
            )
        )
    return rows
