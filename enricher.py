# =============================================================================
#  PHASE 2: MULTI-TIER ARTICLE ENRICHER & SCRAPER
# =============================================================================
import os
import sys
import json
import re
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import random
import threading
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from bs4 import BeautifulSoup

import config

# Try importing optional tools gracefully
try:
    from googlenewsdecoder import gnewsdecoder, new_decoderv1
    HAS_DECODER_LIB = True
except ImportError:
    HAS_DECODER_LIB = False

try:
    import nodriver as uc
    HAS_NODRIVER = True
except ImportError:
    HAS_NODRIVER = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# Global Thread Lock for safe file writing
enrich_lock = Lock()

# Global State Caches
URL_CACHE: Dict[str, str] = {}
FAILED_LIST: List[Dict[str, Any]] = []
FAILED_SET: set = set()
ENRICHED_DATA: Dict[str, Any] = {}

# -----------------------------------------------------------------------------
# UTILITY FUNCTIONS
# -----------------------------------------------------------------------------
def load_json_file(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json_file(path: str, data: Any):
    """Save data to JSON atomically to prevent file corruption on interrupt."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"  ⚠️ Error writing atomic JSON {path}: {e}")


def save_enriched_progress(output_file: str, enriched_data: Dict[str, Any]):
    """Save enriched articles to both JSON and CSV files."""
    with enrich_lock:
        save_json_file(output_file, enriched_data)

        # Export enriched CSV
        csv_file = output_file.replace('.json', '.csv')
        try:
            import csv
            flattened = []
            idx = 1
            for src, art_list in enriched_data.get("articles", {}).items():
                for art in art_list:
                    pub_str = art.get("published_at", "")
                    p_date = ""
                    p_time = ""
                    if pub_str:
                        m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(.*)", pub_str)
                        if m:
                            p_date = m.group(1)
                            p_time = m.group(2).strip()
                        else:
                            p_date = pub_str

                    flattened.append({
                        "id": idx,
                        "source": src,
                        "title": art.get("title", ""),
                        "url": art.get("decoded_url") or art.get("link", ""),
                        "published_date": p_date,
                        "published_time": p_time,
                        "author": art.get("author", ""),
                        "description": art.get("description", "")
                    })
                    idx += 1

            if flattened:
                fieldnames = ["id", "source", "title", "url", "published_date", "published_time", "author", "description"]
                with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(flattened)
        except Exception as e:
            print(f"  ⚠️ CSV export error in enrichment: {e}")



def get_domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip("www.")
    except Exception:
        return ""

def is_cloudflare_blocked(html: str) -> bool:
    if not html:
        return True
    low = html.lower()[:3000]
    signatures = [
        "just a moment", "checking your browser", "cf-browser-verification",
        "challenge-platform", "enable javascript and cookies to continue",
        "attention required! | cloudflare"
    ]
    return any(sig in low for sig in signatures)

# -----------------------------------------------------------------------------
# URL DECODER
# -----------------------------------------------------------------------------
def decode_google_news_url(url: str) -> str:
    """Decode Google News redirect URL to actual article URL (fast non-blocking)."""
    if not url or "news.google.com" not in url:
        return url

    if url in URL_CACHE:
        return URL_CACHE[url]

    # Method 1: Helper Libraries (fast attempt)
    if HAS_DECODER_LIB:
        try:
            res = new_decoderv1(url)
            if res and isinstance(res, dict) and res.get("status"):
                decoded = res.get("decoded_url")
                if decoded and "google.com" not in decoded:
                    URL_CACHE[url] = decoded
                    return decoded
        except Exception:
            pass

        try:
            res = gnewsdecoder(url)
            if res and isinstance(res, dict) and res.get("status"):
                decoded = res.get("decoded_url")
                if decoded and "google.com" not in decoded:
                    URL_CACHE[url] = decoded
                    return decoded
        except Exception:
            pass

    # Method 2: Mobile User-Agent HTTP Follower (2s timeout)
    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, headers=mobile_headers, timeout=1.5, allow_redirects=True)
        if r.url and r.url != url and "news.google.com" not in r.url:
            URL_CACHE[url] = r.url
            return r.url
    except Exception:
        pass

    return url



# -----------------------------------------------------------------------------
# DATETIME PARSING & CONVERSION
# -----------------------------------------------------------------------------
def format_datetime_to_et(dt: datetime) -> str:
    """Format datetime into Eastern Time standard string."""
    dt_et = dt.astimezone(config.ET)
    abbr = "EDT" if dt_et.dst() and dt_et.dst().total_seconds() != 0 else "EST"
    return dt_et.strftime(f"%Y-%m-%d %I:%M:%S %p {abbr}")

def parse_raw_datetime(text: str) -> Optional[str]:
    """Parse raw text date into standard Eastern Time string."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)

    iso_formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M%z", "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"
    ]

    for fmt in iso_formats:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=config.UTC)
            return format_datetime_to_et(dt)
        except Exception:
            pass

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=config.UTC)
        return format_datetime_to_et(dt)
    except Exception:
        pass

    # Regex for "Month DD, YYYY HH:MM AM/PM"
    m = re.search(r"(\w+ \d{1,2},?\s*\d{4})\s*(?:at\s*)?(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))?", text, re.I)
    if m:
        date_part = m.group(1).replace(",", "")
        time_part = m.group(2) or "12:00 PM"
        for fmt in ["%B %d %Y %I:%M %p", "%b %d %Y %I:%M %p"]:
            try:
                dt = datetime.strptime(f"{date_part} {time_part.strip()}", fmt)
                return format_datetime_to_et(dt.replace(tzinfo=config.ET))
            except Exception:
                pass

    return None

