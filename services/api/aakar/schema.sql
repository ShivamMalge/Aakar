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

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS corpora (
    id         TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_corpora_owner ON corpora(owner_id);

CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    corpus_id    TEXT NOT NULL REFERENCES corpora(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    page_count   INTEGER,
    storage_path TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_owner_hash ON documents(owner_id, content_hash);

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
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_qa_cache_owner ON qa_cache_meta(owner_id);
CREATE INDEX IF NOT EXISTS idx_qa_cache_scope ON qa_cache_meta(corpus_id, topic_id, part_id);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');
