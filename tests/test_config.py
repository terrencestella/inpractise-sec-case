import pytest
from pydantic import ValidationError

from sec_reports.config import Settings


def test_run_time_parsed():
    assert Settings(sec_identity="x", run_time="07:30").run_hour_minute == (7, 30)


@pytest.mark.parametrize("bad", ["7am", "25:00", "7:00", "07:60"])
def test_run_time_invalid(bad):
    with pytest.raises(ValidationError):
        Settings(sec_identity="x", run_time=bad)


def test_sec_identity_required(monkeypatch):
    monkeypatch.delenv("SEC_IDENTITY", raising=False)
    with pytest.raises(ValidationError):
        Settings()
