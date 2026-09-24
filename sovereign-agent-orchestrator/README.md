# Sovereign Agent Orchestrator

A local/air-gapped agentic workbench: an API and CLI that take a task plus optional
files, route the task to a capability-matched local model, plan it, execute only
registered tools, verify the result, and return artifacts with citations. Nothing
leaves the machine.

This file is the operational guide — install, configure, run, integrate.
[SYSTEM_GUIDE.md](SYSTEM_GUIDE.md) carries the deeper architecture, security and
roadmap detail, and [ARCHITECTURE.md](ARCHITECTURE.md) the job lifecycle and
security invariants.

> **Is this a complete offline RAG system?**
>
> For local document ingestion and retrieval, yes, with one distinction:
>
> - It works with no internet access and no Ollama, using deterministic lexical retrieval.
> - It uses local semantic embeddings when Ollama is installed and the embedding model was pulled before the machine was isolated.
> - It extracts text from images locally via Tesseract or a local Ollama vision model.
> - It is not a packaged one-command air-gapped appliance. The operator still supplies model files, database backups, secrets and host OCR dependencies.

---

## 1. What the system does

Accepts a task through the API or CLI. Classifies it (coding / calculation /
spreadsheet / presentation / multimodal / document_workflow / general) and routes it
to a capability-matched local model — the routed model is the one that runs, via a
per-model adapter, falling back to the default model and emitting a `model_fallback`
event if it is not pulled. Runs a plan → act → observe → verify → deliver workflow
with a task-type-specific plan, re-planning on verification failure within
`MAX_ITERATIONS` and capping tool calls at `MAX_TOOL_CALLS`.

Job states: `queued`, `planning`, `acting`, `observing`, `verifying`,
`awaiting_approval`, `delivering`, `done`, `failed`, `cancelled`.

Ingest accepts **50 file extensions**: documents, spreadsheets, images, and source
code. Code and config files are chunked on line boundaries so indentation survives —
the prose chunker collapses all whitespace, which for Python discards the structure
that carries the meaning.

Every chunk is also indexed with the equipment identifiers it contains
(`equipment_tags`, e.g. `P-204B`, `HV-1127`, `SOP-BFP-07`), so a document can be
found by name as well as by meaning. Filter with
`{"metadata": {"equipment_tags": ["HV-1127"]}}` on `POST /knowledge/search`. Tags are
written at ingest time, so documents indexed before this existed carry none until
they are re-ingested.

For RAG, the flow is:

```text
Document upload
    |
    v
File stored in workspace/uploads, and in the RAG tier database for the uploader's role
    |
    v
Text extraction
TXT/Markdown/PDF/DOCX/PPTX/CSV/XLSX/XLSM/image OCR
    |
    v
Normalized text split into overlapping chunks
    |
    +--> Ollama embedding available: semantic vector stored
    |
    +--> Ollama unavailable: chunk stored without vector
    |
    v
SQLite or PostgreSQL index, one database per access tier
    |
    v
Knowledge search across the tiers the caller may read
semantic cosine score when possible, lexical score otherwise
    |
    v
Agent tool search_documents or direct search API
```

## 2. Tiered access model

This is the project's central security property and it is physical, not a `WHERE`
clause. RAG content lives in **three separate databases**, one per tier, and a role
can only read downward:

| Role | Uploads land in | Can read |
|---|---|---|
| `admin` | admin tier | admin, higher, lower |
| `higher` | higher tier | higher, lower |
| `lower` | lower tier | lower |

A `lower` user cannot reach admin content because the connection to that database is
never opened for them — not because a prompt or a filter asked nicely. Roles are
resolved in `app/access.py`; when several are present the most privileged wins, and
an absent or unrecognised role resolves to `lower`.

The tier databases are configured by `ADMIN_DATABASE_URL`, `HIGHER_DATABASE_URL` and
`LOWER_DATABASE_URL`. **See the warning in section 7 before setting `DATABASE_URL`.**

## 3. Repository map

