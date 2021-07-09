PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS feeds (
    name TEXT NOT NULL,
    channel_id INTEGER NOT NULL UNIQUE,
    guild_id INTEGER NOT NULL,
    url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    feed_name TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    entry_id INTEGER NOT NULL,
    updated TEXT NOT NULL,
    PRIMARY KEY (entry_id, channel_id)
);