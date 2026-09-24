CREATE TABLE IF NOT EXISTS jobs (id VARCHAR(255) PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS events (id BIGSERIAL PRIMARY KEY, job_id VARCHAR(255) NOT NULL, type VARCHAR(255) NOT NULL, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS approvals (id BIGSERIAL PRIMARY KEY, job_id VARCHAR(255) NOT NULL, approved BOOLEAN NOT NULL, reviewer VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS files (id VARCHAR(255) PRIMARY KEY, owner_id VARCHAR(255) NOT NULL, tenant_id VARCHAR(255) NOT NULL, name VARCHAR(512) NOT NULL, path TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}', created_at VARCHAR(255));
-- Added after the table shipped, so existing databases need the column too.
ALTER TABLE files ADD COLUMN IF NOT EXISTS created_at VARCHAR(255);
CREATE TABLE IF NOT EXISTS audit_events (id BIGSERIAL PRIMARY KEY, actor_id VARCHAR(255), tenant_id VARCHAR(255), action VARCHAR(255) NOT NULL, resource VARCHAR(255), data JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS job_queue (job_id VARCHAR(255) PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE, status VARCHAR(32) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS events_job_id_idx ON events(job_id, id);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs USING gin(data);
CREATE TABLE IF NOT EXISTS conversations (
	id VARCHAR(255) PRIMARY KEY,
	tenant_id VARCHAR(255) NOT NULL,
	owner_id VARCHAR(255) NOT NULL,
	title VARCHAR(512) NOT NULL,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
	updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
	archived BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS messages (
	id VARCHAR(255) PRIMARY KEY,
	conversation_id VARCHAR(255) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
	role VARCHAR(32) NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
	content TEXT NOT NULL,
	citations JSONB NOT NULL DEFAULT '[]',
	created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_tenant_updated_idx ON conversations(tenant_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS messages_conversation_id_idx ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS file_shares (
	id VARCHAR(255) PRIMARY KEY,
	file_id VARCHAR(255) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
	tenant_id VARCHAR(255) NOT NULL,
	shared_with_user_id VARCHAR(255) NOT NULL,
	permission VARCHAR(32) NOT NULL DEFAULT 'read',
	expires_at TIMESTAMPTZ,
	revoked BOOLEAN NOT NULL DEFAULT FALSE,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS file_shares_access_idx ON file_shares(file_id, shared_with_user_id, revoked);