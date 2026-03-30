SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS listings_seen (
    url_normalized TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_seen_at ON listings_seen(seen_at);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_message_id INTEGER,
    mode TEXT NOT NULL,
    listing_url TEXT,
    caption TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    post_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts(id)
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

CREATE TABLE IF NOT EXISTS auto_batches (
    id TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    filters_json TEXT NOT NULL,
    items_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
