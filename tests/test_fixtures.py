from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = {"AAPL": 21, "JPM": 20, "XOM": 20, "SAP": 20, "WMT": 20, "CVNA": 9}


@pytest.mark.parametrize("ticker,count", EXPECTED.items())
def test_fixture_counts(ticker, count):
    filings = pd.read_csv(FIXTURES / f"{ticker}_filings.csv")
    assert len(filings) == count
    facts = pd.read_csv(FIXTURES / f"{ticker}_fy_facts.csv")
    assert facts.groupby("accession")["fiscal_year"].nunique().max() == 1