```text
.
|-- app/
|   |-- main.py                  Application composition and worker lifecycle
|   |-- config.py                Environment-variable settings, tier database URLs
|   |-- access.py                Roles and the downward tier read cascade
|   |-- auth.py                  JWT / OIDC / API-key identity and role resolution
|   |-- dev_auth.py              Local dev login (DEV_AUTH_ENABLED only)
|   |-- diagnostics.py           Readiness probes and host capability report
|   |-- network.py               Egress status surface
|   |-- operations.py            Rate limiting, storage quotas, malware scanning
|   |-- queue.py                 Durable database-backed job queue
|   |-- worker.py                Job worker loop
|   |-- api/
|   |   `-- routes.py            REST, SSE, upload, search, approval, artifact routes
|   |-- orchestrator/
|   |   `-- service.py           Plan -> act -> observe -> verify -> deliver workflow
|   |-- models/
|   |   |-- adapter.py           Fake and Ollama model adapters
|   |   `-- router.py            Deterministic task-and-attachment-to-model routing
|   |-- rag/
|   |   |-- service.py           Extraction, chunking, embeddings, search
|   |   |-- tiered.py            Per-tier services and the read cascade
|   |   `-- report.py            Workbook and knowledge-transfer reports
|   |-- tools/
|   |   |-- registry.py          Allowed document and artifact tools
|   |   `-- sandbox.py           No-network sandbox for generated Python
|   |-- policy/
|   |   `-- engine.py            Allow, deny, or require-approval policy
|   |-- verification/
|   |   `-- verifier.py          Completion and artifact verification
|   |-- storage/
|   |   `-- store.py             Jobs, events, files, approvals, audit, queue
|   |-- workspace/
|   |   `-- manager.py           Per-job filesystem and traversal protection
|   |-- audit/                   Audit event helpers
|   `-- schemas/
|       `-- contracts.py         API request and response contracts
|-- config/
|   |-- models.yaml              Model registry read by the router
|   `-- tools.yaml               Reviewed tool catalog
|-- frontend/                    Vite + React dashboard (separate dev server)
|-- migrations/
|   |-- tier/001_initial_pgvector.sql  pgvector schema (per RAG-tier DB)
|   `-- core/001_operational.sql       operational tables/indexes
|-- workspace/                   Uploaded files and per-job working data
|-- cli.py                       Local demonstration runner
|-- docker-compose.yml           PostgreSQL plus orchestrator services
|-- Dockerfile                   Container image definition
|-- requirements.txt             Python runtime dependencies
|-- tests/                       Core, routing, RAG and tiered-access tests
|-- start.md                     Manual start-up runbook for the full local stack
|-- SYSTEM_GUIDE.md              Authoritative architecture/security/ops reference
`-- ARCHITECTURE.md              Lifecycle and security invariants
```

### Runtime directories

Each job receives its own directory:

