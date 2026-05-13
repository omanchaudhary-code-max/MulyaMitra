# SPTDAS Crawler — Setup & Operations Guide

## What this crawler does

Collects Daraz Nepal product prices daily, stores them in MongoDB,
and feeds the deal detection engine that powers user alerts.

**ToS compliance:** Only crawls public product listing and detail pages.
Respects daraz.com.np/robots.txt — disallowed paths (/checkout/, /customer/,
/cart/, /catalog/) are never visited. Randomised delays prevent server overload.

---

## Project structure

```
sptdas_crawler/
├── crawler/
│   ├── daraz_crawler.py   ← Selenium scraper (product data extraction)
│   ├── storage.py         ← MongoDB layer (upserts, dedup, indexes)
│   ├── orchestrator.py    ← Ties crawler + storage into one run cycle
│   └── deal_detector.py   ← Checks alert conditions after each crawl
├── scheduler.py           ← APScheduler daily job (run this as a service)
├── run_now.py             ← One-off manual crawl (testing + first run)
├── requirements.txt
├── .env.example           ← Copy to .env and fill in your values
└── logs/
    └── crawler.log        ← All output goes here + stdout
```

---

## Setup (do this once)

### 1. Prerequisites

- Python 3.10+
- Google Chrome installed (any recent version)
- MongoDB running locally OR a MongoDB Atlas URI

### 2. Install dependencies

```bash
cd sptdas_crawler
pip install -r requirements.txt
```

This installs:
- `selenium` + `webdriver-manager` (auto-downloads chromedriver)
- `pymongo` (MongoDB driver)
- `apscheduler` (job scheduler)
- `python-dotenv` (config from .env)
- `fake-useragent` (UA rotation)

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
MONGO_URI=mongodb://localhost:27017    # or your Atlas URI
MONGO_DB=sptdas
DELAY_MIN=4
DELAY_MAX=10
MAX_PRODUCTS_PER_CATEGORY=50
CATEGORIES=laptops,smartphones,televisions,headphones,shoes-men,shoes-women,tshirts-men,books,kitchen-appliances,cameras
CRAWL_HOUR=2
CRAWL_MINUTE=30
PROJECT_END_DATE=2026-07-30
```

### 4. First run (seed the database)

```bash
python run_now.py
```

You should see output like:
```
2026-05-11 14:00:01  INFO  Starting Chrome driver...
2026-05-11 14:00:05  INFO  === Crawling category: laptops (max 50) ===
2026-05-11 14:00:05  INFO  Listing page 1: https://www.daraz.com.np/laptops/
...
2026-05-11 14:18:42  INFO  Crawl complete. Stats: {total_products: 487, ...}
```

Test a specific category with fewer products first:
```bash
python run_now.py --categories laptops --max 5
```

### 5. Start the daily scheduler

```bash
python scheduler.py
```

This runs forever (blocking), firing a crawl every day at 02:30 NPT.
It automatically stops on 2026-07-30.

---

## Running as a background service (recommended for production)

### Option A: Linux systemd (best for a server or always-on PC)

Create `/etc/systemd/system/sptdas-crawler.service`:

```ini
[Unit]
Description=SPTDAS Daraz Crawler Scheduler
After=network.target mongod.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/sptdas_crawler
ExecStart=/usr/bin/python3 scheduler.py
Restart=on-failure
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sptdas-crawler
sudo systemctl start sptdas-crawler
sudo systemctl status sptdas-crawler
```

View live logs:
```bash
sudo journalctl -u sptdas-crawler -f
```

### Option B: Windows Task Scheduler

- Action: `python C:\path\to\sptdas_crawler\scheduler.py`
- Trigger: At startup, run indefinitely
- Or: Daily trigger at 02:30 using `run_now.py` instead of `scheduler.py`

### Option C: Simple nohup (quick and dirty on Linux/Mac)

```bash
nohup python scheduler.py > logs/scheduler.log 2>&1 &
echo $! > logs/scheduler.pid
```

To stop:
```bash
kill $(cat logs/scheduler.pid)
```

---

## Data projection — why starting now matters

Starting collection on **11 May 2026** through **30 July 2026** gives
**80 days** of daily price history per product.

| Milestone          | Date       | Data points per product |
|--------------------|------------|------------------------|
| First run          | 11 May     | 1                      |
| Alert-ready (7pts) | 18 May     | 7  ← ATL alerts begin  |
| 1 month            | 11 Jun     | 31                     |
| Mid-project        | 20 Jun     | 40                     |
| Full dataset       | 30 Jul     | 80                     |

With 10 categories × 50 products = **500 products tracked** and 80 crawls,
you'll accumulate approximately **40,000 price_history documents** by submission.
This is a statistically meaningful dataset for your price charts and deal engine.

**Why 7 data points minimum for ATL alerts?**
In the first week, any price could be a daily fluctuation. After 7 readings
you have a real baseline. The deal_detector.py enforces this automatically.

---

## MongoDB collections reference

```
sptdas.products         — master product registry
sptdas.price_history    — timestamped price per product per crawl
sptdas.crawl_logs       — one doc per run (admin dashboard source)
sptdas.errors           — failed URLs for debugging
sptdas.users            — managed by your Node.js backend
sptdas.watchlist        — managed by your Node.js backend
```

Check your data in MongoDB Compass or mongosh:
```js
use sptdas
db.price_history.countDocuments()
db.products.countDocuments()
db.crawl_logs.find().sort({started_at: -1}).limit(5)
db.errors.find().sort({logged_at: -1}).limit(10)
```

---

## Updating CSS selectors

If Daraz changes their HTML, the crawler will stop finding prices.
All selectors are in one place — `crawler/daraz_crawler.py`, the `SELECTORS` dict:

```python
SELECTORS = {
    "product_cards": "div[data-qa-locator='product-item']",
    "current_price": "span.pdp-price_type_normal, span.notranslate.pdp-price",
    "original_price": "span.pdp-price_type_deleted",
    ...
}
```

To find the new selector: open Chrome DevTools on a Daraz product page,
right-click the price, Inspect, copy the CSS selector, update the dict.
No other code needs to change.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ChromeDriverManager` fails | Check internet connection; update Chrome |
| No products found in category | Daraz changed CSS selectors — update `SELECTORS` |
| MongoDB connection refused | Start MongoDB: `sudo systemctl start mongod` |
| Scheduler fires but crawl skips | Check `PROJECT_END_DATE` in .env |
| 0 prices extracted | Open the URL manually, check if price selector matches |
| High error rate in logs | Daraz may be rate-limiting — increase DELAY_MIN/MAX |
