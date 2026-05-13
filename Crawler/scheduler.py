"""
scheduler.py
------------
Runs the Daraz crawler automatically every day at a configured time
(default 02:30 NPT) and stops itself on PROJECT_END_DATE (2026-07-30).

Robustness features:
  ✅ Fires 1 min after startup in TEST_MODE for quick verification
  ✅ Auto-starts MongoDB via Homebrew before each crawl
  ✅ Verifies MongoDB is actually reachable before crawling
  ✅ Retries a failed crawl once after 5 minutes (same night)
  ✅ Logs a clear FAILED/SUCCEEDED banner after every run
  ✅ misfire_grace_time=3600 — fires even if Mac was asleep at crawl time
  ✅ coalesce=True — missed runs fire only once, not repeatedly
  ✅ max_instances=1 — never runs two crawls simultaneously
  ✅ Auto-shuts down cleanly on PROJECT_END_DATE
  ✅ Handles KeyboardInterrupt and SystemExit gracefully

Nepal Standard Time is UTC+5:45, handled via 'Asia/Kathmandu' timezone.

TEST MODE: Add TEST_MODE=true to your .env to fire the job 1 minute
after startup instead of waiting for 02:30 NPT. Remove when done testing.
"""

import logging
import os
import socket
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

# ── Logging setup ───────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
log_file  = os.getenv("LOG_FILE",  "logs/crawler.log")
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("sptdas.scheduler")

# ── Project config ──────────────────────────────────────────────────────────────
PROJECT_END_DATE   = date.fromisoformat(os.getenv("PROJECT_END_DATE", "2026-07-30"))
CRAWL_HOUR         = int(os.getenv("CRAWL_HOUR",   "2"))
CRAWL_MINUTE       = int(os.getenv("CRAWL_MINUTE", "30"))
TIMEZONE           = "Asia/Kathmandu"  # NPT UTC+5:45
RETRY_WAIT_SECONDS = 300               # 5 min wait before retry on failure
TEST_MODE          = os.getenv("TEST_MODE", "false").lower() == "true"


# ── MongoDB health check ────────────────────────────────────────────────────────

def ensure_mongodb() -> bool:
    """
    Start MongoDB via Homebrew (safe to call if already running).
    Then verify it's actually reachable via a socket connection.
    Returns True if MongoDB is up, False if it can't be confirmed.
    """
    logger.info("Ensuring MongoDB is running...")
    result = subprocess.run(
        ["brew", "services", "start", "mongodb-community"],
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    logger.info(f"brew services: {output or 'no output'}")

    # Give MongoDB up to 15 seconds to be ready
    for attempt in range(1, 6):
        try:
            sock = socket.create_connection(("localhost", 27017), timeout=3)
            sock.close()
            logger.info("✓ MongoDB is reachable on localhost:27017")
            return True
        except (OSError, ConnectionRefusedError):
            logger.warning(f"  MongoDB not ready yet (attempt {attempt}/5) — waiting 3s...")
            time.sleep(3)

    logger.error("✗ MongoDB is NOT reachable after 15s — crawl will likely fail.")
    return False


# ── Retry wrapper ───────────────────────────────────────────────────────────────

def _run_with_retry(run_crawl_fn) -> bool:
    """
    Call run_crawl_fn(). If it fails or raises, wait RETRY_WAIT_SECONDS
    and try exactly once more. Returns True if either attempt succeeds.
    """
    for attempt in range(1, 3):
        try:
            logger.info(f"Crawl attempt {attempt}/2...")
            if run_crawl_fn():
                return True
            logger.warning(f"Attempt {attempt} returned False.")
        except Exception as e:
            logger.error(f"Attempt {attempt} raised exception: {e}", exc_info=True)

        if attempt < 2:
            logger.info(f"Waiting {RETRY_WAIT_SECONDS}s before retry...")
            time.sleep(RETRY_WAIT_SECONDS)

    return False


# ── Main job ────────────────────────────────────────────────────────────────────

def job_with_guard(scheduler: BlockingScheduler):
    """
    Runs once per day at the configured time.
      1. Check project end date — shut down if past it
      2. Ensure MongoDB is up and reachable
      3. Run the crawl with one retry on failure
      4. Print a clear SUCCESS / FAILURE banner
    """
    today = date.today()

    # End-date guard
    if today > PROJECT_END_DATE:
        logger.info(
            f"Project end date {PROJECT_END_DATE} reached. "
            "Shutting down scheduler — no more crawls."
        )
        scheduler.shutdown(wait=False)
        return

    days_remaining = (PROJECT_END_DATE - today).days
    logger.info("=" * 60)
    logger.info(f"Daily crawl triggered — {today.isoformat()} ({days_remaining} days remaining)")
    logger.info("=" * 60)

    # Ensure MongoDB
    ensure_mongodb()

    # Run crawl with retry
    from orchestrator import run_crawl
    success = _run_with_retry(run_crawl)

    # Final banner
    if success:
        logger.info("=" * 60)
        logger.info(f"✓  CRAWL SUCCEEDED — {today.isoformat()}")
        logger.info("=" * 60)
    else:
        logger.error("=" * 60)
        logger.error(f"✗  CRAWL FAILED (both attempts) — {today.isoformat()}")
        logger.error("    Check logs/crawler.log for details.")
        logger.error("    Any products scraped before the failure ARE saved in MongoDB.")
        logger.error("=" * 60)


# ── Entry point ─────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("SPTDAS Crawler Scheduler starting up")

    if TEST_MODE:
        fire_time = datetime.now() + timedelta(minutes=1)
        logger.info(f"TEST MODE  — firing at {fire_time.strftime('%H:%M:%S')} (1 min from now)")
    else:
        logger.info(f"Scheduled  — {CRAWL_HOUR:02d}:{CRAWL_MINUTE:02d} NPT ({TIMEZONE})")

    logger.info(f"Project ends  : {PROJECT_END_DATE}")
    logger.info(f"Days remaining: {max(0, (PROJECT_END_DATE - date.today()).days)}")
    logger.info(f"Retry on fail : {RETRY_WAIT_SECONDS}s then 1 retry")
    logger.info("=" * 60)

    if date.today() > PROJECT_END_DATE:
        logger.warning("Project end date has already passed. Exiting.")
        sys.exit(0)

    scheduler = BlockingScheduler(timezone=TIMEZONE)

    if TEST_MODE:
        fire_time = datetime.now() + timedelta(minutes=1)
        trigger = CronTrigger(
            hour=fire_time.hour,
            minute=fire_time.minute,
            timezone=TIMEZONE,
            end_date=datetime.combine(PROJECT_END_DATE, datetime.min.time()),
        )
    else:
        trigger = CronTrigger(
            hour=CRAWL_HOUR,
            minute=CRAWL_MINUTE,
            timezone=TIMEZONE,
            end_date=datetime.combine(PROJECT_END_DATE, datetime.min.time()),
        )

    scheduler.add_job(
        func=job_with_guard,
        trigger=trigger,
        args=[scheduler],
        id="daily_daraz_crawl",
        name="Daily Daraz NP price crawl",
        misfire_grace_time=3600,  # Fire even if up to 1h late
        coalesce=True,            # Only fire once for multiple missed runs
        max_instances=1,          # Never overlap two crawls
    )

    logger.info("Scheduler is running. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user.")


if __name__ == "__main__":
    main()