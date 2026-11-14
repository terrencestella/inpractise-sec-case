from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from sec_reports.config import SEED_COMPANIES

FIXTURES = Path(__file__).parent / "fixtures"
FILING_COLUMNS = ["accession_number", "form", "filing_date", "reportDate", "primaryDocument"]
FACT_COLUMNS = ["accession", "fiscal_year", "fiscal_period", "period_end", "form_type"]


class FakeClient:
    """Offline stand-in for EdgarClient, backed by tests/fixtures."""

    def __init__(
        self,
        tickers: dict[str, tuple[int, str]] | None = None,
        fail_ciks: set[int] = (),
    ):
        if tickers is None:
            tickers = {t: (ciks[0], t) for t, ciks in SEED_COMPANIES.items()}
            tickers["XOM"] = (2115436, "ExxonMobil Holdings Corp")
        self.tickers = tickers
        self.fail_ciks = set(fail_ciks)
        self.cik_to_ticker = {c: t for t, ciks in SEED_COMPANIES.items() for c in ciks}

    def _load(self, cik: int, suffix: str, columns: list[str]) -> pd.DataFrame:
        if cik in self.fail_ciks:
            raise RuntimeError(f"simulated failure for CIK {cik}")
        ticker = self.cik_to_ticker.get(cik)
        if ticker is None:
            return pd.DataFrame(columns=columns)
        return pd.read_csv(FIXTURES / f"{ticker}_{suffix}.csv")

    def fetch_filings(self, cik: int, since: date, full: bool) -> pd.DataFrame:
        return self._load(cik, "filings", FILING_COLUMNS)

    def fetch_fy_facts(self, cik: int) -> pd.DataFrame:
        return self._load(cik, "fy_facts", FACT_COLUMNS)

    def resolve_tickers(self, tickers: list[str]) -> dict[str, tuple[int, str]]:
        return {t: v for t, v in self.tickers.items() if t in tickers}


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()