```text
workspace/<job_id>/
|-- input/       Files copied from the indexed upload store for this job
|-- working/     Intermediate job files
|-- output/      Generated artifacts exposed through the API
`-- logs/        Reserved for job-specific logs
```

`workspace/uploads/` holds the originals uploaded through `POST /api/v1/files`.

## 4. Tools

Registered and callable by the agent:

```text
search_documents   read_file          write_file
generate_docx      generate_xlsx      generate_pptx      generate_pdf
run_python         ingest_document    list_sources       export_report
spreadsheet_profile  redact_pii       extract_tables     ocr_document
search_db          send_email         create_calendar_event
```

`run_python` executes one generated file in a no-network sandbox with CPU, memory and
file-size caps (`app/tools/sandbox.py`): nsjail / bwrap / firejail on Linux, a
`sandbox-exec` deny-network profile on macOS, and a resource-limit floor everywhere.
The exit code gates verification for coding tasks.

`send_email` and `create_calendar_event` require an approval policy. `create_calendar_event`
only ever writes an auditable draft JSON file into the job workspace. `send_email`
does the same unless `SMTP_HOST` is configured, in which case it sends for real.

`redact_pii` handles `.docx` through python-docx rather than as raw bytes, and
replaces per paragraph rather than per run — Word splits a paragraph at every
formatting change, which routinely cuts an email address in half so that no single
run matches. Reading a `.docx` as text instead produced a corrupt archive that still
contained every address it started with.

`generate_xlsx` is reached by the `spreadsheet` plan, which needs a spreadsheet
**attached**. A spreadsheet request with nothing attached currently falls back to the
document plan and produces a `.docx` — see Known limits in `ARCHITECTURE.md`.

There is deliberately no arbitrary-URL fetch tool.

## 5. Model lineup

Configured in [config/models.yaml](config/models.yaml). The router picks a profile per
task type by capability; an attached image forces a vision-capable model regardless of
the wording of the task. Enable a profile, then `ollama pull` its model.

| Profile | Model | Role | Default |
|---|---|---|---|
| `qwen-local` | `qwen3.6:27b` | reasoning / document / calculation / general | **enabled** |
| `qwen-coder` | `qwen3.6:27b` | coding (same weights, already resident) | **enabled** |
| `qwen-vision` | `qwen3-vl:8b` | scans, drawings, photos, screenshots | **enabled** |
| `bge-m3-embed` | `bge-m3` | embeddings, multilingual (1024 dims) | **enabled** |
| `qwen-fast` | `qwen3.5:4b` | fast, low-memory tasks | disabled |
| `qwen-quality` | `qwen3:14b` | higher-quality reports | disabled |
| `qwen-reasoning` | `qwen3.6:35b-a3b` | complex reasoning | disabled |
| `qwen-coder-moe` | `qwen3-coder:30b` | dedicated MoE coder, 256K context | disabled |
| `nomic-embed` | `nomic-embed-text` | embeddings (768 dims) | disabled |

If a routed model is not pulled, the orchestrator falls back to `qwen-local` and emits
a `model_fallback` event. Changing the embedding profile means changing
`RAG_EMBEDDING_DIMENSIONS` to match, or Postgres will reject the vectors.

## 6. Prerequisites

### Minimum offline mode

- Python 3.12 or newer, and pip
- No model server required; SQLite by default
- Internet needed once to install Python packages, unless wheels are already local

Supports document extraction and lexical search. No semantic embeddings, no generation.

### Local semantic and generative mode

Install Ollama on the machine running the API, then pull the models while it still has
registry access:

```bash
ollama pull qwen3.6:27b   # reasoner + coder + calc + docs + general (~17 GB)
ollama pull qwen3-vl:8b   # vision: scans, screenshots, drawings, handwriting (~6 GB)
ollama pull bge-m3        # embeddings, multilingual (~1.2 GB)
```

Model names are overridable with `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL` and
`OLLAMA_EMBEDDING_MODEL`. `qwen3.6:27b` is ~17.8 GB resident; size the host for it, or
enable `qwen-fast` instead.

### Image OCR

Install Tesseract for host-based OCR:

- Windows: install Tesseract OCR and put `tesseract.exe` on `PATH`
- macOS: `brew install tesseract`
- Debian/Ubuntu: `sudo apt-get install tesseract-ocr`

Tesseract is fast but weak on drawings and photographs, where it often returns noise
rather than an error. When its output is unusable the service falls back to the local
Ollama vision model, and if that is also unavailable the file is indexed as having no
readable text rather than as noise. Set `OCR_PREFER_VISION=true` to send images and
scanned PDFs straight to the vision model.

Separately from indexing, an image attached to a task is passed directly to the vision
model at question time, so a drawing can be read even when no OCR text exists for it.

## 7. Configuration

All settings are environment variables; [.env.example](.env.example) documents every
one the code reads. The application does **not** auto-load `.env` — export it first:

```bash
set -a; . ./.env; set +a
```

> **Do not set `DATABASE_URL` on its own.** The three tier variables fall back to it
> when unset, so pointing a local run at Postgres with `DATABASE_URL` alone collapses
> the control plane and all three RAG tiers into one database — and every tier can
> then read every document. `REQUIRE_POSTGRES` does not catch it, because all four
> *are* Postgres. Either leave all four unset (four distinct SQLite files, correctly
> isolated) or set all four. `docker-compose.yml` sets all four.

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_MODE` | `fake` | `fake` needs no model server; `ollama` enables local model calls |
| `DATABASE_URL` | `sqlite:///./orchestrator.db` | Control plane only: jobs, files, conversations, audit |
| `ADMIN_DATABASE_URL` | `sqlite:///./admin_tier.db` | RAG content, admin tier |
| `HIGHER_DATABASE_URL` | `sqlite:///./higher_tier.db` | RAG content, higher tier |
| `LOWER_DATABASE_URL` | `sqlite:///./lower_tier.db` | RAG content, lower tier |
| `REQUIRE_POSTGRES` | `false` | Refuse to start unless all four databases are PostgreSQL |
| `RAG_EMBEDDING_DIMENSIONS` | `768` | Must match the embedding model (bge-m3 = 1024) |
| `WORKSPACE_ROOT` | `./workspace` | Root for uploads and per-job workspaces |
| `AUTH_MODE` | `jwt` | `jwt` validates bearer tokens; `api_key` accepts a shared key |
| `JWT_SECRET` | empty | HS256 secret; dev login returns 503 below 32 characters |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_JWKS_URL` | empty | Production OIDC validation |
| `DEV_AUTH_ENABLED` | `false` | Local dev login endpoint. Never enable on a shared host |
| `API_KEY` | empty | Required when `AUTH_MODE=api_key` |
| `API_ROLE` | `lower` | Tier for an `api_key` request that sends no role header |
| `DEFAULT_TENANT_ID` | `default` | Tenant used when `X-Tenant-Id` is absent |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama API address |
| `OLLAMA_MODEL` | `qwen2.5vl:3b` | Default/fallback generation model (`.env.example` ships `qwen3.6:27b`) |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model (`.env.example` ships `bge-m3`) |
| `OLLAMA_VISION_MODEL` | `qwen2.5vl:3b` | Vision model (`.env.example` ships `qwen3-vl:8b`) |
| `OLLAMA_KEEP_ALIVE` | `5m` | How long Ollama holds weights resident between calls |
| `OLLAMA_NUM_CTX` | `8192` | Context window per request |
| `LLM_MAX_TOKENS` | `1536` | Generation budget per call |
| `LLM_TIMEOUT_SECONDS` | auto | Empty = `num_predict/3 + 120s` |
| `OCR_PREFER_VISION` | `false` | Send images/scanned PDFs straight to the vision model |
| `OCR_VISION_TIMEOUT_SECONDS` | `180` | Budget for one vision-OCR pass during ingest |
| `MAX_ITERATIONS` | `3` | Orchestrator re-planning limit |
| `MAX_TOOL_CALLS` | `12` | Orchestrator tool-call limit |
| `JOB_TIMEOUT_SECONDS` | `120` | Job timeout |
| `TOOL_TIMEOUT_SECONDS` | `30` | Tool timeout |
| `MAX_UPLOAD_BYTES` | `52428800` | Per-upload size cap |
| `USER_STORAGE_QUOTA_BYTES` | `5368709120` | Per-user storage quota |
| `RATE_LIMIT_PER_MINUTE` | `120` | Per-identity request rate limit |
| `MALWARE_SCAN_REQUIRED` | `false` | Hard gate: `true` without `CLAMAV_HOST` fails every upload |
| `RUN_WORKER` | `true` | Whether the API process also runs the job worker |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8080` | Bind address and port |

