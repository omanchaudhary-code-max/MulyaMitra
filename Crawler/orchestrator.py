"""
orchestrator.py
---------------
Runs a complete daily crawl cycle:
  1. Open the crawler
  2. For each configured category, crawl products
  3. Save each product to MongoDB IMMEDIATELY as it is scraped
     (so partial data is never lost even if the crawl crashes mid-category)
  4. Log the full result with per-category breakdown
  5. Close everything cleanly

Called by the scheduler (scheduler.py) or directly for one-off runs.
"""

import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

from daraz_crawler import DarazCrawler
from storage import SPTDASStorage

load_dotenv()

logger = logging.getLogger(__name__)


def run_crawl() -> bool:
    """
    Execute one full crawl cycle across all configured categories.

    Each product is saved to MongoDB immediately after scraping — so if the
    crawler crashes on product 35 of 50, products 1–34 are already in the DB.

    Returns True if at least one category completed without a fatal error,
    False only if MongoDB is unreachable or the whole run catastrophically fails.
    """

    # ── Config from .env ────────────────────────────────────────────────────────
    mongo_uri    = os.getenv("MONGO_URI",    "mongodb://localhost:27017")
    db_name      = os.getenv("MONGO_DB",     "daraz_db")
    delay_min    = int(os.getenv("DELAY_MIN",    "4"))
    delay_max    = int(os.getenv("DELAY_MAX",    "10"))
    max_per_cat  = int(os.getenv("MAX_PRODUCTS_PER_CATEGORY", "50"))

    categories_raw = os.getenv(
        "CATEGORIES",
        "laptops,smartphones,televisions,headphones,shoes-men",
    )
    categories = [c.strip() for c in categories_raw.split(",") if c.strip()]

    logger.info("=" * 60)
    logger.info(f"SPTDAS Crawl started at {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Categories : {categories}")
    logger.info(f"Max/cat    : {max_per_cat}")
    logger.info("=" * 60)

    # ── Connect to MongoDB ──────────────────────────────────────────────────────
    storage = SPTDASStorage(uri=mongo_uri, db_name=db_name)
    try:
        storage.connect()
    except Exception as e:
        logger.critical(f"Cannot connect to MongoDB: {e}")
        return False

    run_id = storage.start_crawl_run(categories)

    # Aggregate stats across all categories
    total_stats = {
        "total_products": 0,
        "total_new":      0,
        "total_updated":  0,
        "total_errors":   0,
    }

    # Per-category breakdown for the run log
    category_results = {}

    # ── Crawl ───────────────────────────────────────────────────────────────────
    try:
        with DarazCrawler(delay_min=delay_min, delay_max=delay_max) as crawler:

            for category in categories:
                logger.info(f"\n>>> Starting category: {category}")

                cat_stats = {"scraped": 0, "new": 0, "updated": 0, "errors": 0}

                # ── Immediate-save callback ─────────────────────────────────────
                # Called by the crawler right after each product is successfully
                # scraped. This means every product hits MongoDB before the next
                # product is even requested — no batch loss on crash.
                def make_save_callback(cat_name, c_stats):
                    def save_one(product: dict):
                        try:
                            result = storage.save_products([product], run_id)
                            c_stats["new"]     += result.get("new", 0)
                            c_stats["updated"] += result.get("updated", 0)
                            c_stats["errors"]  += result.get("errors", 0)
                            c_stats["scraped"] += 1
                            logger.debug(
                                f"  Saved {product.get('item_id')} "
                                f"({product.get('current_price')} NPR)"
                            )
                        except Exception as e:
                            logger.error(
                                f"  Immediate save failed for "
                                f"{product.get('url', '?')}: {e}"
                            )
                            c_stats["errors"] += 1
                    return save_one

                save_cb = make_save_callback(category, cat_stats)

                try:
                    products = crawler.crawl_category(
                        category,
                        max_products=max_per_cat,
                        save_callback=save_cb,   # ← immediate per-product save
                    )

                    if not products:
                        logger.warning(f"No products returned for: {category}")
                        storage.log_error(run_id, category, "", "Zero products returned")
                        cat_stats["errors"] += 1

                except Exception as e:
                    logger.error(f"Category {category} failed: {e}", exc_info=True)
                    storage.log_error(run_id, category, "", str(e))
                    cat_stats["errors"] += 1
                    # Continue to the next category — never abort the whole run

                finally:
                    # Record this category's result regardless of outcome
                    category_results[category] = cat_stats
                    total_stats["total_products"] += cat_stats["scraped"]
                    total_stats["total_new"]      += cat_stats["new"]
                    total_stats["total_updated"]  += cat_stats["updated"]
                    total_stats["total_errors"]   += cat_stats["errors"]

                    logger.info(
                        f"  Category summary — {category}: "
                        f"scraped={cat_stats['scraped']}, "
                        f"new={cat_stats['new']}, "
                        f"updated={cat_stats['updated']}, "
                        f"errors={cat_stats['errors']}"
                    )

        # ── Finish ──────────────────────────────────────────────────────────────
        storage.finish_crawl_run(run_id, total_stats)

        logger.info("\n" + "=" * 60)
        logger.info(f"Crawl complete. Overall stats: {total_stats}")
        logger.info("Per-category breakdown:")
        for cat, stats in category_results.items():
            status = "✓" if stats["errors"] == 0 else "⚠"
            logger.info(
                f"  {status} {cat:30s} scraped={stats['scraped']:3d}  "
                f"new={stats['new']:3d}  errors={stats['errors']:3d}"
            )
        logger.info("=" * 60 + "\n")

        return True

    except Exception as e:
        logger.critical(f"Crawl run failed catastrophically: {e}", exc_info=True)
        try:
            storage.fail_crawl_run(run_id, str(e))
        except Exception:
            pass
        return False

    finally:
        storage.close()