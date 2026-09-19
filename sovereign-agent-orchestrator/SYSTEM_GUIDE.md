# Sovereign Agent Orchestrator

Authoritative design, API, deployment, security, and operations guide for the local multi-user document intelligence server.

## 1. What It Does

The system is an offline-capable document AI backend and agent runtime for an organization. It provides:

- Multi-user conversations with durable history.
- Private document uploads and explicit document sharing.
- Text-only, document-only, and text-plus-document queries.
- Local document extraction for TXT, Markdown, PDF, DOCX, PPTX, CSV, XLSX, XLSM, and common images.
- Local OCR and optional local vision transcription, including page-by-page OCR of image-only / scanned PDFs, and a vision fallback when Tesseract returns unusable output.
- Direct vision reading of images attached to a task, independent of what OCR indexed for them.
- **Physically isolated RAG tiers**: admin / higher / lower, each its own database, with a downward-only read cascade (section 6A).
- Tenant, conversation, and attachment retrieval boundaries on top of the tier boundary.
- PostgreSQL plus pgvector for production; SQLite for development.
- **A multi-model local backend.** `config/models.yaml` holds several Ollama model
  profiles; a deterministic task router classifies each task and the orchestrator
  serves it with a matching model (coder for code, vision for scanned documents,
  reasoner for everything else), plus the embedding model and, when needed, the
  vision model within the same job. New models are added by editing the YAML, not
  the code.
- **An agent workflow**, not single-shot answering: retrieve → route to a model →
  build a task-type-specific plan → run policy-controlled local tools → verify →
  deliver, and re-plan up to `MAX_ITERATIONS` when verification fails.
- **Real deliverables**: `.docx` (approval notes, summaries, analyses, worked
  calculations), `.xlsx`, `.pptx`, and source files for coding tasks.
- **Sandboxed code execution**: generated Python is run in a no-network sandbox
  (nsjail / bwrap / firejail on Linux, `sandbox-exec` on macOS, resource-limit
  floor everywhere) and its exit code gates verification for coding tasks.
- Stable citations containing source document, document ID, chunk ID, score, quote, and retrieval method.
- Durable jobs, SSE progress events, approval policy, generated artifacts, and audit events.
- A separate API and worker deployment model for concurrent users.

This system can run without public internet after container images, Python packages, and local model files have been provisioned. Model quality is determined by the selected local model and available CPU/GPU resources.

## 2. Request Flow

```text
UI
  -> authenticated API request
  -> conversation and attachment authorization
  -> document upload/index or existing file lookup
  -> retrieval scope = the RAG tiers this role may read, filtered by tenant
  -> if attachments exist: retrieval scope = attached file IDs only
     (attachments are resolved through the file surface, so owner/share applies there)
  -> recent conversation history + retrieved evidence
  -> local Ollama model
  -> structured citations persisted with assistant message
  -> queued job status and SSE events
```

Two different boundaries operate here and they must not be confused.

**The file surface** (`GET /files`, download, and attaching a file to a job) is
owner-scoped: a file is reachable when the caller owns it, holds an active unexpired
share, or is an administrator, all within one tenant.

**RAG retrieval** (`/knowledge/search` and the `search_documents` tool) is *not*
owner-scoped. Authorization is tier membership: the query runs against the tier
databases the caller's role may read, filtered by tenant. Everything inside a readable
tier is, by design, readable by that role — two `lower` users in the same tenant can
retrieve each other's indexed content. Isolation between users of the same tier is not
a property this system provides; isolation between tiers is, and it is physical.

Attachment queries are narrower than either: they search only the supplied file IDs,
and because attachments are resolved through the file surface, owner and share rules do
apply to what can be attached in the first place.

## 3. Authentication Headers

Production mode uses signed JWTs. The local single-identity/API-key mode is retained only as an explicit development fallback.

OIDC/JWT settings:

