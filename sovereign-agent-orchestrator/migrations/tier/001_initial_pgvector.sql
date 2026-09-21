-- Vector width must match the embedding model, i.e. RAG_EMBEDDING_DIMENSIONS.
-- It was hardcoded to 768 (nomic-embed-text) while the shipped configuration moved to
-- bge-m3 at 1024, so every chunk insert failed with a dimension error that named
-- neither the setting nor the column. Override for a different embedder with:
--     psql -v embedding_dim=768 -f 001_initial_pgvector.sql
\if :{?embedding_dim}
\else
\set embedding_dim 1024
\endif

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY,
    name VARCHAR(512) NOT NULL,
    mime_type VARCHAR(255),
    checksum CHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(:embedding_dim),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS rag_chunks_metadata_gin
    ON rag_chunks USING gin (metadata);
CREATE INDEX IF NOT EXISTS rag_documents_metadata_gin
    ON rag_documents USING gin (metadata);
CREATE INDEX IF NOT EXISTS rag_documents_checksum_idx
    ON rag_documents (checksum);