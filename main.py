# =============================================================================
#  NEWS SCRAPING, ENRICHMENT & PREPROCESSING MASTER PIPELINE
# =============================================================================
import os
import sys
import argparse
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import config
from rss_scraper import load_sources, scrape_rss_sources
from enricher import run_enrichment_pipeline
from preprocessor import preprocess_and_clean_dataset
from exporter import export_to_json, export_to_csv, export_to_postgres, export_all

def main():
    parser = argparse.ArgumentParser(description="Google News Scraping & Preprocessing Pipeline (10,000 Articles / 200 Sources)")
    parser.add_argument("--phase", choices=["all", "rss", "enrich", "clean", "export-db"], default="all",
                        help="Phase of the pipeline to run (default: all)")
    parser.add_argument("--all", action="store_true", help="Run full pipeline (all phases)")
    parser.add_argument("--sources-limit", type=int, default=config.MAX_SOURCES,
                        help=f"Max sources to process (default: {config.MAX_SOURCES})")
    parser.add_argument("--articles-per-source", type=int, default=config.ARTICLES_PER_SOURCE,
                        help=f"Target articles per source (default: {config.ARTICLES_PER_SOURCE})")
    parser.add_argument("--postgres", action="store_true", help="Also export clean data to PostgreSQL DB")
    args = parser.parse_args()

    start_time = datetime.now()
    print("=" * 80)
    print("📰 NEWS PIPELINE STARTING")
    print(f"⏰ Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Configuration: {args.sources_limit} Sources × {args.articles_per_source} Articles = Target ~{args.sources_limit * args.articles_per_source} Total URLs")
    print("=" * 80)

    # 1. PHASE 1: RSS URL COLLECTION
    if args.phase in ["all", "rss"]:
        print("\n▶️ [STEP 1/4] Starting Phase 1: RSS URL Collection...")
        sources = load_sources(config.SOURCES_FILE)
        scrape_rss_sources(
            sources=sources,
            articles_per_source=args.articles_per_source,
            max_sources=args.sources_limit,
            output_file=config.RSS_OUTPUT_FILE,
            workers=config.RSS_WORKERS,
            resume=True
        )

    # 2. PHASE 2: MULTI-TIER ENRICHMENT
    if args.phase in ["all", "enrich"]:
        print("\n▶️ [STEP 2/4] Starting Phase 2: Multi-Tier Enrichment...")
        run_enrichment_pipeline(
            input_file=config.RSS_OUTPUT_FILE,
            output_file=config.ENRICH_OUTPUT_FILE
        )

    # 3. PHASE 3 & 4: PREPROCESSING & EXPORT
    if args.phase in ["all", "clean", "export-db"]:
        print("\n▶️ [STEP 3/4] Starting Phase 3: Preprocessing & Cleaning...")
        cleaned_articles = preprocess_and_clean_dataset(input_file=config.ENRICH_OUTPUT_FILE)

        if cleaned_articles:
            print("\n▶️ [STEP 4/4] Starting Phase 4: Exporting Cleaned Data...")
            export_all(cleaned_articles)

            if args.postgres or args.phase == "export-db":
                export_to_postgres(cleaned_articles)
        else:
            print("⚠️ No cleaned articles found to export.")

    end_time = datetime.now()
    duration = end_time - start_time
    print("\n" + "=" * 80)
    print("🎉 PIPELINE RUN COMPLETE")
    print(f"⏱️ Total Execution Time: {duration}")
    print(f"📁 Raw Data File      : {config.RSS_OUTPUT_FILE}")
    print(f"📁 Enriched Data File : {config.ENRICH_OUTPUT_FILE}")
    print(f"💾 Cleaned JSON File  : {config.CLEANED_JSON_FILE}")
    print(f"📄 Cleaned CSV File   : {config.CLEANED_CSV_FILE}")
    print("=" * 80)

if __name__ == "__main__":
    main()