# -----------------------------------------------------------------------------
# HTML METADATA & CONTENT EXTRACTOR
# -----------------------------------------------------------------------------
def extract_metadata_from_html(html: str) -> Optional[Dict[str, Any]]:
    """Extract Published Date, Author, Title, and Description from HTML soup."""
    if not html or is_cloudflare_blocked(html):
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    result = {
        "title": "",
        "published_at": None,
        "author": "",
        "description": ""
    }

    # 1. JSON-LD Extraction
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            if not script.string:
                continue
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                nodes = [item] + item.get("@graph", [])
                for node in nodes:
                    if not isinstance(node, dict):
                        continue

                    # Headline / Title
                    if not result["title"] and node.get("headline"):
                        result["title"] = str(node["headline"]).strip()

                    # Published Date
                    if not result["published_at"]:
                        for date_key in ("datePublished", "dateCreated", "uploadDate"):
                            if node.get(date_key):
                                parsed_d = parse_raw_datetime(str(node[date_key]))
                                if parsed_d:
                                    result["published_at"] = parsed_d
                                    break

                    # Author
                    if not result["author"] and node.get("author"):
                        auth = node["author"]
                        if isinstance(auth, dict):
                            result["author"] = auth.get("name", "")
                        elif isinstance(auth, list) and len(auth) > 0:
                            first_a = auth[0]
                            result["author"] = first_a.get("name", "") if isinstance(first_a, dict) else str(first_a)
                        elif isinstance(auth, str):
                            result["author"] = auth

                    # Description / Content
                    if not result["description"]:
                        if node.get("description"):
                            result["description"] = str(node["description"])[:800]
                        elif node.get("articleBody"):
                            result["description"] = str(node["articleBody"])[:800]
        except Exception:
            continue

    # 2. Meta Tags Extraction Fallbacks
    if not result["published_at"]:
        meta_props = [
            "article:published_time", "og:published_time", "datePublished",
            "pubdate", "publish_date", "date", "DC.date.issued", "sailthru.date"
        ]
        for prop in meta_props:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                parsed_d = parse_raw_datetime(tag["content"])
                if parsed_d:
                    result["published_at"] = parsed_d
                    break

    if not result["author"]:
        author_props = [
            "author", "article:author", "dc.creator", "sailthru.author", "byl",
            "twitter:creator", "parsely-author", "citation_author", "author-name"
        ]
        for prop in author_props:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                result["author"] = tag["content"].strip()
                break

    if not result["title"]:
        og_title = soup.find("meta", property="og:title") or soup.find("title")
        if og_title:
            result["title"] = og_title.get("content", "") or og_title.get_text(strip=True)

    if not result["description"]:
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            result["description"] = og_desc["content"][:800]

    # 3. HTML Element Fallbacks
    if not result["published_at"]:
        for time_tag in soup.find_all("time"):
            raw_t = time_tag.get("datetime") or time_tag.get_text(strip=True)
            if raw_t:
                parsed_d = parse_raw_datetime(raw_t)
                if parsed_d:
                    result["published_at"] = parsed_d
                    break

    if not result["author"]:
        author_element = soup.select_one(
            ".byline, .author, .byline-author, [itemprop='author'], .author-name, "
            "[rel='author'], .c-author, .article-author, .post-author, .byline__name, "
            ".entry-author, .vcard .fn, .author-link, a[href*='/author/']"
        )
        if author_element:
            result["author"] = author_element.get_text(strip=True)

    if not result["description"]:
        article_tag = soup.find("article")
        if article_tag:
            paras = [p.get_text(strip=True) for p in article_tag.find_all("p")[:5]]
            text = " ".join(p for p in paras if p)
            if text:
                result["description"] = text[:800]

    if not result["published_at"]:
        return None

    return result

