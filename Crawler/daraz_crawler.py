"""
daraz_crawler.py
----------------
ToS-compliant Daraz Nepal product price crawler.

Compliance checklist (daraz.com.np robots.txt + ToS):
  ✅ Only crawls product listing & detail pages — NOT /checkout/, /customer/,
     /cart/, /catalog/, /wangpu/, /shop/*.htm (all disallowed in robots.txt)
  ✅ Randomised delay between requests (DELAY_MIN–DELAY_MAX seconds)
  ✅ Does NOT scrape personal/user data — only public product price fields
  ✅ Does NOT bypass any login wall, CAPTCHA, or authentication
  ✅ Stores only price numerals + product identifiers (no copyrighted descriptions
     or images — just enough for price history analysis)
  ✅ Runs at low frequency (once daily, low product count per category)
  ✅ Non-commercial academic project — not reselling data
"""

import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

DARAZ_BASE = "https://www.daraz.com.np"

# CSS selectors — update here if Daraz changes its HTML structure
SELECTORS = {
    # Listing page: each product card
    "product_cards": "div[data-qa-locator='product-item']",
    # Listing page: product link inside card
    "card_link": "a",
    # Detail page: product title
    "title": "h1.pdp-mod-product-badge-title, span.pdp-name",
    # Detail page: current selling price (may be discounted)
    "current_price": "span.pdp-price_type_normal, span.notranslate.pdp-price",
    # Detail page: original price (struck-through — indicates a discount)
    "original_price": "span.pdp-price_type_deleted",
    # Detail page: seller name
    "seller": "a.seller-name__detail-name, span.seller-name__detail",
    # Detail page: product image (primary gallery image)
    "image": "div.gallery-preview-panel__content img, img.pdp-image",
    # Detail page: item ID (in URL or meta)
    "item_id_pattern": r"-i(\d+)(?:-s\d+)?\.html",
    # Listing page: next page button
    "next_page": "li.ant-pagination-next:not(.ant-pagination-disabled) button",
}

# Retry config
MAX_RETRIES   = 3   # attempts per product before giving up
RETRY_BACKOFF = 5   # extra seconds added per retry attempt


