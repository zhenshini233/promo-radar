-- promo-radar 数据库 schema（PRAGMA user_version = 3）

CREATE TABLE IF NOT EXISTS deals (
    dedup_key          TEXT PRIMARY KEY,
    source             TEXT NOT NULL,
    title              TEXT NOT NULL,
    url                TEXT DEFAULT '',
    provider           TEXT,
    amount_hint        TEXT,
    card_required_hint INTEGER,
    score              REAL DEFAULT 0,
    evidence           TEXT DEFAULT '',
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    last_changed_at    TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'new',
    matched            TEXT NOT NULL DEFAULT '[]',
    also_seen_in       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_deals_last_seen ON deals (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_deals_status ON deals (status);

-- 模糊合并的吸收关系：转发帖 key → 主条目 key。
-- 之后的 sighting 经别名直达主条目，视为"见到"而非"内容变化"（幂等）。
CREATE TABLE IF NOT EXISTS aliases (
    aliased_key TEXT PRIMARY KEY,
    master_key  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aliases_master ON aliases (master_key);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT NOT NULL,
    new_deals     INTEGER DEFAULT 0,
    updated_deals INTEGER DEFAULT 0,
    errors        INTEGER DEFAULT 0,
    expired       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_runs (
    run_id     INTEGER NOT NULL,
    source     TEXT NOT NULL,
    status     TEXT NOT NULL,
    fetched    INTEGER DEFAULT 0,
    kept       INTEGER DEFAULT 0,
    new        INTEGER DEFAULT 0,
    updated    INTEGER DEFAULT 0,
    error      TEXT DEFAULT '',
    elapsed_ms INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snapshots (
    url             TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    label           TEXT DEFAULT '',
    content_hash    TEXT NOT NULL,
    promo_keywords  TEXT DEFAULT '',
    last_checked_at TEXT NOT NULL,
    last_changed_at TEXT NOT NULL
);

-- 每轮每页一条，支撑 dashboard 的"信号历史条形带"（upptime 模式）
CREATE TABLE IF NOT EXISTS snapshot_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL,
    checked_at     TEXT NOT NULL,
    promo_keywords TEXT DEFAULT '',
    changed        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_history_url_time ON snapshot_history (url, checked_at);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
