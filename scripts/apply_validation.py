"""Apply validated fiscal years to the seed DB and mark rows verified.

Usage: uv run python scripts/apply_validation.py seed/validation.csv seed/reports.db
CSV columns: accession_no, fiscal_year, period_of_report, status (confirmed|corrected), evidence
Fails if a CSV accession is not in the DB, or if any DB row is left unverified.
"""

import csv
import sqlite3
import sys
from pathlib import Path


class ValidationError(Exception):
    pass


def apply_validation(csv_path: Path, db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    with open(csv_path, newline="") as f:
        lines = list(csv.DictReader(f))
    known = {r[0] for r in conn.execute("SELECT accession_no FROM annual_reports")}
    unknown = [ln["accession_no"] for ln in lines if ln["accession_no"] not in known]
    if unknown:
        raise ValidationError(f"accessions not in DB: {unknown}")
    with conn:
        for ln in lines:
            conn.execute(
                "UPDATE annual_reports SET fiscal_year = ?, period_of_report = ?, fy_source = 'verified', note = ? "
                "WHERE accession_no = ?",
                (int(ln["fiscal_year"]), ln["period_of_report"], f"{ln['status']}: {ln['evidence']}", ln["accession_no"]),
            )
    left = [r[0] for r in conn.execute("SELECT accession_no FROM annual_reports WHERE fy_source != 'verified'")]
    conn.close()
    if left:
        raise ValidationError(f"rows not verified: {left}")
    return len(lines)


if __name__ == "__main__":
    print(f"verified {apply_validation(Path(sys.argv[1]), Path(sys.argv[2]))} rows")
