from fastapi.testclient import TestClient

from sec_reports import job
from sec_reports.config import SEED_COMPANIES, Settings
from sec_reports.db import connect, seed_companies
from sec_reports.main import create_app

from conftest import FakeClient


def _app(tmp_path, seed=None):
    return create_app(
        Settings(sec_identity="test@example.com"), FakeClient(),
        db_path=tmp_path / "data" / "reports.db",
        seed_path=seed or tmp_path / "none.db",
        start_scheduler=False,
    )


def test_refresh_then_reports(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        r = c.post("/refresh")
        assert r.status_code == 200 and r.json()["new_rows"] == 110
        rows = c.get("/reports", params={"ticker": "WMT", "fiscal_year": 2014}).json()
        assert len(rows) == 1 and rows[0]["period_of_report"] == "2014-01-31"


def test_refresh_conflict_409(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        assert job.RUN_LOCK.acquire(blocking=False)
        try:
            assert c.post("/refresh").status_code == 409
        finally:
            job.RUN_LOCK.release()


def test_health_shows_drift(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        c.post("/refresh")
        h = c.get("/health").json()
        assert {"ticker": "XOM", "cik": 2115436} in h["auto_added_ciks"]
        assert h["status"] == "ok" and h["last_run_status"] == "ok"
        assert h["last_success"] is not None
        assert isinstance(h["overdue_tickers"], list)


def test_health_before_any_run(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        h = c.get("/health").json()
        assert h["last_success"] is None and h["last_run_status"] is None


def test_coverage_shape(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        c.post("/refresh")
        cov = c.get("/coverage").json()
        assert {x["ticker"] for x in cov} == set(SEED_COMPANIES)
        assert {"ticker", "ciks", "fiscal_years", "missing_years", "latest_period",
                "overdue", "by_source"} <= set(cov[0])


def test_seed_copied_on_start(tmp_path):
    seed = tmp_path / "seed.db"
    conn = connect(seed)
    seed_companies(conn, {"ZZZ": [1]})
    conn.close()
    with TestClient(_app(tmp_path, seed)) as c:
        assert (tmp_path / "data" / "reports.db").exists()
        assert any(x["ticker"] == "ZZZ" for x in c.get("/coverage").json())