Beyond a single-user local machine: set a real `JWT_SECRET` or OIDC, disable
`DEV_AUTH_ENABLED`, use a non-default tenant, and put the service behind TLS or a
private network boundary.

## 8. Installation

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation for the current process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Start the API with the default offline configuration:

```powershell
$env:MODEL_MODE = "fake"
$env:WORKSPACE_ROOT = "./workspace"
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

For local Ollama mode, in one window:

```powershell
ollama serve
```

and in another:

```powershell
ollama pull qwen3.6:27b
ollama pull qwen3-vl:8b
ollama pull bge-m3
$env:MODEL_MODE = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen3.6:27b"
$env:OLLAMA_EMBEDDING_MODEL = "bge-m3"
$env:OLLAMA_VISION_MODEL = "qwen3-vl:8b"
$env:RAG_EMBEDDING_DIMENSIONS = "1024"
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

### macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the default offline API:

```bash
MODEL_MODE=fake WORKSPACE_ROOT=./workspace \
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Install and prepare Ollama:

```bash
brew install --cask ollama
ollama serve
```

In another terminal:

```bash
ollama pull qwen3.6:27b
ollama pull qwen3-vl:8b
ollama pull bge-m3
MODEL_MODE=ollama \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_MODEL=qwen3.6:27b \
OLLAMA_EMBEDDING_MODEL=bge-m3 \
OLLAMA_VISION_MODEL=qwen3-vl:8b \
RAG_EMBEDDING_DIMENSIONS=1024 \
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

