-- promo-radar 数据库 schema（PRAGMA user_version = 10）

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
    also_seen_in       TEXT NOT NULL DEFAULT '[]',
    verified_at        TEXT NOT NULL DEFAULT '',
    verified_by        TEXT NOT NULL DEFAULT ''
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
    updated_at       TEXT NOT NULL DEFAULT '',
    -- v10：垂直领域与云资源属性
    vertical         TEXT NOT NULL DEFAULT 'ai_api',
    categories       TEXT NOT NULL DEFAULT '[]',
    deploy_modes     TEXT NOT NULL DEFAULT '[]',
    free_tier_url    TEXT NOT NULL DEFAULT '',
    pricing_url      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_providers_status ON providers (status);
CREATE INDEX IF NOT EXISTS idx_providers_category ON providers (category);
CREATE INDEX IF NOT EXISTS idx_providers_vertical ON providers (vertical);

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
    dedup_key     TEXT NOT NULL UNIQUE,
    -- v10：免费资源结构化字段
    vertical      TEXT NOT NULL DEFAULT 'ai_api',
    offer_type    TEXT NOT NULL DEFAULT 'credits',
    granularity   TEXT NOT NULL DEFAULT 'activity',
    category      TEXT NOT NULL DEFAULT '',
    resources     TEXT NOT NULL DEFAULT '{}',
    limits        TEXT NOT NULL DEFAULT '{}',
    eligibility   TEXT NOT NULL DEFAULT '{}',
    regions       TEXT NOT NULL DEFAULT '[]',
    claim_steps   TEXT NOT NULL DEFAULT '',
    difficulty    INTEGER NOT NULL DEFAULT 2,
    expires_at    TEXT NOT NULL DEFAULT '',
    terms_hash    TEXT NOT NULL DEFAULT '',
    last_verified_at TEXT NOT NULL DEFAULT '',
    verified_by   TEXT NOT NULL DEFAULT 'rule',
    status_reason TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    evidence      TEXT NOT NULL DEFAULT '',
    provider_name TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_offers_provider ON offers (provider_id);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers (status);
CREATE INDEX IF NOT EXISTS idx_offers_vertical ON offers (vertical);
CREATE INDEX IF NOT EXISTS idx_offers_type ON offers (offer_type);
CREATE INDEX IF NOT EXISTS idx_offers_expires ON offers (expires_at);

CREATE TABLE IF NOT EXISTS offer_evidence (
    offer_id  INTEGER NOT NULL,
    deal_key  TEXT NOT NULL,
    url       TEXT NOT NULL DEFAULT '',
    source    TEXT NOT NULL DEFAULT '',
    seen_at   TEXT NOT NULL DEFAULT '',
    -- v10：证据明细（吸收原 deals 的展示字段）
    title         TEXT NOT NULL DEFAULT '',
    evidence      TEXT NOT NULL DEFAULT '',
    amount_hint   TEXT NOT NULL DEFAULT '',
    matched       TEXT NOT NULL DEFAULT '[]',
    score         REAL NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL DEFAULT '',
    last_seen_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (offer_id, deal_key)
);
CREATE INDEX IF NOT EXISTS idx_offer_evidence_offer ON offer_evidence (offer_id);

-- v10：条款快照历史（terms_hash 变化时留档）
CREATE TABLE IF NOT EXISTS offer_terms_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id       INTEGER NOT NULL,
    terms_hash     TEXT NOT NULL,
    snapshot       TEXT NOT NULL DEFAULT '{}',
    changed_fields TEXT NOT NULL DEFAULT '[]',
    changed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_terms_offer ON offer_terms_history (offer_id, changed_at);

-- v10：信号事件（补货/售罄/新地区/降价/条款变更）
CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    vertical     TEXT NOT NULL DEFAULT 'ai_api',
    provider_id  INTEGER,
    offer_id     INTEGER,
    source       TEXT NOT NULL DEFAULT '',
    page_url     TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL DEFAULT '{}',
    observed_at  TEXT NOT NULL,
    notified_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_signals_time ON signals (observed_at);
CREATE INDEX IF NOT EXISTS idx_signals_kind ON signals (kind, observed_at);

-- v10：个人领取跟踪（serve 模式 / CLI），静态站用 localStorage
CREATE TABLE IF NOT EXISTS claims (
    offer_id    INTEGER PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'todo'
                CHECK (state IN ('todo', 'claimed', 'rejected', 'expired', 'skipped')),
    claimed_at  TEXT NOT NULL DEFAULT '',
    expires_at  TEXT NOT NULL DEFAULT '',
    account     TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
