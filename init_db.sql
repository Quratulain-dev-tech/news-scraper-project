-- =============================================================================
--  POSTGRESQL SCHEMA FOR NEWS ARTICLES PIPELINE
-- =============================================================================

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

-- Create Indexes for fast querying
CREATE INDEX IF NOT EXISTS idx_news_articles_url ON news_articles(url);
CREATE INDEX IF NOT EXISTS idx_news_articles_source ON news_articles(source);
CREATE INDEX IF NOT EXISTS idx_news_articles_published_date ON news_articles(published_date);
CREATE INDEX IF NOT EXISTS idx_news_articles_author ON news_articles(author);