[start.md](start.md) is the fuller runbook for bringing up the whole local stack —
Ollama, API and the Vite frontend — including recommended `ollama serve` flags.

### Linux (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the default offline API:

```bash
MODEL_MODE=fake WORKSPACE_ROOT=./workspace \
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

For local Ollama mode, install Ollama through the distribution's approved package
process and use the same environment variables as the macOS section above.

## 9. Offline reports from the CLI

The CLI ingests a workbook into the local RAG index and generates an aggregate DOCX and
JSON report without calling the API or any external service:

```powershell
python cli.py --report "C:\path\to\responses.xlsx" --output-dir workspace\reports
```

Generated as `<workbook>_report.docx` and `<workbook>_report.json`. If Ollama is
unavailable, ingestion still succeeds and retrieval falls back to lexical matching.

For a consolidated knowledge-transfer report from several documents:

```powershell
python cli.py --knowledge-transfer `
  "C:\path\to\problem-statement.docx" `
  "C:\path\to\coding-prompt.md" `
  "C:\path\to\README.md" `
  --output-dir workspace\reports
```

This creates `knowledge_transfer_report.docx` and `knowledge_transfer_report.json`,
including a source register, transfer checklist, evidence sections and citations.

## 10. Verify that the API is running

The interactive API contract is at `http://127.0.0.1:8080/docs`.

```bash
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/ready
```

`/health` returns `{"status":"ok"}`. `/ready` additionally reports the active model,
embedding model and vision model, and whether each backing service is reachable.
Neither requires authentication.

Every other endpoint needs an identity. With `DEV_AUTH_ENABLED=true`:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/auth/dev/login \
  -H 'content-type: application/json' \
  -d '{"username":"Admin","password":"<DEV_ADMIN_PASSWORD>"}'
```

That returns an `access_token` to send as `Authorization: Bearer <token>`. The
accounts are `Admin`, `Higher` and `Lower`, matching the three tiers. In production,
tokens come from your OIDC provider instead.

## 11. Upload and index documents

```bash
curl -X POST http://127.0.0.1:8080/api/v1/files \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: engineering" \
  -F "file=@./documents/inspection-report.pdf"
```

Supported extensions:

```text
.txt .md .pdf .docx .pptx .csv .xlsx .xlsm .png .jpg .jpeg .tiff .bmp
```

The response includes `file_id` — required to attach the upload to a job — and reports
how many chunks were embedded and which tier the document landed in. Uploading an
image whose text cannot be read may take up to `OCR_VISION_TIMEOUT_SECONDS`, because
ingest runs the vision pass synchronously.

## 12. Search the knowledge base directly

```bash
curl -X POST http://127.0.0.1:8080/api/v1/knowledge/search \
  -H "content-type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: engineering" \
  -d '{"query":"fire extinguisher inspection interval","top_k":5}'
```

The search spans exactly the tiers the caller's role may read. Scoring is cosine
similarity when both the query and the chunk have embeddings, and a deterministic
token-overlap lexical score otherwise. Tenant metadata is always added to the filter
by the API route.

## 13. Conversations

Conversations are durable threads. User and assistant messages are stored per tenant,
and the latest 20 are supplied to the model on the next turn. Assistant messages retain
their retrieved citation objects.

```text
GET    /api/v1/conversations
POST   /api/v1/conversations              {"title":"Inspection review"}
GET    /api/v1/conversations/{id}
GET    /api/v1/conversations/{id}/messages
POST   /api/v1/chat                       {"conversation_id":"...","message":"Summarize the inspection findings."}
GET    /api/v1/files
DELETE /api/v1/files/{file_id}
```

`POST /api/v1/chat` returns a queued `job_id` and `conversation_id`. Subscribe to
`/api/v1/agent/{job_id}/events` for progress, then read the answer from the job or the
conversation messages.

## 14. Run an agent task with indexed files

```bash
curl -X POST http://127.0.0.1:8080/api/v1/agent/run \
  -H "content-type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: engineering" \
  -d '{
    "task":"Read the inspection report, find the applicable SOP requirements, and generate an approval note with citations.",
    "attachments":[{"file_id":"REPLACE_WITH_THE_RETURNED_FILE_ID"}]
  }'
