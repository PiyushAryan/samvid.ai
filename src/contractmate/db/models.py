SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    email_domain TEXT UNIQUE,
    name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

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
