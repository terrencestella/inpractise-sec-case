from datetime import date

from sec_reports import job
from sec_reports.config import SEED_COMPANIES
from sec_reports.db import company_ciks, connect, last_success, list_reports
from sec_reports.job import run_update, run_update_locked, years_ago

from conftest import FakeClient

TODAY = date(2026, 11, 14)


def _conn(tmp_path):
    return connect(tmp_path / "t.db")


def test_first_run_counts(tmp_path, fake_client):
    conn = _conn(tmp_path)
    res = run_update(conn, fake_client, TODAY)
    assert res.status == "ok"
    assert res.new_rows == 110
    assert len(list_reports(conn, None, None)) == 110
    assert last_success(conn) is not None


def test_second_run_no_changes(tmp_path, fake_client):
    conn = _conn(tmp_path)
    run_update(conn, fake_client, TODAY)
    res = run_update(conn, fake_client, TODAY)
    assert res.new_rows == 0 and res.updated_rows == 0


def test_drift_adds_xom_holding_cik(tmp_path, fake_client):
    conn = _conn(tmp_path)
    res = run_update(conn, fake_client, TODAY)
    assert ("XOM", 2115436) in res.added_ciks
    assert company_ciks(conn)["XOM"] == [34088, 2115436]
    assert run_update(conn, fake_client, TODAY).added_ciks == []


def test_one_cik_failure_partial(tmp_path):
    conn = _conn(tmp_path)
    res = run_update(conn, FakeClient(fail_ciks={19617}), TODAY)
    assert res.status == "partial"
    assert len(res.errors) == 1 and "19617" in res.errors[0]
    tickers = {r["ticker"] for r in list_reports(conn, None, None)}
    assert tickers == set(SEED_COMPANIES) - {"JPM"}


def test_ticker_map_failure_not_fatal(tmp_path, fake_client):
    def boom(tickers):
        raise RuntimeError("map down")

    fake_client.resolve_tickers = boom
    conn = _conn(tmp_path)
    res = run_update(conn, fake_client, TODAY)
    assert res.status == "partial"
    assert res.new_rows == 110


def test_lock_blocks_second_run(tmp_path, fake_client):
    conn = _conn(tmp_path)
    assert job.RUN_LOCK.acquire(blocking=False)
    try:
        assert run_update_locked(conn, fake_client, TODAY) is None
    finally:
        job.RUN_LOCK.release()
    assert run_update_locked(conn, fake_client, TODAY).status == "ok"


def test_years_ago_leap_day():
    assert years_ago(date(2028, 2, 29), 20) == date(2008, 2, 29)
    assert years_ago(date(2024, 2, 29), 21) == date(2003, 2, 28)