```text
AUTH_MODE=jwt
OIDC_ISSUER=https://identity.example.com/
OIDC_AUDIENCE=sovereign-agent-orchestrator
OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
```

For an isolated server without an identity provider, use a long random `JWT_SECRET` for HS256 test tokens. Do not use HS256 for a shared internet-facing deployment.

The local single-identity fallback (`AUTH_MODE=api_key`) uses one shared key:

```text
Authorization: Bearer $API_KEY
X-Tenant-Id: engineering
X-User-Id: alice
X-User-Role: lower
```

Because every caller presents the same key, identity comes from those headers, falling
back to `API_USER_ID`, `API_ROLE` (default `lower`) and `DEFAULT_TENANT_ID`. That means
a client can name its own role, so this mode is only appropriate behind a trusted proxy
that sets the headers, on an isolated server, or for local development. There is no
server-side user map: use JWT or OIDC for anything multi-user.

Roles are `admin`, `higher` and `lower` — they are the RAG tiers (section 6A), not free
text. An absent or unrecognised role resolves to `lower`, the least privileged; when a
token carries several, the most privileged wins.

For local development with the bundled dashboard, `DEV_AUTH_ENABLED=true` exposes
`POST /api/v1/auth/dev/login`, which issues a short-lived token for the `Admin`,
`Higher` or `Lower` account against the matching `DEV_*_PASSWORD`. It requires a
`JWT_SECRET` of at least 32 characters and returns 503 below that. Never enable it on a
shared or internet-facing host.

For an internet-facing installation, place the API behind an OIDC/JWT gateway or mTLS
identity proxy.

## 4. API Contract

Base URL: `http://server:8080/api/v1`

### Health and capabilities

```text
GET /health
GET /ready
GET /system/capabilities
GET /system/network
GET /tools
GET /models
```

`/ready` checks database connectivity, workspace access, disk capacity, and configured Ollama models. `/system/capabilities` reports CPU, GPU detection, selected model, size, quantization, context window, embedding dimensions, retrieval mode, reranking status, and supported parsers. `/system/network` reports the egress policy, whether an Ollama *cloud* endpoint is configured, whether outbound cloud is disabled, and any outbound connections the app itself observed — the "nothing leaves the box" surface (it reports; the deployment enforces). `/tools` and `/models` list the registered tool surface and the model registry.

### Documents

```text
POST   /files
GET    /files
GET    /files/scopes
DELETE /files/{file_id}
POST   /files/{file_id}/shares
GET    /files/{file_id}/shares
DELETE /files/shares/{share_id}
```

`GET /files/scopes` lists the tiers this caller may upload into. `POST /files` accepts
an optional `scope` form field naming one of them; without it the upload lands in the
caller's own tier.

Upload example:

```bash
curl -X POST http://localhost:8080/api/v1/files \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "X-Tenant-Id: engineering" \
  -H "X-User-Id: alice" \
  -F "file=@./inspection.pdf"
```

Share example:

```json
POST /api/v1/files/{file_id}/shares
{"user_id":"bob","permission":"read","expires_at":null}
```

Only the owner or administrator can create or revoke a share. Revoked and expired shares are excluded from retrieval.

### Knowledge search

```json
POST /knowledge/search
{
  "query":"What is the inspection interval?",
  "top_k":8,
  "metadata":{"department":"safety"}
}
```

The server always adds the caller's tenant and clearance and resolves the caller's allowed file IDs. Caller input cannot raise clearance or select another tenant.

For retrieval evaluation, use:

```json
POST /api/v1/knowledge/evaluate
{"cases":[{"query":"inspection interval","expected_file_ids":["file-id"],"top_k":5}]}
```

The response reports hit rate, reciprocal rank, and the found file IDs. Retrieval uses semantic candidates followed by a local lexical reranker; no document leaves the server.

### Conversations and chat

