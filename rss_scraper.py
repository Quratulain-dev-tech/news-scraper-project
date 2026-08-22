# =============================================================================
#  PHASE 1: RSS SCRAPER (URL COLLECTION)
# =============================================================================
import os
import sys
import json
import time
import feedparser
import threading

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from urllib.parse import quote
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Set

import config

def load_sources(sources_file: str) -> List[str]:
    """Load source names from the JSON file."""
    if not os.path.exists(sources_file):
        raise FileNotFoundError(f"Sources file not found at: {sources_file}")

    with open(sources_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, list):
        if len(data) > 0 and isinstance(data[0], dict) and 'source' in data[0]:
            return [item['source'] for item in data]
        return data
    elif isinstance(data, dict):
        return list(data.keys())
    else:
        raise ValueError("Invalid format in sources file.")

def build_rss_url(query: str, after_date: str = "", before_date: str = "",
                  language: str = "en", country: str = "US") -> str:
    """Build a Google News RSS URL with query and optional date range."""
    search_query = query
    if after_date and before_date:
        search_query = f"{query} after:{after_date} before:{before_date}"

    encoded_query = quote(search_query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl={language}-{country}&gl={country}&ceid={country}:{language}"

def fetch_source_articles(query: str, limit: int = 50,
                          after_date: str = "", before_date: str = "") -> List[Dict[str, str]]:
    """
    Fetch up to `limit` articles from Google News RSS for a single source.
    If date filtering yields less articles than limit, falls back to raw search.
    """
    articles = []

    # First attempt: search with date range
    url = build_rss_url(query, after_date, before_date)
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            source_title = entry.get('source', {}).get('title', query) or query
            articles.append({
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'published': entry.get('published', ''),
                'source': source_title,
                'query': query
            })
            if len(articles) >= limit:
                break
    except Exception as e:
        print(f"  [RSS Error] Parsing query '{query}' with date filter: {e}")

    # Fallback attempt: if date filter returned fewer than expected, search without date filter
    if len(articles) < limit:
        url_broad = build_rss_url(query)
        try:
            feed_broad = feedparser.parse(url_broad)
            seen_links = {a['link'] for a in articles}
            for entry in feed_broad.entries:
                link = entry.get('link', '')
                if link and link not in seen_links:
                    source_title = entry.get('source', {}).get('title', query) or query
                    articles.append({
                        'title': entry.get('title', ''),
                        'link': link,
                        'published': entry.get('published', ''),
                        'source': source_title,
                        'query': query
                    })
                    seen_links.add(link)
                if len(articles) >= limit:
                    break
        except Exception as e:
            print(f"  [RSS Error] Parsing query '{query}' fallback: {e}")

    return articles[:limit]

def save_rss_progress(output_file: str, results: Dict[str, List[Dict[str, str]]],
                      total_articles: int, sources_processed: int):
    """Save collected RSS data with metadata to JSON and CSV atomically."""
    data = {
        'metadata': {
            'total_articles': total_articles,
            'sources_processed': sources_processed,
            'timestamp': datetime.now().isoformat()
        },
        'articles': results
    }
    tmp_file = output_file + ".tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, output_file)
    except Exception as e:
        print(f"  ⚠️ Error writing atomic RSS JSON: {e}")


    # Save to CSV as well
    csv_file = output_file.replace('.json', '.csv')
    try:
        import csv
        flattened = []
        idx = 1
        for src, art_list in results.items():
            for art in art_list:
                flattened.append({
                    "id": idx,
                    "source": src,
                    "title": art.get("title", ""),
                    "link": art.get("link", ""),
                    "published": art.get("published", "")
                })
                idx += 1

        if flattened:
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=["id", "source", "title", "link", "published"])
                writer.writeheader()
                writer.writerows(flattened)
    except Exception as e:
        print(f"  ⚠️ CSV export error in RSS: {e}")

    print(f"  💾 Progress saved to {os.path.basename(output_file)} & {os.path.basename(csv_file)} ({total_articles} articles across {sources_processed} sources)")


def scrape_rss_sources(sources: List[str], articles_per_source: int = config.ARTICLES_PER_SOURCE,
                       max_sources: int = config.MAX_SOURCES, output_file: str = config.RSS_OUTPUT_FILE,
                       workers: int = config.RSS_WORKERS, save_interval: int = config.RSS_SAVE_INTERVAL,
                       resume: bool = True) -> Dict[str, List[Dict[str, str]]]:
    """
    Main Phase 1 function to gather raw URLs for sources.
    """
    existing_results = {}
    processed_sources: Set[str] = set()

    if resume and os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                if 'articles' in old_data:
                    existing_results = old_data['articles']
                    processed_sources = set(existing_results.keys())
                    print(f"✅ Resuming Phase 1 RSS: Found {len(processed_sources)} sources in {os.path.basename(output_file)}")
        except Exception as e:
            print(f"⚠️ Could not load existing RSS data: {e}")

    sources_to_process = [s for s in sources[:max_sources] if s not in processed_sources]
    if not sources_to_process:
        print("✅ All sources already collected in Phase 1.")
        return existing_results

    print("=" * 80)
    print(f"🚀 PHASE 1: RSS Scraping ({len(sources_to_process)} sources remaining)")
    print(f"🎯 Target: Up to {articles_per_source} articles/source (~{len(sources[:max_sources]) * articles_per_source} total links)")
    print("=" * 80)

    results = existing_results.copy()
    total_articles = sum(len(v) for v in results.values())
    sources_processed = len(results)
    lock = threading.Lock()

    def process_source_worker(query_source: str) -> Tuple[str, List[Dict[str, str]]]:
        arts = fetch_source_articles(query_source, limit=articles_per_source,
                                     after_date=config.AFTER_DATE, before_date=config.BEFORE_DATE)
        return query_source, arts

    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {executor.submit(process_source_worker, q): q for q in sources_to_process}
        for future in as_completed(futures):
            q_source, articles = future.result()
            with lock:
                if articles:
                    results[q_source] = articles
                    sources_processed += 1
                    total_articles += len(articles)
                    print(f"  [+{len(articles)} arts] {q_source:<35} Total: {total_articles}")
                else:
                    sources_processed += 1
                    results[q_source] = []
                    print(f"  [ 0 arts] {q_source:<35} Total: {total_articles}")

                if sources_processed % save_interval == 0:
                    save_rss_progress(output_file, results, total_articles, sources_processed)

    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user. Saving current progress...")
        save_rss_progress(output_file, results, total_articles, sources_processed)
        executor.shutdown(wait=False, cancel_futures=True)
        sys.exit(0)
    else:
        executor.shutdown(wait=True)

    # Save final results
    save_rss_progress(output_file, results, total_articles, sources_processed)
    print("=" * 80)
    print(f"✅ PHASE 1 COMPLETE! Sources: {sources_processed} | Total URLs: {total_articles}")
    print("=" * 80)
    return results

if __name__ == "__main__":
    srcs = load_sources(config.SOURCES_FILE)
    scrape_rss_sources(srcs, articles_per_source=config.ARTICLES_PER_SOURCE, max_sources=config.MAX_SOURCES)
