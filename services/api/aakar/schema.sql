-- Aakar bookkeeping (spec §3, task 0.5).
--
-- D-011: v1 has exactly one owner, but every user-scoped table carries owner_id from
-- day one so vNext multi-user is a policy change rather than a migration. Nothing here
-- assumes a single row in users.
--
-- D-007: qa_cache_meta carries corpus_id. The semantic answer cache is scoped
-- (corpus_id, topic, part) — one owner can upload two chapters on the same topic, so
-- document identity must be part of the key. The column is NOT NULL to keep that
-- structural rather than conventional.
--
-- D-029 (Phase 2A): `corpora` is CONTENT-ADDRESSED AND OWNERLESS. Content-hash dedupe and
-- `corpora.owner_id` are incompatible, so ownership moved to `corpus_grants` and access is
-- by grant, never by ownership. Sharing keys on a hash of the raw bytes, so byte-identical
-- files dedupe and nothing else can: a private document has a unique hash and is isolated
-- structurally, with no allow-list and no exception path.
--
-- Ruling (e): a grant's holder is an owner OR a group, never both and never neither. The
-- group tables exist so shared-classroom access is a later feature rather than a migration
-- through every access path. No routes, no tier logic, no UI — schema shape only.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Ownerless by design (D-029). Keyed by a hash of the raw file bytes, so two owners who
-- upload the same file share one row, one parse and one embedding cost.
CREATE TABLE IF NOT EXISTS corpora (
    id           TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_corpora_hash ON corpora(content_hash);

-- Principals a grant can be held by. No routes in 2A; the shape exists so classroom
-- sharing is a feature rather than a migration through every access path (ruling e).
CREATE TABLE IF NOT EXISTS groups (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id  TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members(user_id);

-- Access is by grant, never by ownership (D-029). Exactly one of owner_id / group_id is
-- set — the CHECK makes "granted to nobody" and "granted to both" unrepresentable rather
-- than merely discouraged.
CREATE TABLE IF NOT EXISTS corpus_grants (
    id         TEXT PRIMARY KEY,
    corpus_id  TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    owner_id   TEXT REFERENCES users(id) ON DELETE CASCADE,
    group_id   TEXT REFERENCES groups(id) ON DELETE CASCADE,
    granted_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ((owner_id IS NOT NULL) + (group_id IS NOT NULL) = 1)
);
CREATE INDEX IF NOT EXISTS idx_corpus_grants_owner ON corpus_grants(owner_id);
CREATE INDEX IF NOT EXISTS idx_corpus_grants_group ON corpus_grants(group_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_corpus_grants_owner_unique
    ON corpus_grants(corpus_id, owner_id) WHERE owner_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_corpus_grants_group_unique
    ON corpus_grants(corpus_id, group_id) WHERE group_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    corpus_id    TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    -- Page counts are stored as both a LABEL and an INDEX everywhere downstream (2A.6);
    -- this is the physical count, which is the index space.
    page_count   INTEGER,
    -- LightningParse's per-DOCUMENT extraction tier ('digital' | 'scanned'). Measured,
    -- not assumed: see aakar/ingest/parser.py for what 0.4.1 actually emits.
    parse_tier   TEXT,
    storage_path TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_owner_hash ON documents(owner_id, content_hash);

-- 2A.5 / 2A.6. Belongs to a corpus, not to an owner: the corpus is content-addressed and
-- shared, so its chunks are too. Reachable only through a grant.
--
-- page_index and page_label are SEPARATE COLUMNS and neither is derived from the other
-- (2A.6). They diverge on any document with front matter. Citations render the label;
-- addressing uses the index.
--
-- warnings_json holds whatever the parser reported about THIS chunk. Provenance strength
-- in the UI derives from it. See aakar/ingest/chunks.py for what is and is not known
-- about its granularity today.
-- The page map, stored rather than recomputed (2A.6). Labels come from the PDF at the
-- boundary; the worker must not re-derive them, because a re-derivation that disagrees
-- with the one the limits were checked against is a silent inconsistency.
CREATE TABLE IF NOT EXISTS document_pages (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_index  INTEGER NOT NULL,
    page_label  TEXT NOT NULL,
    PRIMARY KEY (document_id, page_index)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    corpus_id     TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       INTEGER NOT NULL,
    page_index    INTEGER NOT NULL,
    page_label    TEXT NOT NULL,
    section       TEXT,
    text          TEXT NOT NULL,
    -- 2A.5, ANSWERED. LightningParse 0.4.1 emits NO warnings array; this was measured,
    -- not assumed. What it does emit is `block.source` (per BLOCK, finer than per-chunk)
    -- and `metadata.tier` (per document). `source` is stored here at block granularity,
    -- which is the finest available.
    source        TEXT NOT NULL DEFAULT 'unknown',
    -- Kept for the day the parser gains a warnings array. `scope` records what a
    -- populated value would describe, so a parser upgrade cannot silently reinterpret it.
    warnings_json TEXT NOT NULL DEFAULT '[]',
    warning_scope TEXT NOT NULL DEFAULT 'none'
        CHECK (warning_scope IN ('block', 'chunk', 'document', 'none', 'unknown')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_corpus ON chunks(corpus_id);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(document_id, page_index);

-- D-034: ingest is ASYNCHRONOUS. max_ocr_pages 40 at ~25 s/page is ~17 minutes for one
-- upload, and no HTTP request survives that, so ingest cannot be request/response.
--
-- The boundary checks stay SYNCHRONOUS: a rejection is never asynchronous, because the
-- student must find out at upload rather than minutes later. Only accepted work is queued.
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id             TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    owner_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status         TEXT NOT NULL
                   CHECK (status IN ('queued','running','succeeded','failed','rejected')),
    -- Real progress, written as work completes (D-034). Never interpolated from elapsed
    -- time: a progress bar that moves while nothing happens is worse than none.
    pages_done     INTEGER NOT NULL DEFAULT 0,
    pages_total    INTEGER NOT NULL,
    failure_reason TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    started_at     TEXT,
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_owner ON ingest_jobs(owner_id);
-- The worker claims by (status, created_at); the global bound counts by status.
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_queue ON ingest_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS topics (
    id         TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    corpus_id  TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    slug       TEXT NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (owner_id, corpus_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_topics_owner ON topics(owner_id);

-- D3: every generation attempt is stored, approved or not. That audit trail is the point.
CREATE TABLE IF NOT EXISTS spec_versions (
    id               TEXT PRIMARY KEY,
    owner_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id         TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    attempt          INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL CHECK (status IN ('draft','needs_human','approved','rejected')),
    spec_json        TEXT NOT NULL,
    critique_json    TEXT,
    screenshot_paths TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (topic_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_spec_versions_owner ON spec_versions(owner_id);
CREATE INDEX IF NOT EXISTS idx_spec_versions_status ON spec_versions(topic_id, status);

CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    owner_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spec_version_id TEXT NOT NULL REFERENCES spec_versions(id) ON DELETE CASCADE,
    decision        TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_approvals_owner ON approvals(owner_id);

-- Cost log (D8). Phase 1 asserts this table is empty: zero LLM calls before Phase 2.
CREATE TABLE IF NOT EXISTS llm_calls (
    id                TEXT PRIMARY KEY,
    owner_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL CHECK (kind IN ('chat','vlm','embedding')),
    -- 2B.8. Recorded rather than inferred from the model name: a deployment that
    -- configures one model for both tiers must still produce a truthful split, because
    -- the split is what says whether a rising bill means more topics or more readers.
    tier              TEXT CHECK (tier IN ('generation','answer')),
    model             TEXT NOT NULL,
    mode              TEXT NOT NULL CHECK (mode IN ('live','record','replay')),
    cache_hit         INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    usd               REAL NOT NULL DEFAULT 0.0,
    topic_id          TEXT REFERENCES topics(id) ON DELETE SET NULL,
    request_hash      TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_owner ON llm_calls(owner_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_topic ON llm_calls(topic_id);

-- Bookkeeping only; the vectors live in Qdrant.
CREATE TABLE IF NOT EXISTS qa_cache_meta (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    corpus_id   TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    topic_id    TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    part_id     TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer_json TEXT NOT NULL,
    vector_id   TEXT NOT NULL,
    -- The question embedding, stored beside the bookkeeping so a cache lookup does not
    -- need Qdrant to be up. Qdrant remains the index for CHUNK retrieval; this set is
    -- small and per-(corpus, scope), and keeping it here is what lets cached answers keep
    -- serving in degraded mode (2B.11).
    vector_json TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_qa_cache_owner ON qa_cache_meta(owner_id);
CREATE INDEX IF NOT EXISTS idx_qa_cache_scope ON qa_cache_meta(corpus_id, topic_id, part_id);

-- 2B.12. Beyond the account ceiling a signup is recorded, not refused: a refusal loses
-- the person, a waitlist costs one row.
CREATE TABLE IF NOT EXISTS waitlist (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    position   INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '2');
