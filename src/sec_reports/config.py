"""Settings from env vars and project-wide constants."""

import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

FORMS = ["10-K", "10-KT", "20-F", "40-F"]
SEED_COMPANIES: dict[str, list[int]] = {
    "AAPL": [320193],
    "JPM": [19617],
    "XOM": [34088],
    "SAP": [1000184],
    "WMT": [104169],
    "CVNA": [1690820],
}
DB_PATH = Path("/app/data/reports.db")
SEED_PATH = Path("/app/seed/reports.db")
YEARS_BACK = 20
OVERDUE_DAYS = 395

_RUN_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class Settings(BaseSettings):
    sec_identity: str
    tz: str = "Europe/Amsterdam"
    run_time: str = "07:00"

    @field_validator("run_time")
    @classmethod
    def _check_run_time(cls, v: str) -> str:
        if not _RUN_TIME.match(v):
            raise ValueError(f"RUN_TIME must be HH:MM (24h), got {v!r}")
        return v

    @property
    def run_hour_minute(self) -> tuple[int, int]:
        h, m = self.run_time.split(":")
        return int(h), int(m)