```text
GET  /conversations
POST /conversations                 {"title":"Inspection review"}
GET  /conversations/{id}
GET  /conversations/{id}/messages
POST /chat
```

Chat request:

```json
{
  "conversation_id":"optional-existing-id",
  "message":"Compare the attached report with the safety procedure.",
  "attachments":[{"file_id":"uploaded-file-id"}]
}
```

The response contains a queued `job_id` and `conversation_id`. The worker persists the user message, retrieves the allowed context, calls the local model, and persists the assistant response and citations.

### Jobs and artifacts

```text
GET  /agent
POST /agent/run
GET  /agent/{job_id}
GET  /agent/{job_id}/events
POST /agent/{job_id}/approve
POST /agent/{job_id}/cancel
GET  /agent/{job_id}/artifacts
GET  /agent/{job_id}/artifacts/{artifact_name}
```

`GET /agent` lists the caller's recent jobs with status, task type and routed model —
the job list the dashboard renders.

Jobs and artifacts are owner-scoped. Administrators may access jobs in their tenant.

## 5. Citation Contract

Every retrieval hit has this shape:

```json
{
  "chunk_id":"chunk-uuid",
  "document_id":"document-uuid",
  "source":"inspection.pdf",
  "content":"quoted indexed chunk",
  "score":0.91,
  "retrieval_method":"embedding+local_rerank",
  "tier":"higher",
  "metadata":{"file_id":"...","owner_id":"alice","tenant_id":"engineering","visibility_tier":"higher"}
}
```

These hits are stored in the job's `retrieval` and `citations` fields and in the assistant message's `citations` field. The model is instructed to cite source names and state when evidence is insufficient. The API remains the authoritative citation source for UI rendering.

## 6. Storage Model

Operational PostgreSQL tables:

- `jobs`: durable workflow state.
- `job_queue`: queued/running/done/failed work.
- `events`: ordered job progress events.
- `files`: uploaded file ownership and filesystem location.
- `file_shares`: explicit read grants, expiry, and revocation.
- `conversations`: tenant and owner-scoped threads.
- `messages`: user/assistant history and structured citations.
- `audit_events`: security and lifecycle actions.

RAG tables, created identically in **each** of the three tier databases (section 6A):

- `rag_documents`: checksum, source metadata, owner, tenant, and visibility tier.
- `rag_chunks`: content, embedding, chunk number, and provenance metadata.

PostgreSQL uses pgvector and JSONB indexes. SQLite is a development fallback with in-process scoring.

## 6A. Tiered Access Model

RAG content is split across **three separate databases**, one per tier, configured by
`ADMIN_DATABASE_URL`, `HIGHER_DATABASE_URL` and `LOWER_DATABASE_URL`. A role reads
downward only:

| Role | Uploads land in | Can read |
|---|---|---|
| `admin` | admin tier | admin, higher, lower |
| `higher` | higher tier | higher, lower |
| `lower` | lower tier | lower |

An upload's tier is chosen by the uploader's role, optionally narrowed by a requested
scope (`resolve_upload_tier` in `app/access.py`); a search fans out across exactly the
readable tiers and merges by score (`app/rag/tiered.py`). A `lower` caller cannot reach
admin content because the connection to that database is never opened for them. This is
the property the design rests on: prompt-level or filter-level access control is not
access control, and tier membership is the authorization.

> **Do not set `DATABASE_URL` on its own.** The three tier variables fall back to it
> when unset, so pointing a deployment at PostgreSQL with `DATABASE_URL` alone collapses
> the control plane and all three tiers into a single database, and every tier can then
> read every document. `REQUIRE_POSTGRES` does not catch this, because all four *are*
> PostgreSQL. Either leave all four unset — the default gives four distinct SQLite files,
> correctly isolated — or set all four explicitly, as `docker-compose.yml` does.

Verify what a configuration actually resolves to before trusting it:

