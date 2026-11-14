import csv
import importlib.util
from pathlib import Path

import pytest

from sec_reports.db import connect, upsert_reports
from sec_reports.fiscal import ReportRow

spec = importlib.util.spec_from_file_location(
    "apply_validation", Path(__file__).parents[1] / "scripts" / "apply_validation.py"
)
av = importlib.util.module_from_spec(spec)
spec.loader.exec_module(av)

FIELDS = ["accession_no", "fiscal_year", "period_of_report", "status", "evidence"]


def _db(tmp_path, accessions):
    db = tmp_path / "r.db"
    conn = connect(db)
    upsert_reports(conn, [
        ReportRow(a, "WMT", 104169, "10-K", "2009-04-01", "2009-04-01", None, "unknown", "u") for a in accessions
    ])
    conn.close()
    return db


def _csv(tmp_path, lines):
    p = tmp_path / "v.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(lines)
    return p


LINE = {"accession_no": "A1", "fiscal_year": "2009", "period_of_report": "2009-01-31",
        "status": "corrected", "evidence": "For the fiscal year ended January 31, 2009"}


def test_apply_sets_verified(tmp_path):
    db = _db(tmp_path, ["A1"])
    assert av.apply_validation(_csv(tmp_path, [LINE]), db) == 1
    row = connect(db).execute("SELECT * FROM annual_reports").fetchone()
    assert (row["fiscal_year"], row["period_of_report"], row["fy_source"]) == (2009, "2009-01-31", "verified")


def test_unknown_accession_fails(tmp_path):
    db = _db(tmp_path, ["A1"])
    with pytest.raises(av.ValidationError):
        av.apply_validation(_csv(tmp_path, [LINE, {**LINE, "accession_no": "ZZ"}]), db)


def test_incomplete_coverage_fails(tmp_path):
    db = _db(tmp_path, ["A1", "A2"])
    with pytest.raises(av.ValidationError):
        av.apply_validation(_csv(tmp_path, [LINE]), db)
