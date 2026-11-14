"""FastAPI app: endpoints plus the daily APScheduler job."""

import asyncio
import logging
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException

from sec_reports.config import DB_PATH, SEED_PATH, Settings
from sec_reports.db import connect, coverage, last_success, list_reports, seed_if_missing
from sec_reports.edgar_client import EdgarClient
from sec_reports.job import run_update_locked

log = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    client,
    db_path: Path = DB_PATH,
    seed_path: Path = SEED_PATH,
    start_scheduler: bool = True,
) -> FastAPI:
    tz = ZoneInfo(settings.tz)

    def today() -> date:
        return datetime.now(tz).date()

    def run_job():
        # Runs in a worker thread: own connection.
        with closing(connect(db_path)) as conn:
            return run_update_locked(conn, client, today())

    async def scheduled_run():
        try:
            res = await asyncio.to_thread(run_job)
            log.info("scheduled run: %s", res.status if res else "skipped (already running)")
        except Exception:
            log.exception("scheduled run crashed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if seed_path.exists() and seed_if_missing(seed_path, db_path):
            log.info("seeded %s from %s", db_path, seed_path)
        scheduler = None
        if start_scheduler:
            hour, minute = settings.run_hour_minute
            scheduler = AsyncIOScheduler(timezone=settings.tz)
            scheduler.add_job(
                scheduled_run, "cron", hour=hour, minute=minute,
                coalesce=True, misfire_grace_time=3600, id="daily",
            )
            with closing(connect(db_path)) as conn:
                last = last_success(conn)
            if last is None or datetime.now(timezone.utc) - last > timedelta(hours=24):
                log.info("catch-up run scheduled (last success: %s)", last)
                scheduler.add_job(scheduled_run, id="catchup")  # date trigger, runs now
            scheduler.start()
        try:
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)

    app = FastAPI(title="SEC annual reports", lifespan=lifespan)

    @app.get("/reports")
    def reports(ticker: str | None = None, fiscal_year: int | None = None):
        with closing(connect(db_path)) as conn:
            return list_reports(conn, ticker, fiscal_year)

    @app.post("/refresh")
    async def refresh():
        res = await asyncio.to_thread(run_job)
        if res is None:
            raise HTTPException(status_code=409, detail="update already running")
        return res

    @app.get("/coverage")
    def get_coverage():
        with closing(connect(db_path)) as conn:
            return coverage(conn, today())

    @app.get("/health")
    def health():
        with closing(connect(db_path)) as conn:
            last = last_success(conn)
            run = conn.execute(
                "SELECT status FROM runs WHERE status != 'running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            auto = [{"ticker": r["ticker"], "cik": r["cik"]} for r in conn.execute(
                "SELECT ticker, cik FROM companies WHERE source='auto' ORDER BY ticker, cik")]
            overdue = [c["ticker"] for c in coverage(conn, today()) if c["overdue"]]
        return {
            "status": "ok",
            "last_success": last.isoformat() if last else None,
            "last_run_status": run["status"] if run else None,
            "auto_added_ciks": auto,
            "overdue_tickers": overdue,
        }

    return app


def build_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    return create_app(settings, EdgarClient(settings.sec_identity))