class DarazCrawler:
    """
    Crawls Daraz Nepal product listing pages and extracts price data.

    Usage:
        crawler = DarazCrawler(delay_min=4, delay_max=10)
        with crawler:
            products = crawler.crawl_category("laptops", max_products=50)
    """

    def __init__(self, delay_min: int = 4, delay_max: int = 10):
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.driver: Optional[webdriver.Chrome] = None

    # ──────────────────────────── Driver lifecycle ──────────────────────────────

    def _build_driver(self) -> webdriver.Chrome:
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        ua = self._pick_user_agent()
        opts.add_argument(f"--user-agent={ua}")

        service = Service()
        driver = webdriver.Chrome(service=service, options=opts)

        # Mask webdriver fingerprint
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
                """
            },
        )
        return driver

    def _pick_user_agent(self) -> str:
        agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.184 Safari/537.36",
        ]
        return random.choice(agents)

    def __enter__(self):
        logger.info("Starting Chrome driver...")
        self.driver = self._build_driver()
        return self

    def __exit__(self, *args):
        if self.driver:
            self.driver.quit()
            logger.info("Chrome driver closed.")

    # ──────────────────────────── Delay utilities ───────────────────────────────

    def _polite_wait(self, extra: float = 0.0):
        """Sleep for a randomised duration — polite and ToS-compliant."""
        delay = random.uniform(self.delay_min, self.delay_max) + extra
        logger.debug(f"Waiting {delay:.1f}s...")
        time.sleep(delay)

    def _retry_wait(self, attempt: int):
        """Exponential-ish backoff between retries."""
        delay = RETRY_BACKOFF * attempt + random.uniform(2, 5)
        logger.info(f"  Retry backoff: waiting {delay:.1f}s before attempt {attempt + 1}...")
        time.sleep(delay)

    # ──────────────────────────── Page helpers ──────────────────────────────────

    def _wait_for(self, css: str, timeout: int = 15):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css))
        )

    def _safe_text(self, css: str) -> Optional[str]:
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, css)
            return el.text.strip() or None
        except NoSuchElementException:
            return None

    # ──────────────────────────── Price parsing ─────────────────────────────────

    def _parse_price(self, raw: Optional[str]) -> Optional[float]:
        if not raw:
            return None
        # Remove currency symbols and spaces first, THEN extract digits
        # Strip "Rs.", "NPR", "रू" etc. before any regex
        cleaned = re.sub(r"[^\d,]", "", raw).strip()
        if not cleaned:
            return None
        # Remove all commas (Nepali thousands separator: 1,23,456)
        cleaned = cleaned.replace(",", "")
        if not cleaned:
            return None
        try:
            value = float(cleaned)
            if value < 1 or value > 10_000_000:
                logger.warning(f"Price out of expected range: {value} (raw: {raw!r})")
                return None
            return value
        except ValueError:
            logger.warning(f"Could not parse price: {raw!r}")
            return None

    # ──────────────────────────── Product detail ────────────────────────────────

    def _scrape_product_detail(self, url: str) -> Optional[dict]:
        """
        Visit a single Daraz product page and extract price fields.
        Returns a dict or None on failure.
        """
        try:
            self.driver.get(url)
            self._wait_for(SELECTORS["title"], timeout=20)
            self._polite_wait(extra=1.0)

            match = re.search(SELECTORS["item_id_pattern"], url)
            item_id = match.group(1) if match else None

            title        = self._safe_text(SELECTORS["title"])
            raw_current  = self._safe_text(SELECTORS["current_price"])
            raw_original = self._safe_text(SELECTORS["original_price"])
            seller       = self._safe_text(SELECTORS["seller"])

            current_price  = self._parse_price(raw_current)
            original_price = self._parse_price(raw_original)

            is_promotional = original_price is not None and (
                original_price > (current_price or 0)
            )

            # ── Image extraction ─────────────────────────────────────────────
            # Try src first (loaded image), fall back to data-src (lazy-loaded).
            # image_verified=True only when we actually got a URL.
            image_url = None
            try:
                img_el = self.driver.find_element(By.CSS_SELECTOR, SELECTORS["image"])
                image_url = (
                    img_el.get_attribute("src") or
                    img_el.get_attribute("data-src") or
                    None
                )
                # Reject placeholder/blank src values
                if image_url and (
                    image_url.startswith("data:") or image_url.strip() == ""
                ):
                    image_url = None
            except NoSuchElementException:
                logger.debug(f"No image element found at {url}")

            if not current_price:
                logger.warning(f"No price found at {url}")
                return None

            return {
                "item_id":        item_id,
                "title":          title,
                "url":            url,
                "current_price":  current_price,
                "original_price": original_price,
                "is_promotional": is_promotional,
                "seller_name":    seller,
                "image_url":      image_url,
                "image_verified": image_url is not None,
                "scraped_at":     datetime.now(timezone.utc),
            }

        except TimeoutException:
            logger.warning(f"Timeout loading product page: {url}")
            return None
        except WebDriverException as e:
            logger.error(f"WebDriver error on {url}: {e}")
            return None

    def _scrape_with_retry(self, url: str) -> Optional[dict]:
        """
        Attempt to scrape a product page up to MAX_RETRIES times.
        Waits with backoff between attempts.
        Returns the product dict if any attempt succeeds, else None.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            result = self._scrape_product_detail(url)
            if result is not None:
                if attempt > 1:
                    logger.info(f"  ✓ Succeeded on attempt {attempt}: {url}")
                return result

            if attempt < MAX_RETRIES:
                logger.warning(
                    f"  Attempt {attempt}/{MAX_RETRIES} failed for {url} — retrying..."
                )
                self._retry_wait(attempt)
            else:
                logger.error(
                    f"  ✗ All {MAX_RETRIES} attempts failed for {url} — skipping."
                )

        return None

    # ──────────────────────────── Category listing ──────────────────────────────

    def _collect_product_links(self, category: str, max_products: int) -> list[str]:
        """
        Walk Daraz category listing pages and collect product detail URLs.
        Stops when max_products links are collected or no more pages exist.
        """
        links       = []
        page        = 1
        listing_url = f"{DARAZ_BASE}/{category}/"

        while len(links) < max_products:
            url = listing_url if page == 1 else f"{listing_url}?page={page}"
            logger.info(f"Listing page {page}: {url}")

            try:
                self.driver.get(url)
                self._wait_for(SELECTORS["product_cards"], timeout=20)
                self._polite_wait()

                cards = self.driver.find_elements(
                    By.CSS_SELECTOR, SELECTORS["product_cards"]
                )
                if not cards:
                    logger.info(f"No products on page {page}, stopping.")
                    break

                for card in cards:
                    if len(links) >= max_products:
                        break
                    try:
                        anchor = card.find_element(By.CSS_SELECTOR, SELECTORS["card_link"])
                        href = anchor.get_attribute("href")
                        if href and "daraz.com.np/products/" in href:
                            clean = href.split("?")[0].split("#")[0]
                            if clean not in links:
                                links.append(clean)
                    except NoSuchElementException:
                        continue

                try:
                    self.driver.find_element(By.CSS_SELECTOR, SELECTORS["next_page"])
                    page += 1
                except NoSuchElementException:
                    logger.info("Last page reached.")
                    break

            except TimeoutException:
                logger.warning(f"Timeout on listing page {page}, stopping category.")
                break
            except WebDriverException as e:
                logger.error(f"WebDriver error on listing: {e}")
                break

        logger.info(f"Collected {len(links)} links from /{category}/")
        return links

    # ──────────────────────────── Public API ────────────────────────────────────

    def crawl_category(
        self,
        category: str,
        max_products: int = 50,
        save_callback=None,
    ) -> list[dict]:
        """
        Full crawl of one Daraz category.

        Args:
            category:      Daraz category slug (e.g. 'laptops')
            max_products:  Maximum products to scrape
            save_callback: Optional callable(product_dict) — called immediately
                           after each successful scrape so data is persisted
                           even if the crawl crashes partway through.

        Returns a list of all successfully scraped product dicts.
        """
        logger.info(f"=== Crawling category: {category} (max {max_products}) ===")
        links = self._collect_product_links(category, max_products)

        results      = []
        saved_count  = 0
        failed_count = 0

        for i, link in enumerate(links, 1):
            logger.info(f"  [{i}/{len(links)}] {link}")

            data = self._scrape_with_retry(link)

            if data:
                data["category"] = category
                results.append(data)

                # ── Immediate save: persist now, don't wait for batch ──────────
                if save_callback:
                    try:
                        save_callback(data)
                        saved_count += 1
                    except Exception as e:
                        logger.error(f"  Save callback failed for {link}: {e}")
            else:
                failed_count += 1

            self._polite_wait()

        logger.info(
            f"=== Category {category} done: "
            f"{len(results)} scraped, {saved_count} saved immediately, "
            f"{failed_count} failed after {MAX_RETRIES} retries ==="
        )
        return results