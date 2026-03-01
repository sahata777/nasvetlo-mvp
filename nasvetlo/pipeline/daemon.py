"""Daemon scheduler for periodic pipeline runs."""

from __future__ import annotations

import signal
import sys
import time

from nasvetlo.config import AppConfig, get_config, load_config
from nasvetlo.db import init_db
from nasvetlo.logging_utils import get_logger, setup_logging
from nasvetlo.pipeline.run_once import run_pipeline
from nasvetlo.settings import get_settings

log = get_logger("pipeline.daemon")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info("Received signal %d, shutting down gracefully...", signum)
    _shutdown = True


def run_daemon() -> None:
    """Run the pipeline in a loop with configured interval."""
    settings = get_settings()
    setup_logging(settings.log_level)
    config = load_config(settings.nasvetlo_config)
    init_db()

    interval_seconds = config.schedule.scan_minutes * 60

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info(
        "Daemon started. Interval: %d min. Daily cap: %d.",
        config.schedule.scan_minutes,
        config.schedule.daily_cap,
    )

    while not _shutdown:
        try:
            # Reload config each cycle to pick up changes
            config = load_config(settings.nasvetlo_config)
            summary = run_pipeline(config, dry_run=False)
            log.info(
                "Pipeline run complete: ingested=%d, clustered=%d, drafts=%d, errors=%d",
                summary["articles_ingested"],
                summary["clusters_formed"],
                summary["drafts_created"],
                summary["errors"],
            )
        except Exception as e:
            log.error("Daemon cycle failed: %s", e, exc_info=True)

        # Sleep in small increments so we can respond to signals
        for _ in range(interval_seconds):
            if _shutdown:
                break
            time.sleep(1)

    log.info("Daemon stopped.")
