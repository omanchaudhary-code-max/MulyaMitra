"""
run_now.py
----------
Run a single crawl cycle immediately — useful for:
  - Testing your setup before the scheduler goes live
  - Manually triggering a re-crawl after fixing a bug
  - First-run to seed the database with initial data

Usage:
    python run_now.py                        # crawl all configured categories
    python run_now.py --categories laptops   # crawl only laptops
    python run_now.py --categories laptops smartphones --max 10
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.FileHandler("logs/crawler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

from orchestrator import run_crawl


def main():
    parser = argparse.ArgumentParser(description="Run SPTDAS crawler immediately")
    parser.add_argument(
        "--categories",
        nargs="*",
        help="Override categories from .env (space-separated)",
    )
    parser.add_argument(
        "--max",
        type=int,
        help="Override MAX_PRODUCTS_PER_CATEGORY from .env",
    )
    args = parser.parse_args()

    if args.categories:
        os.environ["CATEGORIES"] = ",".join(args.categories)
        print(f"Override categories: {args.categories}")

    if args.max:
        os.environ["MAX_PRODUCTS_PER_CATEGORY"] = str(args.max)
        print(f"Override max products: {args.max}")

    success = run_crawl()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
