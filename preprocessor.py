# =============================================================================
#  PHASE 3: PREPROCESSOR & DATA CLEANER
# =============================================================================
import os
import sys
import re
import html
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import config

def clean_title(title: str) -> str:
    """Clean headline/title by removing trailing source branding suffixes."""
    if not title:
        return ""

    title = html.unescape(title).strip()

    # Common source branding separator patterns (e.g., "Headline - Reuters", "Headline | BBC")
    patterns = [
        r"\s*[-|–—:]\s*(?:Reuters|BBC|CNN|CNBC|Bloomberg|WSJ|The Guardian|Al Jazeera|AP News|Fox News|The New York Times|NPR|Forbes|Business Insider|MarketWatch|Politico|Axios)\s*$",
        r"\s*[-|–—]\s*[A-Z][a-zA-Z0-9\s.]{2,25}$"  # Generic trailing source name
    ]

    for pat in patterns:
        title = re.sub(pat, "", title, flags=re.IGNORECASE).strip()

    # Remove extra quotes and collapse whitespace
    title = re.sub(r"\s+", " ", title)
    return title.strip()

def clean_author(author_raw: Any, source_name: str = "") -> str:
    """Clean and normalize author string, falling back to '{Source} Staff' if missing."""
    fallback = f"{source_name} Staff" if source_name else "Unknown"
    if not author_raw:
        return fallback

    if isinstance(author_raw, list):
        author_raw = ", ".join(str(a) for a in author_raw if a)

    author_str = str(author_raw)
    author_str = html.unescape(author_str).strip()

    # Remove prefixes like "By ", "BY ", "by "
    author_str = re.sub(r"^(?:by|written by|author|posted by)[:\s]+", "", author_str, flags=re.IGNORECASE).strip()

    # Check for junk / generic non-person authors
    junk_patterns = [
        r"^https?://", r"www\.", r"@\w+", r"^\d+$", r"^admin$", r"^staff$",
        r"^contributor$", r"^editor$", r"^newsroom$", r"^editorial team$", r"^unknown$"
    ]
    for junk in junk_patterns:
        if re.search(junk, author_str, re.IGNORECASE):
            return fallback

    # Clean multiple spaces and special characters
    author_str = re.sub(r"\s+", " ", author_str).strip()
    return author_str if len(author_str) >= 2 else fallback

def clean_description(text: str) -> str:
    """Remove HTML tags, decode HTML entities, and collapse whitespace."""
    if not text:
        return ""

    text = html.unescape(text)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove URL links in body
    text = re.sub(r"https?://\S+", "", text)
    # Replace HTML space entities & collapse whitespace
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def split_date_and_time(raw_date_str: str) -> Tuple[str, str]:
    """
    Split a publication datetime string into separate clean published_date (YYYY-MM-DD)
    and published_time (HH:MM:SS AM/PM EST/EDT) strings.
    """
    if not raw_date_str:
        now_et = datetime.now(config.ET)
        return now_et.strftime("%Y-%m-%d"), now_et.strftime("%I:%M:%S %p EST")

    # Match "YYYY-MM-DD HH:MM:SS AM/PM EST/EDT"
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?(?:\s+[A-Z]{3,4})?)", raw_date_str, re.I)
    if m:
        p_date = m.group(1)
        p_time = m.group(2).strip()
        return p_date, p_time

    # Try parsing ISO 8601
    try:
        dt = datetime.fromisoformat(raw_date_str.replace("Z", "+00:00"))
        dt_et = dt.astimezone(config.ET)
        abbr = "EDT" if dt_et.dst() and dt_et.dst().total_seconds() != 0 else "EST"
        return dt_et.strftime("%Y-%m-%d"), dt_et.strftime(f"%I:%M:%S %p {abbr}")
    except Exception:
        pass

    m_date = re.search(r"(\d{4}-\d{2}-\d{2})", raw_date_str)
    if m_date:
        p_date = m_date.group(1)
        p_time = raw_date_str.replace(p_date, "").strip()
        return p_date, p_time if p_time else "12:00:00 PM EST"

    now_et = datetime.now(config.ET)
    return now_et.strftime("%Y-%m-%d"), "12:00:00 PM EST"

def preprocess_and_clean_dataset(input_file: str = config.ENRICH_OUTPUT_FILE) -> List[Dict[str, Any]]:
    """
    Main preprocessing function:
    - Loads enriched data
    - Cleans titles, authors, descriptions
    - Splits published date and published time into separate columns
    - Removes google_url and time_tier
    - Deduplicates by URL and headline
    - Returns clean flat list of article dictionaries
    """
    if not os.path.exists(input_file):
        print(f"❌ Input file {input_file} not found for preprocessing.")
        return []

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    raw_articles_map = data.get("articles", {})
    cleaned_articles: List[Dict[str, Any]] = []

    seen_urls = set()
    seen_titles = set()

    total_processed = 0
    total_cleaned = 0

    print("=" * 80)
    print("🧹 PHASE 3: Data Preprocessing, Cleaning & Deduplication")
    print("=" * 80)

    for source_name, article_list in raw_articles_map.items():
        for art in article_list:
            total_processed += 1

            raw_title = art.get("title", "")
            raw_url = art.get("decoded_url") or art.get("link") or art.get("google_link", "")
            raw_author = art.get("author", "")
            raw_desc = art.get("description", "")
            pub_date_et = art.get("published_at", "")

            # 1. Clean Title
            c_title = clean_title(raw_title)
            if not c_title or len(c_title) < 10:
                continue

            # 2. Clean URL
            if not raw_url:
                continue

            # 3. Clean Author
            c_author = clean_author(raw_author, source_name)

            # 4. Clean Description
            c_desc = clean_description(raw_desc)

            # 5. Deduplication
            normalized_title_key = c_title.lower()[:60]
            if raw_url in seen_urls or normalized_title_key in seen_titles:
                continue

            seen_urls.add(raw_url)
            seen_titles.add(normalized_title_key)

            # 6. Separate Date & Time
            p_date, p_time = split_date_and_time(pub_date_et)

            cleaned_article = {
                "id": total_cleaned + 1,
                "title": c_title,
                "url": raw_url,
                "source": source_name,
                "author": c_author,
                "published_date": p_date,
                "published_time": p_time,
                "summary": c_desc if c_desc else c_title,
                "scraped_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }

            cleaned_articles.append(cleaned_article)
            total_cleaned += 1


    print(f"📊 Total Raw Input Articles: {total_processed}")
    print(f"✨ Total Cleaned & Deduplicated Articles: {total_cleaned}")
    print(f"🗑️ Removed Duplicates / Invalid: {total_processed - total_cleaned}")
    print("=" * 80)

    return cleaned_articles

if __name__ == "__main__":
    arts = preprocess_and_clean_dataset()
    print(f"Cleaned {len(arts)} articles.")
