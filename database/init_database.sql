PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS feeds (
    name TEXT UNIQUE,
    url TEXT NOT NULL,
    channel INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    entry_id INTEGER,
    feed_name TEXT,
    updated TEXT
);