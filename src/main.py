"""Application entrypoint: scheduler + live dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from src.config import get_settings
from src.logging_setup import setup_logging
from src.pipeline import get_pipeline
from src.execution.instance_lock import InstanceLock


def _build_scheduler(pipeline) -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=settings.tz)
    from src.analysis.knowledge_base import run_knowledge_job
    scheduler.add_job(run_knowledge_job, "interval", hours=1,
                      next_run_time=datetime.now(timezone.utc), id="knowledge_base",
                      max_instances=1, coalesce=True)
    from src.analysis.strategy_lab_job import run_lab_job
    scheduler.add_job(run_lab_job, "interval", hours=6,
                      next_run_time=datetime.now(timezone.utc), id="strategy_lab",
                      max_instances=1, coalesce=True)

    def minute_job() -> None:
        now = datetime.now(timezone.utc)
        tfs = ["M1", "M5", "H1"]
        if now.minute == 0:
            tfs.append("D1")
        pipeline.run_cycle(tuple(tfs))  # type: ignore[arg-type]

    def quote_job() -> None:
        try:
            with pipeline._lock:
                quotes = pipeline.fetcher.fetch_quotes(pipeline.settings.symbols)
                pipeline._quotes = {q.symbol: q for q in quotes}
                account = pipeline.broker.account_summary()
                pipeline._account = account
                pipeline._sync_open_trades(account)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Quote refresh failed: {}", exc)

    def morning_job() -> None:
        try:
            pipeline.send_morning_brief()
        except Exception:
            logger.exception("Morning EUR/USD brief failed")

    def recap_job() -> None:
        try:
            pipeline.send_night_recap()
        except Exception:
            logger.exception("Night EUR/USD recap failed")

    def news_job() -> None:
        try:
            pipeline.run_news_scan(force=True, deep=True)
        except Exception:
            logger.exception("EUR/USD 05:00 news scan failed")

    def pulse_job() -> None:
        try:
            pipeline.send_tape_pulse()
        except Exception:
            logger.exception("Tape pulse failed")

    def intel_job() -> None:
        try:
            pipeline.run_intel(force_slack=True)
        except Exception:
            logger.exception("EUR/USD intel cycle failed")

    def history_job() -> None:
        try:
            pipeline.kick_history_study(force=False)
        except Exception:
            logger.exception("Scheduled history study failed")

    scheduler.add_job(
        minute_job,
        "interval",
        seconds=max(30, settings.fetch_interval_seconds),
        id="pipeline_cycle",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        quote_job,
        "interval",
        seconds=15,
        id="quote_refresh",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        pulse_job,
        "interval",
        minutes=max(5, settings.slack_pulse_minutes),
        id="tape_pulse",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        intel_job,
        "interval",
        minutes=max(10, settings.intel_interval_minutes),
        id="eurusd_intel",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        history_job,
        "interval",
        hours=6,
        id="history_study",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        morning_job,
        "cron",
        hour=settings.briefing_hour,
        minute=settings.briefing_minute,
        id="morning_brief",
        timezone="UTC",
        day_of_week="mon-fri",
    )
    scheduler.add_job(
        recap_job,
        "cron",
        hour=settings.recap_hour,
        minute=settings.recap_minute,
        id="night_recap",
        timezone="UTC",
        day_of_week="mon-fri",
    )
    scheduler.add_job(
        news_job,
        "cron",
        hour=settings.news_scan_hour,
        minute=settings.news_scan_minute,
        id="eurusd_news_scan",
        timezone="UTC",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Forex Sentinel starts with new entries paused.")
    parser.add_argument("--trade", action="store_true", help="Explicitly arm practice entries after reconciliation")
    args = parser.parse_args()
    settings = get_settings()
    identity = settings.oanda_environment + ":" + get_pipeline().broker.account_id
    with InstanceLock(identity):
        _run(arm=args.trade)


def _run(*, arm: bool = False) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Forex Sentinel on :{}", settings.dashboard_port)
    pipeline = get_pipeline()
    pipeline.startup()
    if arm:
        pipeline.set_trading(True)
    scheduler = _build_scheduler(pipeline)
    scheduler.add_job(pipeline.run_startup_tasks, "date", id="startup_tasks",
                      max_instances=1, misfire_grace_time=60)
    scheduler.add_job(pipeline.refresh_documentation, "interval", seconds=60,
                      next_run_time=datetime.now(timezone.utc), id="documentation",
                      max_instances=1, coalesce=True)
    scheduler.start()
    try:
        uvicorn.run(
            "src.dashboard.app:app",
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            log_level=settings.log_level.lower(),
            reload=False,
        )
    finally:
        scheduler.shutdown(wait=False)
        pipeline.shutdown()


if __name__ == "__main__":
    main()