# -----------------------------------------------------------------------------
# TIER 1: FAST HTTP SCRAPER WORKER
# -----------------------------------------------------------------------------
def tier1_http_worker(item: Dict[str, Any], session: requests.Session) -> Tuple[str, Dict[str, Any], Optional[str], Optional[Dict[str, Any]]]:
    google_url = item["google_url"]
    source = item["source"]

    decoded_url = decode_google_news_url(google_url)
    if not decoded_url:
        decoded_url = google_url

    domain = get_domain_from_url(decoded_url)
    item["decoded_url"] = decoded_url
    item["domain"] = domain

    # Check if domain belongs to heavy paywall / anti-bot sources
    if any(p in domain.lower() or p in source.lower() for p in config.PAYWALLED_SOURCES):
        return "route_to_stealth", item, decoded_url, None

    if "news.google.com" not in decoded_url:
        try:
            r = session.get(decoded_url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                meta = extract_metadata_from_html(r.text)
                if meta:
                    meta["time_tier"] = "tier1_http"
                    return "ok", item, decoded_url, meta
        except Exception:
            pass

    # Fast fallback metadata so pipeline finishes in minutes without hanging in browser queue
    fallback_meta = {
        "published_at": item["article_ref"].get("published", "") or datetime.now().strftime("%Y-%m-%d %I:%M:%S %p EST"),
        "author": "Unknown",
        "description": item["article_ref"].get("title", ""),
        "title": item["article_ref"].get("title", ""),
        "time_tier": "fast_fallback"
    }
    return "ok", item, decoded_url, fallback_meta



# -----------------------------------------------------------------------------
# TIER 3: STEALTH PLAYWRIGHT ENRICHER (BLOOMBERG / WSJ / anti-bot)
# -----------------------------------------------------------------------------
def run_tier3_playwright(items: List[Dict[str, Any]]):
    """Enrich heavy paywalled / anti-bot articles using Playwright."""
    if not items or not HAS_PLAYWRIGHT:
        return

    print(f"\n🎭 Starting Tier 3 Playwright Stealth Scraper for {len(items)} items...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York"
        )
        page = context.new_page()

        for idx, item in enumerate(items, 1):
            google_url = item["google_url"]
            decoded_url = item.get("decoded_url") or decode_google_news_url(google_url)
            source = item["source"]
            title = item.get("title", "")[:40]

            if not decoded_url:
                continue

            print(f"  [Playwright {idx}/{len(items)}] [{source}] {title}...")
            try:
                page.goto(decoded_url, wait_until="domcontentloaded", timeout=35000)
                time.sleep(random.uniform(1.5, 3))
                html = page.content()
                meta = extract_metadata_from_html(html)
                if meta:
                    meta["time_tier"] = "tier3_playwright"
                    update_article_data(item["article_ref"], google_url, page.url or decoded_url, meta)
                    print(f"    ✓ Extracted: {meta['published_at']} | Author: {meta.get('author','N/A')}")
                else:
                    fallback_meta = {
                        "published_at": item["article_ref"].get("published", "") or datetime.now().strftime("%Y-%m-%d %I:%M:%S %p EST"),
                        "author": "Unknown",
                        "description": item["article_ref"].get("title", ""),
                        "title": item["article_ref"].get("title", ""),
                        "time_tier": "tier3_fallback"
                    }
                    update_article_data(item["article_ref"], google_url, page.url or decoded_url, fallback_meta)
                    print(f"    ✓ Preserved (Fallback): {fallback_meta['published_at']}")
            except Exception as e:
                print(f"    ✗ Playwright error: {str(e)[:50]}")
                fallback_meta = {
                    "published_at": item["article_ref"].get("published", "") or datetime.now().strftime("%Y-%m-%d %I:%M:%S %p EST"),
                    "author": "Unknown",
                    "description": item["article_ref"].get("title", ""),
                    "title": item["article_ref"].get("title", ""),
                    "time_tier": "error_fallback"
                }
                update_article_data(item["article_ref"], google_url, decoded_url, fallback_meta)

        context.close()
        browser.close()

# -----------------------------------------------------------------------------
# STATE UPDATE & RECORD KEEPING
# -----------------------------------------------------------------------------
def update_article_data(article_ref: Dict[str, Any], google_url: str,
                        decoded_url: str, meta: Dict[str, Any]):
    """Update article dictionary with scraped metadata in a thread-safe manner."""
    with enrich_lock:
        article_ref["google_link"] = google_url
        article_ref["decoded_url"] = decoded_url
        article_ref["link"] = decoded_url
        article_ref["original_published_at"] = article_ref.get("published", "")
        article_ref["published_at"] = meta.get("published_at") or article_ref.get("published", "")
        article_ref["author"] = meta.get("author", "")
        article_ref["description"] = meta.get("description", "")
        article_ref["time_tier"] = meta.get("time_tier", "scraped")
        if meta.get("title") and not article_ref.get("title"):
            article_ref["title"] = meta["title"]
        article_ref.pop("published", None)
        article_ref.pop("query", None)

def record_failed_article(google_url: str, decoded_url: Optional[str],
                          source: str, title: str, error: str):
    """Record an un-enrichable article in failed list."""
    with enrich_lock:
        if google_url not in FAILED_SET:
            FAILED_SET.add(google_url)
            FAILED_LIST.append({
                "google_url": google_url,
                "decoded_url": decoded_url or "",
                "source": source,
                "title": title[:100],
                "error": error,
                "timestamp": datetime.now().isoformat()
            })

# -----------------------------------------------------------------------------
# MAIN ENRICHMENT ORCHESTRATOR
# -----------------------------------------------------------------------------
def run_enrichment_pipeline(input_file: str = config.RSS_OUTPUT_FILE,
                            output_file: str = config.ENRICH_OUTPUT_FILE):
    """Run Phase 2 Multi-tier Enrichment across raw collected URLs."""
    global URL_CACHE, FAILED_LIST, FAILED_SET, ENRICHED_DATA

    raw_data = load_json_file(input_file, {})
    if not raw_data or "articles" not in raw_data:
        print(f"❌ Input file {input_file} missing or invalid.")
        return

    URL_CACHE = load_json_file(config.CACHE_FILE, {})
    FAILED_LIST = load_json_file(config.FAILED_FILE, [])
    FAILED_SET = {f["google_url"] for f in FAILED_LIST}

    existing_enriched = load_json_file(output_file, {})
    enriched_articles_map = existing_enriched.get("articles", {}) if existing_enriched else {}

    # Build lookup map of already enriched items
    lookup = {}
    for src, art_list in enriched_articles_map.items():
        for art in art_list:
            g_link = art.get("google_link") or art.get("link")
            if g_link and art.get("published_at"):
                lookup[(src, g_link)] = art

    ENRICHED_DATA = {"metadata": raw_data.get("metadata", {}), "articles": {}}
    articles_to_process = []

    for source, art_list in raw_data.get("articles", {}).items():
        ENRICHED_DATA["articles"][source] = []
        for art in art_list:
            g_link = art.get("link", "")
            key = (source, g_link)
            if key in lookup:
                # Reuse existing enriched data
                prev = lookup[key]
                art["published_at"] = prev.get("published_at")
                art["author"] = prev.get("author", "")
                art["description"] = prev.get("description", "")
                art["decoded_url"] = prev.get("decoded_url", g_link)
                art["google_link"] = g_link
                art["time_tier"] = prev.get("time_tier", "cached")
                art.pop("published", None)
                art.pop("query", None)

            ENRICHED_DATA["articles"][source].append(art)

            if "published_at" not in art and g_link:
                articles_to_process.append({
                    "google_url": g_link,
                    "source": source,
                    "title": art.get("title", ""),
                    "article_ref": art
                })

    already_enriched_count = len(lookup)
    total_total = sum(len(v) for v in raw_data.get("articles", {}).values())

    print("=" * 80)
    print(f"⚡ PHASE 2: Multi-Tier Enrichment")
    print(f"💾 Loaded {already_enriched_count} already-enriched articles from saved progress!")
    print(f"🔄 Processing {len(articles_to_process)} remaining articles (out of {total_total} total)")
    print("=" * 80)

    if not articles_to_process:
        print("✅ All articles already enriched.")
        return

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(config.HEADERS)

    stealth_queue = []
    browser_queue = []
    success_count = 0

    print(f"🚀 Launching Tier 1 Fast HTTP Workers ({config.ENRICH_REQUESTS_WORKERS} threads)...")

    executor = ThreadPoolExecutor(max_workers=config.ENRICH_REQUESTS_WORKERS)
    try:
        futures = {executor.submit(tier1_http_worker, item, session): item for item in articles_to_process}
        for idx, future in enumerate(as_completed(futures), 1):
            status, item, decoded_url, meta = future.result()
            g_url = item["google_url"]
            src = item["source"]
            title = item["title"][:40]
            curr_pos = already_enriched_count + idx

            if status == "ok":
                update_article_data(item["article_ref"], g_url, decoded_url, meta)
                success_count += 1
                print(f"  [{curr_pos}/{total_total}] ✓ [{src}] {title} -> Date: {meta['published_at']}")
            elif status == "route_to_stealth":
                print(f"  [{curr_pos}/{total_total}] 🎭 [→ Playwright] [{src}] {title}")
                stealth_queue.append(item)
            elif status == "needs_browser":
                print(f"  [{curr_pos}/{total_total}] ⏳ [→ Browser] [{src}] {title}")
                browser_queue.append(item)
            else:
                print(f"  [{curr_pos}/{total_total}] ⏳ [→ Fallback] [{src}] {title}")
                browser_queue.append(item)

            if idx % config.ENRICH_SAVE_INTERVAL == 0:
                save_json_file(config.CACHE_FILE, URL_CACHE)
                save_enriched_progress(output_file, ENRICHED_DATA)

    except KeyboardInterrupt:
        print("\n⚠️ Enrichment interrupted. Saving progress...")
        save_json_file(config.CACHE_FILE, URL_CACHE)
        save_enriched_progress(output_file, ENRICHED_DATA)
        executor.shutdown(wait=False, cancel_futures=True)
        sys.exit(0)
    else:
        executor.shutdown(wait=True)

    save_json_file(config.CACHE_FILE, URL_CACHE)
    save_enriched_progress(output_file, ENRICHED_DATA)

    # Launch Playwright Stealth for Paywalled & Browser Queues
    all_browser_items = stealth_queue + browser_queue
    if all_browser_items:
        print(f"\n🎭 Launching Playwright Browser Tier for {len(all_browser_items)} items...")
        run_tier3_playwright(all_browser_items)
        save_enriched_progress(output_file, ENRICHED_DATA)

    save_json_file(config.FAILED_FILE, FAILED_LIST)
    print("=" * 80)
    print(f"✅ PHASE 2 ENRICHMENT COMPLETE! Enriched Files: {output_file} & {output_file.replace('.json', '.csv')}")
    print("=" * 80)



if __name__ == "__main__":
    run_enrichment_pipeline()
