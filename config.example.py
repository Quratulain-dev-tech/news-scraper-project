"""Copy this file to config.py and add your own PostgreSQL password."""
import os
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(BASE_DIR, "source_counts (1).json")

ARTICLES_PER_SOURCE = 50
MAX_SOURCES = 200
AFTER_DATE = "2021-01-01"
BEFORE_DATE = "2026-12-31"

RSS_WORKERS = 30
ENRICH_REQUESTS_WORKERS = 80
PHASE2_BROWSERS = 2
TABS_PER_BROWSER = 3
REQUEST_TIMEOUT = 2.5
RSS_SAVE_INTERVAL = 10
ENRICH_SAVE_INTERVAL = 25

RSS_OUTPUT_FILE = os.path.join(BASE_DIR, "raw_news_articles.json")
RSS_CSV_FILE = os.path.join(BASE_DIR, "raw_news_articles.csv")
ENRICH_OUTPUT_FILE = os.path.join(BASE_DIR, "news_articles_enriched.json")
ENRICH_CSV_FILE = os.path.join(BASE_DIR, "news_articles_enriched.csv")
CACHE_FILE = os.path.join(BASE_DIR, "url_cache.json")
FAILED_FILE = os.path.join(BASE_DIR, "failed_articles.json")
CLEANED_JSON_FILE = os.path.join(BASE_DIR, "scraped_news_cleaned.json")
CLEANED_CSV_FILE = os.path.join(BASE_DIR, "scraped_news_cleaned.csv")
SQL_SCHEMA_FILE = os.path.join(BASE_DIR, "init_db.sql")

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}
PAYWALLED_SOURCES = {
    "bloomberg.com", "bloomberg", "wsj.com", "wsj", "wall street journal",
    "ft.com", "financial times", "barrons.com", "barron's",
}
POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "news_db",
    "user": "postgres",
    "password": "YOUR_POSTGRES_PASSWORD",
}