```

The API returns a `job_id` immediately. Poll it, stream it, and collect artifacts:

```bash
curl http://127.0.0.1:8080/api/v1/agent/JOB_ID -H "Authorization: Bearer $TOKEN"

curl -N http://127.0.0.1:8080/api/v1/agent/JOB_ID/events -H "Authorization: Bearer $TOKEN"

curl http://127.0.0.1:8080/api/v1/agent/JOB_ID/artifacts -H "Authorization: Bearer $TOKEN"

curl -L http://127.0.0.1:8080/api/v1/agent/JOB_ID/artifacts/approval_note.docx \
  -H "Authorization: Bearer $TOKEN" -o approval_note.docx
```

`GET /api/v1/agent` lists the caller's jobs.

## 15. Approval and cancellation

Policy-controlled actions pause at `awaiting_approval`.

**Only a reviewer or an administrator may approve.** A `lower` role gets
`403 APPROVAL_NOT_AUTHORIZED`, and the role is checked before the job is looked up,
so the response cannot be used to discover which job ids exist. A reviewer may not
clear their own job (`403 SELF_APPROVAL_NOT_ALLOWED`); an administrator may, because
there is nobody above them to ask.

`reviewer_user_id` in the body is accepted for compatibility and **ignored** — the
reviewer recorded is always the one holding the token.

So that there is something to review, a `higher` role can also see another user's job
while it is `awaiting_approval`, in the same tenant, and only in that status.

```bash
# Approve (or send "approved":false to reject)
curl -X POST http://127.0.0.1:8080/api/v1/agent/JOB_ID/approve \
  -H "content-type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"approved":true}'

curl -X POST http://127.0.0.1:8080/api/v1/agent/JOB_ID/cancel \
  -H "Authorization: Bearer $TOKEN"
```

**Each gated tool pauses separately.** A job that generates both a `.docx` and a
`.pdf` pauses twice, and one approval resumes it only as far as the next gated call.
Poll the status after approving rather than assuming the job has finished.

Cancelling a job that is already `done`, `failed` or `cancelled` returns
`409 JOB_ALREADY_FINISHED` rather than overwriting its status.

## 16. API integration pattern

A desktop, Electron or web client should only call the API. It must not import model,
RAG, database or tool modules directly.

```text
1. GET  /api/v1/health
2. POST /api/v1/auth/dev/login  (or obtain an OIDC token)
3. POST /api/v1/files for each knowledge document; save each file_id
4. POST /api/v1/agent/run with the task and attachment file_ids
5. Subscribe to /api/v1/agent/{job_id}/events
6. GET  /api/v1/agent/{job_id} when the stream ends
7. If status is awaiting_approval, POST /approve
8. GET  /api/v1/agent/{job_id}/artifacts and download through the artifact endpoint
```

The client sees job IDs, event data, final answers and artifact URLs. Host filesystem
paths stay server-side. The bundled dashboard in `frontend/` is one such client.

## 17. Docker and PostgreSQL

Compose starts PostgreSQL with pgvector plus the orchestrator. It does not start
Ollama, and its default configuration uses `MODEL_MODE=fake`.

```bash
docker compose up --build
```

The databases are initialized from the migration files mounted into PostgreSQL's
init directory. Compose sets the control-plane URL and all three tier URLs explicitly,
so the tier collapse described in section 7 cannot happen there.

For semantic embeddings in Docker, Ollama must be reachable from the orchestrator
container — `localhost` inside a container is the container itself. Point
`OLLAMA_BASE_URL` at the host gateway or a separately managed Ollama service.

Before an air-gapped deployment:

```text
1. Pull the pgvector image.
2. Build the orchestrator image.
3. Cache all Python packages, or build from an internal package mirror.
4. Pull and cache the Ollama models.
5. Export/import the images and model files on the isolated network.
6. Keep database and workspace volumes on persistent storage.
```

Never use the sample PostgreSQL password in a real deployment.

## 18. SQLite versus PostgreSQL

SQLite is the simplest choice for single-user or development work, and is the default
— four separate files, one per database, correctly isolated.

PostgreSQL is the better choice for multiple workers, concurrent users, backups and
monitoring. Set all four URLs:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/orchestrator
ADMIN_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/rag_admin
HIGHER_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/rag_higher
LOWER_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/rag_lower
```

