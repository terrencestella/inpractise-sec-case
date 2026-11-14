from datetime import date
from pathlib import Path

import pandas as pd

from sec_reports.fiscal import build_rows, filing_url, learn_offsets, normalize_period

FIXTURES = Path(__file__).parent / "fixtures"
CIKS = {"AAPL": 320193, "WMT": 104169, "SAP": 1000184}


def rows_for(ticker, filings=None):
    if filings is None:
        filings = pd.read_csv(FIXTURES / f"{ticker}_filings.csv")
    facts = pd.read_csv(FIXTURES / f"{ticker}_fy_facts.csv")
    return build_rows(ticker, CIKS[ticker], filings, facts)


def by_period(rows):
    return {r.period_of_report: r for r in rows}


def test_normalize_period():
    assert normalize_period(date(2026, 9, 26)) == (2026, 9)
    assert normalize_period(date(2008, 10, 2)) == (2008, 9)
    assert normalize_period(date(2025, 1, 31)) == (2025, 1)
    assert normalize_period(date(2025, 1, 3)) == (2024, 12)


def test_learn_offsets_majority():
    pairs = [(date(2014, 1, 31), 2013)] * 2 + [(date(2015, 1, 31), 2015)] * 3
    assert learn_offsets(pairs) == {1: 0}


def test_aapl_rows():
    rows = rows_for("AAPL")
    assert len(rows) == 21
    p = by_period(rows)
    assert (p["2006-09-30"].fiscal_year, p["2006-09-30"].fy_source) == (2006, "inferred")
    assert (p["2025-09-27"].fiscal_year, p["2025-09-27"].fy_source) == (2025, "xbrl")
    assert p["2025-09-27"].accession_no == "0000320193-25-000079"
    assert p["2025-09-27"].url == filing_url(320193, "0000320193-25-000079")


def test_wmt_outliers_corrected():
    p = by_period(rows_for("WMT"))
    assert (p["2014-01-31"].fiscal_year, p["2014-01-31"].fy_source) == (2014, "inferred")
    assert (p["2025-01-31"].fiscal_year, p["2025-01-31"].fy_source) == (2025, "xbrl")


def test_wmt_bad_period_unknown():
    rows = rows_for("WMT")
    r = next(r for r in rows if r.accession_no == "0000104169-09-000006")
    assert r.fiscal_year is None
    assert r.fy_source == "unknown"


def test_missing_report_date_unknown():
    filings = pd.read_csv(FIXTURES / "AAPL_filings.csv")
    filings.loc[0, "reportDate"] = None
    r = rows_for("AAPL", filings)[0]
    assert (r.fiscal_year, r.fy_source, r.period_of_report) == (None, "unknown", None)


def test_sap_inferred_pre_2017():
    p = by_period(rows_for("SAP"))
    assert (p["2010-12-31"].fiscal_year, p["2010-12-31"].fy_source) == (2010, "inferred")
    assert (p["2024-12-31"].fiscal_year, p["2024-12-31"].fy_source) == (2024, "xbrl")


def test_amendment_dropped():
    filings = pd.read_csv(FIXTURES / "AAPL_filings.csv")
    extra = filings.iloc[[0]].copy()
    extra["form"] = "10-K/A"
    extra["accession_number"] = "0000000000-26-000001"
    rows = rows_for("AAPL", pd.concat([filings, extra], ignore_index=True))
    assert len(rows) == 21
    assert all(r.form != "10-K/A" for r in rows)


def test_url():
    assert filing_url(320193, "0000320193-25-000079") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm"
    )
