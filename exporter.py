# =============================================================================
#  PHASE 4: EXPORTER (JSON, CSV, POSTGRESQL DATABASE)
# =============================================================================
import os
import sys
import csv
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime
from typing import List, Dict, Any, Optional

import config

def export_to_json(articles: List[Dict[str, Any]], json_path: str = config.CLEANED_JSON_FILE):
    """Export cleaned articles to JSON file."""
    data = {
        "metadata": {
            "total_articles": len(articles),
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "format_version": "1.0"
        },
        "articles": articles
    }

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"💾 Cleaned JSON exported to: {os.path.basename(json_path)} ({len(articles)} items)")

def export_to_csv(articles: List[Dict[str, Any]], csv_path: str = config.CLEANED_CSV_FILE):
    """Export cleaned articles to CSV file."""
    if not articles:
        print("⚠️ No articles to export to CSV.")
        return

    fieldnames = [
        "id", "title", "url", "source", "author",
        "published_date", "published_time", "summary", "scraped_at"
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(articles)

    print(f"📄 Cleaned CSV exported to: {os.path.basename(csv_path)} ({len(articles)} rows)")

def export_to_postgres(articles: List[Dict[str, Any]], db_config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Export cleaned articles into PostgreSQL Database.
    Automatically creates news_articles table and performs upsert on conflict (url).
    """
    db_config = db_config or config.POSTGRES_CONFIG

    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        print("\n⚠️ psycopg2 module not found.")
        print("  To enable direct PostgreSQL export, run: pip install psycopg2-binary")
        print("  Alternatively, you can import the generated CSV file directly into PostgreSQL using init_db.sql!")
        return False

    if not articles:
        print("⚠️ No articles to export to PostgreSQL.")
        return False

    print(f"🐘 Connecting to PostgreSQL database '{db_config.get('dbname')}' at {db_config.get('host')}...")

    target_db = db_config.get("dbname", "news_db")
    user = db_config.get("user", "postgres")
    pwd = db_config.get("password", "")
    host = db_config.get("host", "localhost")
    port = db_config.get("port", 5432)

    # Ensure target database exists
    try:
        conn = psycopg2.connect(host=host, port=port, dbname=target_db, user=user, password=pwd)
    except psycopg2.OperationalError as e:
        if "does not exist" in str(e):
            print(f"  📌 Database '{target_db}' does not exist. Creating database...")
            try:
                sys_conn = psycopg2.connect(host=host, port=port, dbname="postgres", user=user, password=pwd)
                sys_conn.autocommit = True
                sys_cur = sys_conn.cursor()
                sys_cur.execute(f'CREATE DATABASE "{target_db}";')
                sys_cur.close()
                sys_conn.close()
                print(f"  ✓ Database '{target_db}' created successfully.")
                conn = psycopg2.connect(host=host, port=port, dbname=target_db, user=user, password=pwd)
            except Exception as create_err:
                print(f"❌ Failed to auto-create database '{target_db}': {create_err}")
                return False
        else:
            print(f"❌ PostgreSQL Connection Error: {e}")
            return False

    try:
        cur = conn.cursor()

        # Create table DDL
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS news_articles (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            author TEXT,
            published_date DATE,
            published_time VARCHAR(100),
            summary TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        ALTER TABLE news_articles ALTER COLUMN source TYPE TEXT;
        ALTER TABLE news_articles ALTER COLUMN author TYPE TEXT;
        CREATE INDEX IF NOT EXISTS idx_news_articles_url ON news_articles(url);
        CREATE INDEX IF NOT EXISTS idx_news_articles_source ON news_articles(source);
        """
        cur.execute(create_table_sql)
        conn.commit()

        # Insert Query
        insert_sql = """
        INSERT INTO news_articles (title, url, source, author, published_date, published_time, summary, scraped_at)
        VALUES %s
        ON CONFLICT (url) DO UPDATE SET
            title = EXCLUDED.title,
            author = EXCLUDED.author,
            published_date = EXCLUDED.published_date,
            published_time = EXCLUDED.published_time,
            summary = EXCLUDED.summary;
        """

        records = [
            (
                a["title"],
                a["url"],
                a["source"],
                a.get("author") or "Unknown",
                a.get("published_date") or None,
                a.get("published_time") or None,
                a.get("summary") or "",
                a.get("scraped_at") or None
            )
            for a in articles
        ]

        execute_values(cur, insert_sql, records, page_size=500)
        conn.commit()

        print(f"✅ Successfully inserted/updated {len(records)} articles in PostgreSQL table 'news_articles'!")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ PostgreSQL Export Error: {e}")
        return False

def export_all(articles: List[Dict[str, Any]]):
    """Export to both JSON and CSV files, and notify about PostgreSQL option."""
    print("=" * 80)
    print("💾 EXPORTING FINAL CLEANED DATASET")
    print("=" * 80)
    export_to_json(articles)
    export_to_csv(articles)
    print("=" * 80)
