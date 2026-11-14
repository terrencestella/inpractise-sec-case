"""The only module that talks to SEC / edgartools."""

import logging
import os
from datetime import date

import httpx
import pandas as pd

from sec_reports.config import FORMS

log = logging.getLogger(__name__)

FILING_COLUMNS = ["accession_number", "form", "filing_date", "reportDate", "primaryDocument"]
FACT_COLUMNS = ["accession", "fiscal_year", "fiscal_period", "period_end", "form_type"]
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"


class EdgarClient:
    def __init__(self, identity: str):
        os.environ.setdefault("EDGAR_CACHE_DIR", "/app/data/.edgar_cache")
        from edgar import set_identity

        set_identity(identity)
        self.identity = identity

    def fetch_filings(self, cik: int, since: date, full: bool) -> pd.DataFrame:
        from edgar import Company

        filings = Company(cik).get_filings(
            form=FORMS,
            amendments=False,
            filing_date=f"{since}:",
            trigger_full_load=full,
        )
        df = filings.to_pandas()
        if df is None or df.empty:
            return pd.DataFrame(columns=FILING_COLUMNS)
        return df[FILING_COLUMNS].reset_index(drop=True)

    def fetch_fy_facts(self, cik: int) -> pd.DataFrame:
        from edgar import Company
        from edgar.entity.entity_facts import CompanyFactsNotFoundError

        empty = pd.DataFrame(columns=FACT_COLUMNS)
        try:
            facts = Company(cik).get_facts()
        except CompanyFactsNotFoundError:
            return empty
        if facts is None:
            return empty
        df = facts.to_dataframe(include_metadata=True, pit_mode=True)
        if df is None or df.empty:
            return empty
        df = df[df["fiscal_period"] == "FY"][FACT_COLUMNS]
        return df.drop_duplicates(["accession", "fiscal_year"]).reset_index(drop=True)

    def resolve_tickers(self, tickers: list[str]) -> dict[str, tuple[int, str]]:
        resp = httpx.get(TICKER_MAP_URL, headers={"User-Agent": self.identity}, timeout=30)
        resp.raise_for_status()
        wanted = {t.upper() for t in tickers}
        out: dict[str, tuple[int, str]] = {}
        for entry in resp.json().values():
            t = str(entry["ticker"]).upper()
            if t in wanted:
                out[t] = (int(entry["cik_str"]), entry["title"])
        return out
