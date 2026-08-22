# 📰 News scraper Pipeline

> Collect news. Clean the noise. Store structured insights.

A Python-powered news-data pipeline that collects articles from Google News RSS, enriches them with article metadata, cleans and deduplicates the records, then exports the final dataset to PostgreSQL.

## ✨ Highlights

- 🌍 Processes up to **200 news sources**
- 🔗 Collects Google News RSS article links
- 🧠 Resolves original URLs and enriches article metadata
- 🧹 Cleans titles, authors, summaries, dates, and duplicate records
- 🐘 Exports the final dataset directly to PostgreSQL
- 📦 Includes a portable SQL database backup

## 📊 Dataset Snapshot

| Metric | Value |
| --- | ---: |
| Sources processed | 200 |
| Raw articles collected | 9,655 |
| Cleaned final articles | 9,500 |
| Database table | `news_articles` |

## 🗂️ Project Structure

```text
news-scraping-pipeline/
├── database/
│   └── news_db_backup.sql          # PostgreSQL backup with final data
├── pipeline/
│   ├── main.py                     # Pipeline entry point
│   ├── rss_scraper.py              # Google News RSS collection
│   ├── enricher.py                 # URL and metadata enrichment
│   ├── preprocessor.py             # Cleaning and deduplication
│   ├── exporter.py                 # JSON, CSV and PostgreSQL export
│   ├── init_db.sql                 # Database schema
│   ├── config.example.py           # Safe configuration template
│   ├── scraped_news_cleaned.csv    # Final cleaned dataset
│   └── scraped_news_cleaned.json   # Final cleaned dataset (JSON)
├── requirements.txt
└── README.md
```

## ⚙️ Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.py config.py
```

Open `pipeline/config.py` and enter your own PostgreSQL password. Do not upload this file to GitHub.

## 🚀 Export Final Data to PostgreSQL

The final dataset is already available in CSV and JSON. To create/export it to PostgreSQL:

```powershell
python main.py --phase export-db
```

This creates the `news_db` database (if needed) and inserts the cleaned records into the `news_articles` table.

## 🐘 Restore the Included Database Backup

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d news_db -f news_db_backup.sql
```

## 🔎 Explore the Data

```sql
SELECT COUNT(*) FROM news_articles;

SELECT id, title, source, published_date
FROM news_articles
LIMIT 10;
```

## 🔐 Security Note

The real `config.py` file contains local database credentials and is excluded through `.gitignore`. Use `config.example.py` as a safe template.

---

Built with Python, Google News RSS, Beautiful Soup, Playwright, and PostgreSQL. ✨
