"""Turn EDGAR filings + XBRL facts into report rows with the company's fiscal year."""

from dataclasses import dataclass


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
