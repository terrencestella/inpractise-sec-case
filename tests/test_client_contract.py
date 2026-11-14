import inspect

import pytest

from conftest import FakeClient
from sec_reports.edgar_client import EdgarClient


@pytest.mark.parametrize("name", ["fetch_filings", "fetch_fy_facts", "resolve_tickers"])
def test_fake_matches_real_signature(name):
    assert inspect.signature(getattr(FakeClient, name)) == inspect.signature(
        getattr(EdgarClient, name)
    )


def test_fake_defaults(fake_client):
    assert fake_client.resolve_tickers(["XOM", "AAPL"]) == {
        "XOM": (2115436, "ExxonMobil Holdings Corp"),
        "AAPL": (320193, "AAPL"),
    }
    assert fake_client.fetch_filings(2115436, None, False).empty
    assert list(fake_client.fetch_fy_facts(2115436).columns)[0] == "accession"
    assert len(fake_client.fetch_filings(320193, None, True)) == 21


def test_fake_fail_ciks():
    with pytest.raises(RuntimeError):
        FakeClient(fail_ciks={19617}).fetch_filings(19617, None, False)
