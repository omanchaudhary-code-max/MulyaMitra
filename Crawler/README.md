# MulyaMitra Crawler

A production-ready price tracking and deal monitoring crawler for **Daraz Nepal**, built for the **SPTDAS (Smart Product Tracking & Deal Alert System)** project.

The crawler collects product prices daily, stores historical pricing data in MongoDB, and powers the deal detection engine used for price-drop alerts and analytics.

---

## Features

- Daily automated product crawling
- MongoDB-based historical price storage
- Deal detection & ATL (All-Time-Low) alert support
- Randomized crawling delays for respectful scraping
- Modular architecture for easy maintenance
- APScheduler-based automation
- Detailed logging & crawl monitoring
- Environment-based configuration
- Easy selector updates if Daraz changes HTML structure

---

## Tech Stack

| Technology | Purpose |
|---|---|
| Python | Core crawler logic |
| Selenium | Browser automation & scraping |
| WebDriver Manager | Automatic ChromeDriver management |
| MongoDB | Data storage |
| APScheduler | Daily scheduling |
| dotenv | Environment configuration |
| Fake User Agent | User-agent rotation |

---

# Project Structure

```bash
MulyaMitra/
├── crawler/
│   ├── daraz_crawler.py      # Selenium scraper
│   ├── storage.py            # MongoDB operations
│   ├── orchestrator.py       # Crawl workflow manager
│   └── deal_detector.py      # Deal & ATL detection
│
├── scheduler.py              # Daily scheduled crawler
├── run_now.py                # Manual one-time crawl
├── requirements.txt
├── .env.example
├── .gitignore
│
└── logs/
    └── crawler.log

Compliance & Responsible Crawling
This project only crawls publicly accessible product pages and respects Daraz Nepal's robots.txt.
The crawler intentionally avoids restricted routes such as:
/checkout/
/customer/
/cart/
/catalog/
Additional protections include:
Randomized delays between requests
Limited products per category
Controlled scheduling frequency
This project is intended strictly for academic and educational purposes.
Setup Guide
1. Prerequisites
Ensure the following are installed:
Python 3.10+
Google Chrome
MongoDB (Local or Atlas)
2. Clone Repository
git clone git@github.com:omanchaudhary-code-max/MulyaMitra.git
cd MulyaMitra
3. Install Dependencies
pip install -r requirements.txt
Installed packages include:
selenium
webdriver-manager
pymongo
apscheduler
python-dotenv
fake-useragent
4. Configure Environment Variables
Create .env:
cp .env.example .env
Example configuration:
MONGO_URI=mongodb://localhost:27017
MONGO_DB=sptdas

DELAY_MIN=4
DELAY_MAX=10

MAX_PRODUCTS_PER_CATEGORY=50

CATEGORIES=laptops,smartphones,televisions,headphones,shoes-men,shoes-women,tshirts-men,books,kitchen-appliances,cameras

CRAWL_HOUR=2
CRAWL_MINUTE=30

PROJECT_END_DATE=2026-07-30
Running the Crawler
Manual Crawl
Run a one-time crawl:
python run_now.py
Test Small Crawl
Useful for debugging:
python run_now.py --categories laptops --max 5
Start Daily Scheduler
python scheduler.py
This runs continuously and automatically starts a crawl every day at the configured time.
Running in Production
Linux (systemd)
Create:
/etc/systemd/system/mulyamitra-crawler.service
Example configuration:
[Unit]
Description=MulyaMitra Daraz Crawler
After=network.target mongod.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/MulyaMitra
ExecStart=/usr/bin/python3 scheduler.py
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
Enable service:
sudo systemctl daemon-reload
sudo systemctl enable mulyamitra-crawler
sudo systemctl start mulyamitra-crawler
Check status:
sudo systemctl status mulyamitra-crawler
View logs:
sudo journalctl -u mulyamitra-crawler -f
Quick Background Run (Linux/Mac)
nohup python scheduler.py > logs/scheduler.log 2>&1 &
Stop process:
kill $(cat logs/scheduler.pid)
MongoDB Collections
Collection	Purpose
products	Master product registry
price_history	Historical pricing data
crawl_logs	Crawl summaries & statistics
errors	Failed URLs and exceptions
users	Managed by backend
watchlist	Managed by backend
Example MongoDB Queries
use sptdas

db.products.countDocuments()

db.price_history.countDocuments()

db.crawl_logs.find()
.sort({ started_at: -1 })
.limit(5)

db.errors.find()
.sort({ logged_at: -1 })
.limit(10)
Updating CSS Selectors
If Daraz updates their frontend HTML structure, update selectors inside:
crawler/daraz_crawler.py
Example:
SELECTORS = {
    "product_cards": "div[data-qa-locator='product-item']",
    "current_price": "span.pdp-price_type_normal",
    "original_price": "span.pdp-price_type_deleted",
}
Use Chrome DevTools to inspect updated elements and replace selectors accordingly.
Dataset Projection
With:
10 categories
50 products per category
80 days of crawling
The system can generate approximately:
40,000+ historical price records
This creates a meaningful dataset for:
Price trend visualization
Deal analytics
Alert systems
Market behavior analysis
Troubleshooting
Problem	Solution
ChromeDriver fails	Update Chrome & check internet
No products detected	Update CSS selectors
MongoDB connection refused	Start MongoDB service
Scheduler skips crawl	Verify PROJECT_END_DATE
Prices not extracted	Inspect updated HTML
Too many request failures	Increase delays
Security Notes
Never commit:
.env
API keys
Database credentials
Logs
__pycache__
Ensure .gitignore contains:
.env
__pycache__/
*.pyc
logs/
*.log
Future Improvements
Multi-platform support
Proxy rotation
Async crawling
Distributed scheduler
ML-based deal prediction
Real-time notification service
Admin analytics dashboard
License
This project was developed for educational and academic purposes under the SPTDAS project.
Use responsibly and comply with the target platform's terms of service.
Author
Oman Chaudhary
GitHub: https://github.com/omanchaudhary-code-max