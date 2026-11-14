"""Build the seed DB with the last 20 years of annual reports (live SEC calls).

Usage: SEC_IDENTITY="Name email" uv run python scripts/backfill.py --out seed/reports.db
"""

import argparse
import logging
import os
from datetime import date
from pathlib import Path

from sec_reports.db import connect
from sec_reports.edgar_client import EdgarClient
from sec_reports.job import run_update


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("seed/reports.db"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    os.environ.setdefault("EDGAR_CACHE_DIR", str(Path(".edgar_cache").resolve()))

    conn = connect(args.out)
    result = run_update(conn, EdgarClient(os.environ["SEC_IDENTITY"]), date.today(), full=True)
    print(result)
    for row in conn.execute(
        "SELECT ticker, fy_source, count(*) n FROM annual_reports GROUP BY ticker, fy_source ORDER BY ticker"
    ):
        print(dict(row))


if __name__ == "__main__":
    main()
