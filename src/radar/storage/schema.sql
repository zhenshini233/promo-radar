-- promo-radar 数据库 schema（PRAGMA user_version = 8）

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
    last_changed_at TEXT NOT NULL,
    -- 连续抓取失败次数：>=3 时熔断 7 天，成功后清零（防止 360 页里少数
    -- 死链每轮都重试，把整轮拖到 CI 超时）
    fail_count      INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT NOT NULL DEFAULT '',
    -- 分层调度：1 每日 / 2 每周 / 3 每月；next_check_at 为空时按域名 hash 错峰
    tier            INTEGER NOT NULL DEFAULT 2,
    next_check_at   TEXT NOT NULL DEFAULT ''
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

-- 用户对 deal 的反馈：up=已薅/有价值，down=误报，snooze=暂时不关心。
-- 一个 deal 只留最新一次反馈（可改主意），用于反哺 scoring 与关键词复盘。
CREATE TABLE IF NOT EXISTS feedback (
    dedup_key TEXT PRIMARY KEY,
    vote      TEXT NOT NULL CHECK (vote IN ('up', 'down', 'snooze')),
    note      TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- v7：Provider 实体（厂商宇宙落库）。旧表不变，deals/snapshots 仍按 provider 文本关联。
CREATE TABLE IF NOT EXISTS providers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    slug             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'unknown',
    regions          TEXT NOT NULL DEFAULT '[]',
    relevance        REAL NOT NULL DEFAULT 0,
    confidence       TEXT NOT NULL DEFAULT 'low',
    status           TEXT NOT NULL DEFAULT 'in_universe'
                     CHECK (status IN ('in_universe', 'monitored', 'pending', 'ignored', 'retired')),
    vendor_like      INTEGER NOT NULL DEFAULT 1,
    brand_key        TEXT NOT NULL DEFAULT '',
    parent_id        INTEGER,
    first_seen_at    TEXT NOT NULL DEFAULT '',
    last_verified_at TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_providers_status ON providers (status);
CREATE INDEX IF NOT EXISTS idx_providers_category ON providers (category);

-- 一个注册域只属于一个 primary provider；子品牌不重复占域名。
CREATE TABLE IF NOT EXISTS provider_domains (
    domain      TEXT PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_provider_domains_pid ON provider_domains (provider_id);

-- 来源写法 / 旧名 / 模型前缀 → 统一到 provider。
CREATE TABLE IF NOT EXISTS provider_aliases (
    alias       TEXT PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'name'
);
CREATE INDEX IF NOT EXISTS idx_provider_aliases_pid ON provider_aliases (provider_id);

-- 该厂商被哪些发现来源收录。
CREATE TABLE IF NOT EXISTS provider_sources (
    provider_id   INTEGER NOT NULL,
    source        TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT '',
    last_seen_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (provider_id, source)
);

-- v8：Offer 层。offer = 厂商的一个促销活动；deals 是它的证据。
CREATE TABLE IF NOT EXISTS offers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id   INTEGER,
    title         TEXT NOT NULL,
    amount_hint   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'expired', 'unknown')),
    first_seen_at TEXT NOT NULL DEFAULT '',
    last_seen_at  TEXT NOT NULL DEFAULT '',
    dedup_key     TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_offers_provider ON offers (provider_id);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers (status);

CREATE TABLE IF NOT EXISTS offer_evidence (
    offer_id  INTEGER NOT NULL,
    deal_key  TEXT NOT NULL,
    url       TEXT NOT NULL DEFAULT '',
    source    TEXT NOT NULL DEFAULT '',
    seen_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (offer_id, deal_key)
);
CREATE INDEX IF NOT EXISTS idx_offer_evidence_offer ON offer_evidence (offer_id);
