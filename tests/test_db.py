from datetime import date, timedelta

from sec_reports import db
from sec_reports.fiscal import ReportRow


def row(acc, fy, src="xbrl", period="2020-12-31", ticker="AAPL", cik=320193):
    return ReportRow(acc, ticker, cik, "10-K", "2021-02-01", period, fy, src, f"u/{acc}")


def conn_(tmp_path):
    return db.connect(tmp_path / "sub" / "r.db")


def test_upsert_idempotent(tmp_path):
    c = conn_(tmp_path)
    rows = [row("a1", 2020), row("a2", 2021, period="2021-12-31")]
    assert db.upsert_reports(c, rows) == (2, 0)
    assert db.upsert_reports(c, rows) == (0, 0)
    assert c.execute("select count(*) from annual_reports").fetchone()[0] == 2


def test_inferred_upgraded_to_xbrl(tmp_path):
    c = conn_(tmp_path)
    db.upsert_reports(c, [row("a1", 2019, "inferred")])
    assert db.upsert_reports(c, [row("a1", 2020, "xbrl")]) == (0, 1)
    r = db.list_reports(c, "AAPL", None)[0]
    assert (r["fiscal_year"], r["fy_source"]) == (2020, "xbrl")


def test_verified_untouched(tmp_path):
    c = conn_(tmp_path)
    db.upsert_reports(c, [row("a1", 2020, "verified")])
    assert db.upsert_reports(c, [row("a1", 2021, "xbrl")]) == (0, 0)
    r = db.list_reports(c, None, None)[0]
    assert (r["fiscal_year"], r["fy_source"]) == (2020, "verified")


def test_xbrl_not_downgraded(tmp_path):
    c = conn_(tmp_path)
    db.upsert_reports(c, [row("a1", 2020, "xbrl")])
    assert db.upsert_reports(c, [row("a1", 2019, "inferred")]) == (0, 0)
    assert db.list_reports(c, None, None)[0]["fiscal_year"] == 2020


def test_coverage_gaps_and_overdue(tmp_path):
    c = conn_(tmp_path)
    today = date(2026, 11, 14)
    old = (today - timedelta(days=400)).isoformat()
    db.seed_companies(c, {"AAPL": [320193]})
    db.upsert_reports(c, [row("a1", 2020, period="2020-12-31"), row("a2", 2022, period=old)])
    cov = {d["ticker"]: d for d in db.coverage(c, today)}["AAPL"]
    assert cov["missing_years"] == [2021]
    assert cov["fiscal_years"] == [2020, 2022]
    assert cov["ciks"] == [320193]
    assert cov["latest_period"] == old
    assert cov["overdue"] is True
    assert cov["by_source"] == {"xbrl": 2}


def test_seed_if_missing(tmp_path):
    seed = tmp_path / "seed.db"
    seed.write_bytes(b"seed-bytes")
    target = tmp_path / "data" / "r.db"
    assert db.seed_if_missing(seed, target) is True
    assert target.read_bytes() == b"seed-bytes"
    target.write_bytes(b"existing")
    assert db.seed_if_missing(seed, target) is False
    assert target.read_bytes() == b"existing"


def test_companies_and_runs(tmp_path):
    c = conn_(tmp_path)
    db.seed_companies(c, {"XOM": [34088]})
    db.seed_companies(c, {"XOM": [34088]})
    db.add_company(c, "XOM", 2115436, "Exxon", "auto")
    assert db.company_ciks(c) == {"XOM": [34088, 2115436]}
    assert db.last_success(c) is None
    rid = db.start_run(c)
    db.finish_run(c, rid, "ok", 1, 0, None)
    assert db.last_success(c) is not None