Apply both migration files, confirm pgvector is enabled, and set
`REQUIRE_POSTGRES=true` so the service refuses to start if any database silently falls
back to SQLite. Keep the databases, `workspace/uploads` and `workspace/<job_id>/output`
in the backup plan.

## 19. What is complete and what still needs work

### Complete for the current scope

- Local HTTP API with OpenAPI, and an SSE progress stream
- Physically isolated per-tier RAG databases with a downward read cascade
- JWT and OIDC authentication, plus a local dev-login shim
- SQLite zero-setup mode and a PostgreSQL/pgvector migration path
- Tenant-aware upload and attachment authorization
- Durable jobs, events, approvals, audit records and queue rows
- Per-job workspace traversal protection
- TXT, Markdown, PDF (including scanned/image-only), DOCX, PPTX, CSV, XLSX, XLSM and image ingestion
- Deterministic chunking, optional Ollama embeddings, lexical fallback without Ollama
- Tesseract OCR with a local vision-model fallback, and direct vision reading of attached images
- Per-task-type plans with bounded re-planning; DOCX / XLSX / PPTX / PDF artifacts
- Generated Python executed in a no-network sandbox, exit code gating verification
- Upload size caps, per-user storage quotas, request rate limiting, optional ClamAV scanning
- Fake model path so the whole pipeline runs with no model server

### Required before calling it a production air-gapped appliance

- A pinned offline Python wheelhouse or internal package index
- A documented model acquisition and checksum process
- A managed Ollama service or another local inference runtime
- Resource limits and model sizing for the target hardware
- TLS or a private network boundary
- Database backup, restore, migration and retention procedures
- OCR quality monitoring, and asynchronous ingest so slow vision passes stop blocking uploads
- Evaluation data for retrieval precision, recall and citation correctness
- Hardening review of the code sandbox for the target OS (nsjail/bwrap policy, seccomp)
- Monitoring, structured logs, alerting and a worker restart policy

## 20. Recommended offline acceptance test

```bash
pytest -q
```

Then validate the deployment in this order:

```text
1.  Stop network access.
2.  Start the API with MODEL_MODE=fake.
3.  Upload a TXT or CSV file.
4.  Search for an exact phrase and confirm a hit.
5.  Start an agent job with the file attached.
6.  Confirm events move through the job lifecycle.
7.  Download the generated artifact.
8.  Start local Ollama, if used, and repeat with semantic queries.
9.  Upload an image and verify Tesseract or local vision extraction.
10. Attach an image to a task and confirm the answer describes the picture itself.
11. Restart the service and confirm jobs, files and indexed chunks survive.
12. Log in as Lower and confirm it cannot retrieve a document uploaded by Admin.
13. Test a second tenant and confirm it cannot search or attach the first tenant's files.
14. Restore from a database and workspace backup on a separate machine.
```

A deployment passes the offline RAG portion only when steps 1 through 7 complete with
the network disabled. Steps 8 through 10 are additional capabilities requiring local
models or OCR dependencies. Step 12 is the tier isolation check and should never be
skipped.

## 21. Useful source files

- [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md): authoritative architecture, security, deployment and ops reference
- [ARCHITECTURE.md](ARCHITECTURE.md): lifecycle, security invariants and extension points
- [start.md](start.md): manual start-up runbook for the full local stack
- [.env.example](.env.example): every environment variable the code reads
- [app/access.py](app/access.py): roles and the tier read cascade
- [app/rag/tiered.py](app/rag/tiered.py): per-tier services and cross-tier search
- [app/rag/service.py](app/rag/service.py): extraction, chunking, embedding and retrieval
- [app/api/routes.py](app/api/routes.py): upload, search, agent, SSE and artifact endpoints
- [app/models/router.py](app/models/router.py): task and attachment routing
- [app/orchestrator/service.py](app/orchestrator/service.py): the plan/act/observe/verify/deliver loop
- [app/tools/registry.py](app/tools/registry.py): the allowed tool surface
- [app/tools/sandbox.py](app/tools/sandbox.py): the no-network execution sandbox
- [app/config.py](app/config.py): environment-variable defaults
- [docker-compose.yml](docker-compose.yml): PostgreSQL deployment example
- [tests/](tests/): current automated coverage
