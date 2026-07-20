POSTGRES_EXTENSIONS_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
"""


SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    email_domain TEXT UNIQUE,
    name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_accounts (
    id TEXT PRIMARY KEY,
    auth_subject TEXT UNIQUE,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'super_admin')),
    state TEXT NOT NULL CHECK (state IN ('unclaimed', 'active')),
    personal_workspace_id TEXT UNIQUE,
    source TEXT NOT NULL CHECK (source IN ('signup', 'inbound_email')),
    claimed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (role = 'super_admin' AND personal_workspace_id IS NULL)
        OR (role = 'user' AND personal_workspace_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS platform_access_events (
    id TEXT PRIMARY KEY,
    actor_account_id TEXT NOT NULL,
    target_account_id TEXT,
    workspace_id TEXT,
    contract_id TEXT,
    event_type TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_user_accounts_role_state
ON user_accounts(role, state, created_at);

CREATE INDEX IF NOT EXISTS ix_platform_access_events_actor_created
ON platform_access_events(actor_account_id, created_at);

CREATE INDEX IF NOT EXISTS ix_platform_access_events_target_created
ON platform_access_events(target_account_id, created_at);

CREATE TABLE IF NOT EXISTS email_threads (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    subject TEXT,
    from_address TEXT NOT NULL,
    agno_session_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inbound_email_events (
    id TEXT PRIMARY KEY,
    email_message_id TEXT NOT NULL UNIQUE,
    workspace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    email_thread_id TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    current_version_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contract_versions (
    id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    s3_object_key TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(contract_id, version_number)
);

CREATE TABLE IF NOT EXISTS parsed_documents (
    id TEXT PRIMARY KEY,
    contract_version_id TEXT NOT NULL UNIQUE,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    requires_ocr INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contract_reviews (
    id TEXT PRIMARY KEY,
    contract_version_id TEXT NOT NULL UNIQUE,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    review_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_indexes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions = 1024),
    reranker_provider TEXT NOT NULL,
    reranker_model TEXT NOT NULL,
    chunking_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'indexing', 'ready', 'failed')),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error_message TEXT,
    indexed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, contract_version_id, embedding_model, chunking_version)
);

CREATE TABLE IF NOT EXISTS knowledge_index_outbox (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'publishing', 'published', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_expires_at TEXT,
    last_error TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, contract_version_id)
);

CREATE INDEX IF NOT EXISTS ix_knowledge_outbox_delivery
ON knowledge_index_outbox(status, next_attempt_at, lease_expires_at);

CREATE INDEX IF NOT EXISTS ix_knowledge_outbox_workspace_contract
ON knowledge_index_outbox(workspace_id, contract_id, contract_version_id);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    knowledge_index_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(knowledge_index_id, ordinal),
    UNIQUE(knowledge_index_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS ix_knowledge_indexes_workspace_status
ON knowledge_indexes(workspace_id, status, updated_at);

CREATE INDEX IF NOT EXISTS ix_knowledge_indexes_workspace_contract
ON knowledge_indexes(workspace_id, contract_id, contract_version_id);

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_workspace_contract
ON knowledge_chunks(workspace_id, contract_id, contract_version_id, ordinal);

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_index_ordinal
ON knowledge_chunks(knowledge_index_id, ordinal);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    contract_id TEXT,
    title TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1),
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content TEXT NOT NULL,
    citations TEXT NOT NULL DEFAULT '[]',
    model_provider TEXT,
    model_name TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_workspace_account_updated
ON chat_sessions(workspace_id, account_id, updated_at);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_workspace_contract_updated
ON chat_sessions(workspace_id, contract_id, updated_at);

CREATE INDEX IF NOT EXISTS ix_chat_messages_workspace_session_created
ON chat_messages(workspace_id, session_id, sequence_number);

CREATE TABLE IF NOT EXISTS proposed_actions (
    id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    proposed_action_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    comment TEXT,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    event_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signing_requests (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS signers (
    id TEXT PRIMARY KEY,
    signing_request_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT,
    required INTEGER NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signer_status_events (
    id TEXT PRIMARY KEY,
    signer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    actor_email TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_signing_requests_active_contract
ON signing_requests(contract_id)
WHERE active = 1;

CREATE INDEX IF NOT EXISTS ix_signing_requests_workspace_contract
ON signing_requests(workspace_id, contract_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_signers_request_email
ON signers(signing_request_id, lower(email));

CREATE INDEX IF NOT EXISTS ix_signers_request_order
ON signers(signing_request_id, display_order);

CREATE INDEX IF NOT EXISTS ix_signer_status_events_signer_created
ON signer_status_events(signer_id, created_at);
"""


POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    email_domain TEXT UNIQUE,
    name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_accounts (
    id TEXT PRIMARY KEY,
    auth_subject TEXT UNIQUE,
    email TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'super_admin')),
    state TEXT NOT NULL CHECK (state IN ('unclaimed', 'active')),
    personal_workspace_id TEXT UNIQUE,
    source TEXT NOT NULL CHECK (source IN ('signup', 'inbound_email')),
    claimed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (role = 'super_admin' AND personal_workspace_id IS NULL)
        OR (role = 'user' AND personal_workspace_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_accounts_email_normalized
ON user_accounts(lower(email));

CREATE TABLE IF NOT EXISTS platform_access_events (
    id TEXT PRIMARY KEY,
    actor_account_id TEXT NOT NULL,
    target_account_id TEXT,
    workspace_id TEXT,
    contract_id TEXT,
    event_type TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_user_accounts_role_state
ON user_accounts(role, state, created_at);

CREATE INDEX IF NOT EXISTS ix_platform_access_events_actor_created
ON platform_access_events(actor_account_id, created_at);

CREATE INDEX IF NOT EXISTS ix_platform_access_events_target_created
ON platform_access_events(target_account_id, created_at);

CREATE TABLE IF NOT EXISTS email_threads (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    subject TEXT,
    from_address TEXT NOT NULL,
    agno_session_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inbound_email_events (
    id TEXT PRIMARY KEY,
    email_message_id TEXT NOT NULL UNIQUE,
    workspace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    email_thread_id TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    current_version_id TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contract_versions (
    id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    s3_object_key TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(contract_id, version_number)
);

CREATE TABLE IF NOT EXISTS parsed_documents (
    id TEXT PRIMARY KEY,
    contract_version_id TEXT NOT NULL UNIQUE,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    requires_ocr BOOLEAN NOT NULL,
    content_json JSONB NOT NULL,
    warnings_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contract_reviews (
    id TEXT PRIMARY KEY,
    contract_version_id TEXT NOT NULL UNIQUE,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    review_json JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_indexes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions = 1024),
    reranker_provider TEXT NOT NULL,
    reranker_model TEXT NOT NULL,
    chunking_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'indexing', 'ready', 'failed')),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error_message TEXT,
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, contract_version_id, embedding_model, chunking_version)
);

CREATE TABLE IF NOT EXISTS knowledge_index_outbox (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'publishing', 'published', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, contract_version_id)
);

CREATE INDEX IF NOT EXISTS ix_knowledge_outbox_delivery
ON knowledge_index_outbox(status, next_attempt_at, lease_expires_at);

CREATE INDEX IF NOT EXISTS ix_knowledge_outbox_workspace_contract
ON knowledge_index_outbox(workspace_id, contract_id, contract_version_id);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    knowledge_index_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1024) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(knowledge_index_id, ordinal),
    UNIQUE(knowledge_index_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS ix_knowledge_indexes_workspace_status
ON knowledge_indexes(workspace_id, status, updated_at);

CREATE INDEX IF NOT EXISTS ix_knowledge_indexes_workspace_contract
ON knowledge_indexes(workspace_id, contract_id, contract_version_id);

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_workspace_contract
ON knowledge_chunks(workspace_id, contract_id, contract_version_id, ordinal);

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_index_ordinal
ON knowledge_chunks(knowledge_index_id, ordinal);

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_search_vector
ON knowledge_chunks USING GIN(search_vector);

CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw
ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    contract_id TEXT,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1),
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_provider TEXT,
    model_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_workspace_account_updated
ON chat_sessions(workspace_id, account_id, updated_at);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_workspace_contract_updated
ON chat_sessions(workspace_id, contract_id, updated_at);

CREATE INDEX IF NOT EXISTS ix_chat_messages_workspace_session_created
ON chat_messages(workspace_id, session_id, sequence_number);

CREATE TABLE IF NOT EXISTS proposed_actions (
    id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    proposed_action_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    comment TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    event_type TEXT NOT NULL,
    metadata_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signing_requests (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_version_id TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS signers (
    id TEXT PRIMARY KEY,
    signing_request_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signer_status_events (
    id TEXT PRIMARY KEY,
    signer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    actor_email TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_signing_requests_active_contract
ON signing_requests(contract_id)
WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS ix_signing_requests_workspace_contract
ON signing_requests(workspace_id, contract_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_signers_request_email
ON signers(signing_request_id, lower(email));

CREATE INDEX IF NOT EXISTS ix_signers_request_order
ON signers(signing_request_id, display_order);

CREATE INDEX IF NOT EXISTS ix_signer_status_events_signer_created
ON signer_status_events(signer_id, created_at);
"""