```bash
set -a; . ./.env; set +a
.venv/bin/python -c "
from app.config import settings
print('control:', settings.database_url)
for t,u in settings.tier_database_urls.items(): print(f'{t:>7}:', u)
print('distinct:', len({settings.database_url, *settings.tier_database_urls.values()}))"
```

Expect `distinct: 4`.

## 7. Local Model and Auto-Configuration

At startup the server detects:

- Operating system and CPU count.
- NVIDIA GPU name, VRAM, and driver when `nvidia-smi` is available.
- Free workspace disk.
- Configured generation and embedding model.
- Model size, quantization, context window, embedding dimensions, and quality rank from `config/models.yaml`.
- Semantic versus lexical retrieval mode.
- Reranking status.
- Parser and OCR capabilities.

When `AUTO_CONFIG=true` and `OLLAMA_MODEL` is not explicitly set, the highest quality enabled model that fits detected GPU memory is selected. Set `AUTO_CONFIG=false` to require explicit configuration.

## 7A. Task Routing and the Agent Loop

`app/models/router.py` classifies every task by ordered regular expressions into
one of: `coding`, `multimodal`, `presentation`, `spreadsheet`, `calculation`,
`document_workflow`, `general`. Each type maps to a model capability
(`coding` → coder, `multimodal` → vision, others → reasoner / document model).
An attached image overrides the capability to `vision` regardless of the task's
wording -- a question about a picture usually names no visual thing ("give the
dimensions for this"), so routing on text alone sent drawings to a text-only model.
The task type, and therefore the plan and the deliverable, still come from the text.

`ModelRouter.route()` returns the chosen registry id **and** model name; the
orchestrator (`_adapter_for`) then builds and caches a per-model `OllamaAdapter`,
so the model the router picked is the model that actually runs. If that model is
not pulled on the host the job degrades to the default model and emits a
`model_fallback` event rather than failing.

`app/orchestrator/service.py` then runs, per attempt:

```text
retrieve evidence (tier-scoped) -> call the routed model
  -> build a task-type plan (_document_plan / _coding_plan / _calc_plan /
     _spreadsheet_plan / _presentation_plan)
  -> execute steps (policy check per tool, MAX_TOOL_CALLS enforced,
     $name placeholders pipe one step's output into a later step)
  -> verify
  -> pass: deliver | fail and attempts left: re-prompt the model with the
     failed checks and re-plan | fail and no attempts left: fail the job
```

`MAX_ITERATIONS` (default 3) and `MAX_TOOL_CALLS` (default 12) bound the loop;
a job may also override `max_iterations` in its request `options`.

## 8. Tools

The registered tools are local and policy-controlled:

- `search_documents`: authorization-aware RAG retrieval.
- `read_file`, `write_file`: job-workspace-only file operations.
- `ingest_document`, `ocr_document`, `extract_tables`: controlled document processing.
- `spreadsheet_profile`, `redact_pii`, `export_report`: local data operations.
- `generate_docx`, `generate_xlsx`, `generate_pptx`, `generate_pdf`: local artifact generation (Word / Excel / PowerPoint / PDF). PDF is produced directly with pymupdf -- no LibreOffice or external converter is involved, and it works air-gapped.
- `list_sources`: inventory of indexed sources the caller may read.
- `run_python`: runs one generated `.py` file in a no-network sandbox with CPU,
  memory and file-size caps; returns exit code and captured output. See
  `app/tools/sandbox.py` for the isolation layers.
- `search_db`: read-only access limited to RAG tables.
- `create_calendar_event`: creates an auditable local event artifact.
- `send_email`: sends through configured SMTP only; returns `SMTP_NOT_CONFIGURED` when unavailable.

High-risk tools require approval. `generate_docx` / `generate_xlsx` / `generate_pptx` / `generate_pdf`
also require approval when the caller's requested role is `approver_demo`. No tool
is allowed to access arbitrary filesystem paths, reach the network from the code
sandbox, or execute arbitrary SQL against operational tables.

## 9. Deployment

### Single-container appliance (Podman)

`Containerfile` + `container/entrypoint.sh` build **one** image containing
PostgreSQL 17 + pgvector (four logical DBs), Ollama, the Python env, Tesseract,
the API and the worker — a self-contained air-gappable appliance. It sets
`REQUIRE_POSTGRES=true` and `OLLAMA_NO_CLOUD=true`, applies the migrations on
first boot, and binds the API to loopback only. See
[PODMAN_SINGLE_CONTAINER.md](PODMAN_SINGLE_CONTAINER.md); `podman-single.ps1`
wraps build / start / logs / `doctor` / pull-models. Use the multi-service
compose stack below when PostgreSQL, Ollama, API and worker need to scale
independently.

`cli.py doctor` (also `doctor --network`, `doctor --json`) runs local
environment, dependency, connectivity and air-gap checks from the host or
`podman exec`.

### Docker Compose (multi-service)

Copy the example environment file and replace every secret:

```bash
cp .env.example .env
docker compose up -d --build
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up -d --build
```

The first startup pulls the configured Ollama models into the persistent `ollama_data` volume. This requires access to the model registry once. After the models are present, the application can run without public internet.

Check the system:

```bash
curl http://localhost:8080/api/v1/health
curl http://localhost:8080/api/v1/ready
curl http://localhost:8080/api/v1/system/capabilities
```

The compose stack contains:

- `postgres`: PostgreSQL 17 with pgvector and mounted migrations, plus one pgvector database per RAG tier.
- `ollama`: local model server.
- `ollama-init`: idempotent model installation step.
- `api`: HTTP/SSE API with no embedded worker.
- `worker`: durable queue consumer.

Set `WORKER_CONCURRENCY` based on model memory and hardware. Start at `1` for GPU-backed Ollama and increase only after measuring contention. `GET /api/v1/metrics` exposes Prometheus counters and latency histograms.

Upload protection is controlled by `MAX_UPLOAD_BYTES`, `USER_STORAGE_QUOTA_BYTES`, `RATE_LIMIT_PER_MINUTE`, `CLAMAV_HOST`, and `MALWARE_SCAN_REQUIRED`. Set `MALWARE_SCAN_REQUIRED=true` when ClamAV is part of the deployment; uploads fail closed if the scanner is unavailable.

For up to roughly 100 organizational users on one server, begin with one API container and one worker. Increase worker replicas only after measuring GPU/CPU contention. Keep PostgreSQL and Ollama volumes backed up.

## 10. Useful Commands

```bash
docker compose logs -f api worker
docker compose ps
docker compose restart worker
docker compose down
```

Run tests locally:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Run a basic authenticated load test:

```powershell
.venv\Scripts\python.exe scripts\load_test.py --url http://localhost:8080/api/v1/ready --token "$JWT_TOKEN" --requests 200 --concurrency 20
```

Create and validate a PostgreSQL backup:

```powershell
$env:DATABASE_URL="postgresql+psycopg://..."
.venv\Scripts\python.exe scripts\backup_postgres.py --output-dir backups
.venv\Scripts\python.exe scripts\restore_check.py backups\orchestrator_TIMESTAMP.dump
.venv\Scripts\python.exe scripts\restore_test.py backups\orchestrator_TIMESTAMP.dump --database-url "postgresql+psycopg://.../orchestrator_restore_test"
```

Run `restore_test.py` only against a disposable database. It performs a real restore and is the required backup verification drill.

### Podman on Windows

```powershell
podman machine init
podman machine start
podman compose up -d --build
podman compose ps
podman compose logs -f api worker
podman compose down
```

If `podman compose` rejects `service_completed_successfully`, start in dependency order:

```powershell
podman compose up -d postgres ollama
podman compose run --rm ollama-init
podman compose up -d api worker
```

### CLI examples

```powershell
.venv\Scripts\python.exe cli.py "Summarize the indexed inspection documents"
.venv\Scripts\python.exe cli.py --report C:\path\responses.xlsx --output-dir workspace\reports
.venv\Scripts\python.exe cli.py --knowledge-transfer C:\path\problem.md C:\path\README.md --output-dir workspace\reports
```

### Manual three-document smoke test

Upload documents with `POST /files`, save each returned `file_id`, then call:

```json
POST /api/v1/chat
{
  "message":"Summarize these documents and cite the evidence.",
  "attachments":[{"file_id":"first-upload-id"},{"file_id":"second-upload-id"},{"file_id":"third-upload-id"}]
}
```

Poll the returned job, consume its SSE stream, verify `status=done`, and confirm `citations` and `artifacts` are present. Artifact generation covers DOCX, XLSX, PPTX and PDF. PDF is written directly by `generate_pdf` using pymupdf, so it needs no LibreOffice, no `soffice` and no network.

## 11. Repository Layout

```text
app/
  api/routes.py              HTTP API and SSE
  access.py                  roles and the downward tier read cascade
  auth.py                    JWT / OIDC / API-key identity and role resolution
  dev_auth.py                local dev login (DEV_AUTH_ENABLED only)
  config.py                  environment settings, including the tier database URLs
  diagnostics.py             startup hardware/readiness checks
  network.py                 egress status surface
  operations.py              rate limiting, storage quotas, malware scanning
  queue.py                   durable database-backed job queue
  main.py                    application composition
  worker.py                  dedicated queue worker
  audit/                     audit event helpers
  models/                    model adapters and routing
  orchestrator/              workflow and citation assembly
  policy/                    allow / deny / require-approval engine
  rag/service.py             extraction, chunking, embedding, retrieval
  rag/tiered.py              per-tier services and the cross-tier read cascade
  rag/report.py              workbook and knowledge-transfer reports
  schemas/                   API contracts
  storage/                   SQL persistence and authorization queries
  tools/registry.py          policy-controlled local tools
  tools/sandbox.py           no-network sandbox for generated Python
  verification/              completion and artifact verification
  workspace/                 per-job filesystem boundary
config/models.yaml           model profiles and auto-configuration data
config/tools.yaml            reviewed tool catalog
frontend/                    Vite + React dashboard
migrations/                  PostgreSQL and pgvector bootstrap SQL
tests/                       core, routing, RAG and tiered-access tests
start.md                     manual start-up runbook for the full local stack
README.md                    operational guide: install, configure, run, integrate
SYSTEM_GUIDE.md              authoritative system/API/deployment guide
```

## 12. End-to-End State Machine

```text
queued -> planning -> acting -> observing -> verifying -> delivering -> done
                        ^         |             |
                        |         v             v
                        |  awaiting_approval  (fail + attempts left)
                        +---------- re-plan ----+
                                                |
                                                v
                                             failed
```

A job cancelled through `POST /agent/{job_id}/cancel` ends in `cancelled`.

Approval-required tools pause at `awaiting_approval`. The approval endpoint resumes
or rejects the pending action. When verification fails and iterations remain, the
job returns to `planning` with the failed checks fed back to the model (a
`replanning` event is emitted); it fails only after `MAX_ITERATIONS`. Every
transition is persisted as an event and is available through SSE.

## 13. Security Invariants

- The model never makes authorization decisions.
- JWT/OIDC claims determine identity, tenant, role, and clearance in production mode.
- RAG retrieval is restricted to the tier databases the caller's role may read; it is not owner-scoped, and users sharing a tier and tenant can retrieve each other's indexed content.
- The file surface -- listing, download, and attaching a file to a job -- *is* owner-scoped: owner, active share, or administrator, within one tenant.
- Attached-document queries are restricted to the supplied file IDs.
- Expired and revoked shares are excluded from the file surface.
- Unknown tools are denied by policy.
- Filesystem paths are canonicalized under the job workspace.
- SQL access is read-only and limited to RAG tables.
- External email requires configured SMTP and approval policy.
- Documents are treated as untrusted data; generated instructions are not authorization.

## 14. Electron, Web, and Other Clients

Clients only need REST/JSON and SSE. They do not need to know about LangGraph, Ollama, PostgreSQL, pgvector, worker internals, or filesystem paths.

Recommended client sequence:

```text
authenticate -> POST /files -> receive file_id -> POST /chat or /agent/run
             -> subscribe to /agent/{job_id}/events
             -> GET /agent/{job_id}
             -> render citations and artifacts
```

Use `conversation_id` to continue a thread. Use `attachments[].file_id` to force retrieval to selected documents. Render citations from the response's structured `citations`, not from model text parsing.

## 15. Current Tool Catalog

| Tool | Purpose | Production boundary |
|---|---|---|
| `search_documents` | Scoped RAG retrieval | Owner/share/tenant/file filters |
| `read_file`, `write_file` | Workspace files | Job workspace only |
| `ingest_document`, `ocr_document` | Indexing and OCR | Supported types and quotas |
| `extract_tables`, `spreadsheet_profile` | Structured documents | Local files only |
| `redact_pii` | Email/phone redaction | Writes to workspace |
| `export_report`, `generate_docx`, `generate_xlsx`, `generate_pptx`, `generate_pdf` | Word/Excel/PowerPoint/PDF artifacts | Output workspace only |
| `list_sources` | Indexed source inventory | Readable tiers only |
| `run_python` | Execute generated Python | No-network sandbox, CPU/mem/file caps |
| `search_db` | RAG inspection | SELECT/WITH and RAG tables only |
| `send_email` | SMTP delivery | Requires SMTP and approval |
| `create_calendar_event` | Local event artifact | No external delivery yet |

## 16. Verification Status

The following have been verified locally:

- Three-document upload and indexing.
- Tenant-scoped search and structured citations.
- Conversation history and attached-document chat.
- DOCX / XLSX / PPTX / PDF artifact generation and complete pipeline delivery.
- Task routing across coding / calculation / spreadsheet / presentation / multimodal
  / document / general, each served by its capability-matched model profile.
- Coding workflow: fenced code written to source files, Python run in the
  no-network sandbox, exit code gating verification; network access from the
  sandbox denied.
- Bounded re-planning: a job whose first attempt fails verification re-prompts the
  model and retries within `MAX_ITERATIONS`.
- Image-only / scanned PDF: per-page rasterisation and Tesseract OCR.
- JWT claim validation, sharing, revocation, and attachment isolation.
- Local reranking and retrieval evaluation metrics.
- 100-request API load test at concurrency 20 against the fake-model API.
- PostgreSQL custom-format backup, destructive drop, restore, and row verification.
- Tier isolation: a lower-tier role cannot retrieve admin-tier content.
- Attached images read directly by the vision model, including dimensioned engineering drawings.
- 46 automated tests passing.

The following require environment-specific verification:

- Real OIDC provider and JWKS rotation.
- Real Ollama generation under target hardware load, including per-task model swaps.
- ClamAV fail-closed scanning.
- Multi-replica rate limiting with Redis/PostgreSQL coordination.
- TLS, secret rotation, alerting, and backup retention policy.

## 17. Roadmap and Definition of Done

Use this document as the single source of truth. The system is prototype-ready when the local API, document flow, citations, conversations, artifacts, and isolation tests pass. Call it production-ready only after target-hardware Ollama load tests, OIDC, TLS, malware scanning, centralized rate limiting, monitoring, restore drills, and an evaluated retrieval/answer set pass.

Model selection must be based on measured latency, VRAM/RAM, retrieval quality, answer quality, and failure rate. For a 16 GB laptop, start with one Ollama worker and increase `WORKER_CONCURRENCY` only after measuring contention.
