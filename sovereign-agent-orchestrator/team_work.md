# Sovereign Agent Orchestrator: Team Work Guide

This document is the implementation guide for integrating and extending this repository. It is based on the code currently in the repository, not only on the architecture proposals.

## 0. Current Status At A Glance

The repository is a working local agent runtime with this path:

```text
Dashboard (frontend/), CLI, or any REST/SSE client
  -> FastAPI REST/SSE API
  -> Store and per-job Workspace
  -> Orchestrator
       -> ModelRouter  (per task type -> per-model OllamaAdapter)
       -> FakeModel or OllamaAdapter
       -> task-type plan  (re-planned up to MAX_ITERATIONS on verify failure)
       -> Policy
       -> ToolRegistry
       -> Verifier
       -> output artifact discovery
  -> job polling, SSE events, artifact download
```

Implemented now:

- FastAPI application and OpenAPI at `/docs`.
- Asynchronous job creation with job polling.
- SSE event streaming.
- SQLite persistence for jobs, events, and approvals.
- Fake model mode and per-model Ollama adapters; the routed model is the one invoked.
- Deterministic task routing into coding / calculation / spreadsheet / presentation / multimodal / document / general.
- Per-task-type plans and a bounded re-plan loop on verification failure (`MAX_ITERATIONS`, `MAX_TOOL_CALLS`).
- Per-job workspace with path traversal protection.
- Tools: `search_documents`, `read_file`, `write_file`, `generate_docx`, `generate_xlsx`, `generate_pptx`, `generate_pdf`, `run_python` (no-network sandbox), `spreadsheet_profile`, `extract_tables`, `ocr_document`, `redact_pii`, `export_report`, `search_db`, `ingest_document`, `list_sources`, `send_email`, `create_calendar_event`.
- Deterministic policy checks; `code_executed` verification check for coding tasks.
- Verification before artifact delivery.
- Approval pause/resume; the CLI wires `TieredRagService` and the model adapter and drives the approval gate through `requested_role`.

Not complete yet:

- PostgreSQL/SQLAlchemy persistence and pgvector migration support are implemented; run the migrations before using the production URL.
- Handwriting OCR remains model-dependent and needs company-document accuracy evaluation.
- A free-form model-driven tool-calling loop (plans are deterministic per task type; re-planning is bounded).
- A desktop shell. The React dashboard in `frontend/` is the working client; `ELECTRON_INTEGRATION.md` describes a desktop wrapper that was never built.
- Multi-process job execution at scale. Authentication (JWT/OIDC), tier-based authorization, rate limits, storage quotas and optional ClamAV scanning are implemented.
- Real-model (Ollama) exercise of the per-task model swaps under target hardware.

Treat this distinction as important when planning integration work.

## 1. How To Use This For Integration

### Prerequisites

- Python 3.12 or newer.
- A virtual environment.
- Dependencies from `requirements.txt`.
- Optional: Ollama running locally for local model mode.
- Optional: Docker for the current single-service container.

### Local setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start the API:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

The application is available at:

- Health: `http://localhost:8080/api/v1/health`
- Readiness: `http://localhost:8080/api/v1/ready`
- OpenAPI UI: `http://localhost:8080/docs`

The configured default is `MODEL_MODE=fake`, so the API does not need Ollama to start. The fake adapter returns a deterministic response; it is useful for integration tests, not for useful document reasoning.

### Minimal integration request

```powershell
$body = @{
  task = 'Summarize the inspection report'
  user_context = @{
    user_id = 'desktop-user'
    role = 'user'
    department = 'inspection'
    clearance = 'internal'
    project = 'demo'
  }
  attachments = @()
  options = @{
    max_iterations = 3
  }
} | ConvertTo-Json -Depth 6

$job = Invoke-RestMethod `
  -Method Post `
  -Uri 'http://localhost:8080/api/v1/agent/run' `
  -ContentType 'application/json' `
  -Body $body

$job
Invoke-RestMethod "http://localhost:8080/api/v1/agent/$($job.job_id)"
```

The run endpoint returns quickly with a `job_id` and `queued` status. The job is persisted in `job_queue`; the FastAPI lifespan worker claims queued jobs and resumes them after a process restart.

### Recommended client lifecycle

1. Check `/api/v1/ready`.
2. Upload files through `POST /api/v1/files` when file upload support is needed.
3. Start a job with `POST /api/v1/agent/run`.
4. Subscribe to `GET /api/v1/agent/{job_id}/events` or poll `GET /api/v1/agent/{job_id}`.
5. If the job reaches `awaiting_approval`, show the approval request and call the approval endpoint.
6. When the job reaches `done`, list artifacts and download them.
7. On `failed` or `cancelled`, show the returned `error` and preserve the event timeline.

### Current API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness response: `status=ok`. |
| GET | `/api/v1/ready` | Readiness: checks database, workspace, disk, and (in ollama mode) that the configured generation and embedding models are installed. `status` is `ready` or `degraded`. |
| POST | `/api/v1/files` | Multipart upload; returns a generated `file_id`. |
| POST | `/api/v1/agent/run` | Creates and asynchronously starts a job. |
| GET | `/api/v1/agent/{job_id}` | Returns the stored job dictionary. |
| POST | `/api/v1/agent/{job_id}/approve` | Approves or rejects an awaiting job. |
| POST | `/api/v1/agent/{job_id}/cancel` | Marks a job cancelled. |
| GET | `/api/v1/agent/{job_id}/events` | Streams stored events as SSE. |
| GET | `/api/v1/agent/{job_id}/artifacts` | Returns the job artifact list. |
| GET | `/api/v1/agent/{job_id}/artifacts/{artifact_name}` | Safely downloads an output file by filename. |

### SSE example

```javascript
const source = new EventSource(`${baseUrl}/api/v1/agent/${jobId}/events`);
source.onmessage = (event) => {
  const record = JSON.parse(event.data);
  renderEvent(record.type, record.data);
};
source.onerror = () => source.close();
```

The server emits records such as `job_created`, `status_changed`, `model_selected`, `model_response`, `model_fallback`, `plan_created`, `step_started`, `tool_started`, `tool_completed`, `step_completed`, `approval_required`, `verification_passed`, `verification_failed`, `replanning`, `artifact_created`, `job_completed`, and `model_error`.

## 2. How To Add New Models

There are two separate concepts:

1. A registry entry in `config/models.yaml`, used for logical routing.
2. A runtime adapter in `app/models/adapter.py`, used to make the actual model call.

### Add an Ollama model

Add an entry with a stable logical ID:

```yaml
models:
  - id: qwen-local
    provider: ollama
    model: qwen3.6:27b
    capabilities: [reasoning, completion, document, coding]
    enabled: true

  - id: llama-local
    provider: ollama
    model: llama3.1:8b
    capabilities: [reasoning, completion, document]
    enabled: true
```

Download the model in the Ollama installation:

```powershell
ollama pull llama3.1:8b
```

Run the API with:

```powershell
$env:MODEL_MODE = 'ollama'
$env:OLLAMA_BASE_URL = 'http://localhost:11434'
$env:OLLAMA_MODEL = 'llama3.1:8b'
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

`ModelRouter` returns the chosen registry id **and** `model_name`; `Orchestrator._adapter_for()` builds and caches a per-model `OllamaAdapter` from that name, so the routed model is the one that runs. `OLLAMA_MODEL` is only the default / fallback (used when a job routes to a model that is not installed, alongside a `model_fallback` event).

### Add a provider

Implement the `ModelAdapter` protocol:

```python
class OpenAICompatibleAdapter:
    async def chat(self, messages, tools=None, **kwargs):
        # POST to the internal provider's chat-completions endpoint.
        # Return at least {'content': '...'}.
        ...
```

Then update application assembly in `app/main.py` to choose the adapter from a provider field. Keep the adapter contract provider-neutral:

- Input: chat messages, optional tool definitions, optional timeout.
- Output: a dictionary containing `content`; preserve structured tool calls if added.
- Errors: raise a clear exception so the orchestrator stores `model_error` and fails the job.

For a fully offline system, package model weights in the approved local model cache, pin model versions, disable network access for the model container, and test startup without DNS or Internet access.

### Routing rules

`app/models/router.py` currently classifies by regular expressions:

`_PATTERNS` in `app/models/router.py`, first match wins:

- code / python / function / algorithm / refactor / debug ... -> `coding`
- image / scan / drawing / photo / P&ID / handwritten / blueprint ... -> `multimodal`
- slide / deck / powerpoint / pptx -> `presentation`
- spreadsheet / excel / xlsx / workbook / pivot table -> `spreadsheet`
- calculate / compute / estimate / sizing / flow rate / how many ... -> `calculation`
- document / approval / report / inspection / summary / memo / letter ... -> `document_workflow`
- otherwise -> `general`

Each task type maps to a capability (`_CAPABILITY`) and then to a preferred registry
id (`_PREFERRED`: `qwen-coder` / `qwen-vision` / `qwen-quality` / `qwen-reasoning`).
If the preferred id is not enabled, the router falls back to any enabled model that
advertises the capability, then to the first enabled model. Keep the registry ids
stable and update `_PATTERNS` / `_CAPABILITY` when adding a task type.

## 3. How To Add More Skills And Tools

In this repository, a skill is currently implemented as a registered tool plus policy and orchestration support. The registry is `app/tools/registry.py`.

### Add a simple tool

1. Add the tool name to `ToolRegistry.names()`.
2. Add a branch to `ToolRegistry.execute(jid, name, args)`.
3. Add its risk tier and decision rule to `Policy.risks` in `app/policy/engine.py`.
4. Add the tool to the relevant plan builder in `Orchestrator` (`_document_plan`,
   `_coding_plan`, `_calc_plan`, `_spreadsheet_plan`, `_presentation_plan`). A step
   can consume an earlier step's output with a `$name` placeholder in its tool_args.
5. Return a JSON-serializable result with useful source metadata.
6. Add tests for allowed execution, invalid arguments, path safety, and failure behavior.

Example shape:

```python
if name == 'count_report_findings':
    report = self.workspace.safe(jid, args['path']).read_text(errors='ignore')
    return {'count': report.count('Finding '), 'source': args['path']}
```

For a real tool system, replace the parallel name list and `if` chain with a definition map containing:

```text
name
description
input schema
risk tier
handler
```

This definition map should be the source for model tool schemas, policy lookup, execution, and OpenAPI documentation.

### Existing tool behavior

- `search_documents`: case-insensitive substring search over `.txt` and `.md` files under the job's `input/` directory.
- `read_file`: reads a path after `Workspace.safe()` validation.
- `write_file`: writes only within the job workspace.
- `generate_docx`: creates a DOCX in `output/` using `python-docx`.

Unknown tools are denied by policy. `run_python` and `ocr_document` are registered and executable; `describe_image` appears in the policy table but is not yet implemented (the vision path runs through `ocr_document` / ingest instead).

### Security requirements for new tools

- Never accept a host filesystem path from the client.
- Resolve all paths through `Workspace.safe()`.
- Do not let model output decide authorization.
- Set an explicit risk tier.
- Add timeout and cancellation handling.
- Limit input size and output size.
- Avoid arbitrary network access by default.
- For code execution, use an ephemeral no-network sandbox such as a hardened container, gVisor, or Firecracker. Do not expose the host filesystem or Docker socket.

## 4. How To Access Its API

The base URL is configurable; the development default is `http://localhost:8080`. Use `/api/v1` for every endpoint.

### Start a job with curl

```bash
curl -X POST http://localhost:8080/api/v1/agent/run \
  -H 'content-type: application/json' \
  -d '{
    "task": "Read the inspection report and generate an approval note",
    "user_context": {
      "user_id": "desktop-user",
      "role": "user",
      "department": "inspection",
      "clearance": "internal",
      "project": "demo"
    },
    "attachments": [],
    "options": {"max_iterations": 3}
  }'
```

### Upload a file

```bash
curl -X POST http://localhost:8080/api/v1/files \
  -F 'file=@inspection_report.txt'
```

The response contains `file_id`, filename, MIME type, byte size, and an indexing result. Current implementation stores the file at `workspace/uploads/{file_id}_{filename}` and immediately extracts, chunks, and indexes it in SQLite. Jobs can retrieve indexed content through semantic model-context retrieval. The remaining gap is that `attachments` are not yet scoped to a job's `input/` directory, so per-job attachment selection and authorization still need to be completed.

### Approval

A job reaches approval when the policy returns `require_approval`. The demo policy does this for `generate_docx` when `user_context.role` is `approver_demo`:

```bash
curl -X POST http://localhost:8080/api/v1/agent/JOB_ID/approve \
  -H 'content-type: application/json' \
  -d '{"approved": true, "reviewer_user_id": "reviewer-1"}'
```

Reject with `"approved": false`. Approval is not authenticated in the current MVP, so production must derive reviewer identity from an authenticated session rather than trusting request JSON.

## 5. Complete Internals

### Application assembly

`app/main.py` creates global process-level objects:

```text
Settings -> Store
         -> Workspace
         -> ModelRouter
         -> FakeModel or OllamaAdapter
         -> Policy
         -> ToolRegistry
         -> Verifier
         -> Orchestrator
         -> FastAPI router
```

### Request-to-result flow

1. `POST /agent/run` creates a UUID and a dictionary-shaped job.
2. The job is saved to `Store.jobs` and `job_created` is emitted.
3. `Orchestrator.run()` invokes a one-node LangGraph-compatible graph.
4. The workspace directories are created.
5. The task is routed to a task type and a model.
6. The routed model receives a system message and the task (plus any retrieved evidence).
7. `_plan()` builds a plan for that task type (document: search + DOCX; coding:
   write source files + `run_python`; calculation / spreadsheet / presentation
   likewise). General tasks skip tools and finish after the model response.
8. Each step is checked by `Policy` and executed by `ToolRegistry`; `MAX_TOOL_CALLS`
   is enforced and `$name` placeholders pipe earlier outputs forward.
9. Results are appended to `observations` and emitted as events.
10. `Verifier` checks plan completion, citations/sources for document workflows,
    artifact existence, no denied calls, evidence grounding, and (for coding) that
    the sandboxed run exited 0.
11. If verification fails and iterations remain, the model is re-prompted with the
    failed checks and the plan is re-run (up to `MAX_ITERATIONS`).
12. Output files are discovered and represented with download URLs.
13. The job becomes `done` or `failed`.

### State lifecycle

```text
queued -> planning -> acting -> observing -> verifying -> delivering -> done
```

Other paths:

```text
acting -> awaiting_approval -> acting
any active state -> failed
any state -> cancelled
```

The documented retry path from `verifying` back to `planning` is not implemented.

### Persistence internals

`app/storage/store.py` uses SQLAlchemy for SQLite development and PostgreSQL production. The RAG service adds `rag_documents` for checksummed source metadata and `rag_chunks` for extracted chunks, metadata, and embeddings. The operational store creates:

- `jobs(id, data)` where the complete job is a JSON blob.
- `events(id, job_id, type, data, created_at)`.
- `approvals(id, job_id, approved, reviewer, created_at)`.

PostgreSQL schemas are supplied in `migrations/tier/001_initial_pgvector.sql` and `migrations/core/001_operational.sql`. The application creates compatible bootstrap tables, but production deployments should apply the migrations first so JSONB, UUID, and vector types are present.

### Verification internals

`app/verification/verifier.py` validates plan completion, retrieved source IDs, artifact existence, and absence of denied calls. A citation is accepted only when the retrieved observation includes both a stable `chunk_id` and source name; generated prose citations still need richer page/offset checks for regulated use.

### Workspace internals

Each job receives:

```text
workspace/{job_id}/
  input/
  working/
  output/
  logs/
```

`Workspace.safe()` canonicalizes the requested path and rejects paths outside the job root with `PATH_OUTSIDE_JOB_WORKSPACE`.

## 6. All Internal Connections

```mermaid
flowchart TD
  Client[Dashboard / CLI / any REST+SSE client] --> API[FastAPI routes]
  API --> Store[Store: SQLite JSON jobs/events/approvals]
  API --> WS[Workspace manager]
  API --> Orch[Orchestrator]
  Orch --> Router[ModelRouter]
  Router --> YAML[config/models.yaml]
  Orch --> Adapter[ModelAdapter]
  Adapter --> Fake[FakeModel]
  Adapter --> Ollama[Ollama /api/chat]
  Orch --> Policy[Policy engine]
  Orch --> Tools[ToolRegistry]
  Tools --> WS
  Tools --> Docx[python-docx]
  Orch --> Verify[Verifier]
  Verify --> WS
  API --> SSE[SSE event stream]
  API --> Artifact[Artifact download]
```

Connection ownership:

- API routes own HTTP validation, job creation, uploads, polling, SSE, approvals, cancellation, and downloads.
- Orchestrator owns sequencing and job state transitions.
- ModelRouter owns deterministic task classification and logical model selection.
- ModelAdapter owns provider-specific model HTTP calls.
- Policy owns allow/deny/approval decisions.
- ToolRegistry owns tool dispatch and workspace operations.
- Workspace owns path containment and directory creation.
- Verifier owns the delivery gate.
- Store owns process-safe SQLite writes and reads.

Important missing connections:

- `RAG_URL` is configured but unused.
- Attachments are accepted by schemas but not connected to workspace inputs.
- The route-selected model is not connected to the runtime adapter selection.
- `MAX_ITERATIONS`, `MAX_TOOL_CALLS`, and timeout settings are read but not enforced.
- `app/audit/` contains no audit implementation.
- `langchain-core` is declared but not used directly.
- The LangGraph graph is one orchestration node, not a set of independently checkpointed nodes.

## 7. PostgreSQL, pgvector, And Other Databases

### PostgreSQL for operational state

The intended production migration is:

1. Replace direct `sqlite3` calls with SQLAlchemy 2.x models and sessions.
2. Add a PostgreSQL driver such as `psycopg`.
3. Add Alembic migrations.
4. Split the JSON job blob into first-class tables while retaining JSON for flexible payloads.
5. Add indexes on job status, owner, timestamps, event job ID, and artifact job ID.
6. Use transactions for state transitions and approval writes.
7. Add a connection pool and health check to `/ready`.

Recommended operational tables:

```text
jobs
job_steps
routing_decisions
model_runs
tool_calls
observations
verification_runs
approvals
artifacts
events or audit_events
```

A minimal environment value would be:

```text
DATABASE_URL=postgresql+psycopg://orchestrator:password@postgres:5432/orchestrator
```

Do not enable this value until the store implementation supports the scheme.

### pgvector for RAG

Use PostgreSQL with the `vector` extension for document retrieval. A practical schema is:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  name text NOT NULL,
  mime_type text,
  checksum text UNIQUE NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_chunks (
  id uuid PRIMARY KEY,
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index integer NOT NULL,
  content text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',
  embedding vector(768),
  search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);

CREATE INDEX document_chunks_embedding_hnsw
  ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX document_chunks_search_tsv
  ON document_chunks USING gin (search_tsv);
```

The dimension must match the selected local embedding model. Do not assume `768` without checking the model.

### RAG service boundary

Add a `Retriever` protocol with a method such as:

```text
search(query, tenant_id, filters, top_k) -> hits
```

Each hit should include:

```text
chunk_id, document_id, document_name, content, score, metadata
```

Then implement either:

- in-process PostgreSQL/pgvector retrieval, or
- an internal HTTP RAG service accessed through `RAG_URL`.

Expose retrieval to orchestration through a `search_documents` tool, not directly to the client. Apply tenant, role, clearance, and project filters before returning chunks. Include stable citation IDs in observations so the verifier can validate them.

### Other database options

- SQLite: good for local development and single-process demos.
- PostgreSQL: recommended operational database and pgvector host.
- Qdrant, Milvus, or Chroma: possible dedicated vector stores, but add a retriever adapter and keep the orchestrator contract unchanged.
- Redis: useful for queues, locks, rate limits, and ephemeral event fan-out; not a replacement for durable job state.
- Object storage or MinIO: useful for large source files and artifacts; store only metadata and object keys in PostgreSQL.

## 8. Electron.js Integration

There is no Electron source tree in this repository and none is planned. The working
client is the React dashboard in `frontend/` (see `frontend/README.md`), which uses
the same REST/SSE surface. `ELECTRON_INTEGRATION.md` remains as the contract a
desktop wrapper would implement, and the guidance below applies to any such client.

Recommended Electron layers:

```text
Renderer UI
  -> preload contextBridge
  -> typed IPC methods
  -> main-process API client
  -> Python FastAPI service
```

Do not let renderer code access arbitrary Node APIs or filesystem paths. The main process or a tightly scoped preload bridge should own the API base URL, request headers, file selection, and upload calls.

### TypeScript client shape

```typescript
type JobStatus =
  | 'queued' | 'planning' | 'acting' | 'observing'
  | 'verifying' | 'awaiting_approval' | 'delivering'
  | 'failed' | 'done' | 'cancelled';

interface AgentRunRequest {
  task: string;
  user_context: {
    user_id: string;
    role: string;
    department: string;
    clearance: string;
    project: string;
  };
  attachments: Array<{ file_id?: string; name?: string; mime_type?: string }>;
  options?: { max_iterations?: number };
}

interface JobSummary {
  job_id: string;
  status: JobStatus;
  final_answer?: string | null;
  error?: string | null;
}
```

Use `fetch` for REST and `EventSource` for SSE. Keep the base URL in Electron configuration, not in UI constants. Reconnect SSE after transient failure and reconcile with `GET /agent/{job_id}` because the current SSE implementation reads from the database and does not provide a durable cursor protocol.

Electron should render structured fields from the job:

- status
- routing
- plan
- tool calls and policy decisions
- observations and citations
- verification checks
- approval request
- artifact names and download actions
- final answer and error

Do not render private chain-of-thought. Do not trust model-generated identity, permissions, or status values.

Before production Electron integration, align the implementation and contract on artifact IDs versus filenames, event field shapes, upload-to-job attachment handling, authentication, and endpoint status codes.

## 9. What Remains For A Complete Offline RAG System

Prioritized implementation backlog:

### P0: Make the current vertical slice reliable

- Fix `cli.py` to construct the model adapter and implement the advertised approval command.
- Make `ModelRouter` and runtime adapter use the same selected model.
- Connect uploaded `file_id` values to a specific job's `input/` directory.
- Prevent global upload filename collisions and enforce upload size/type limits.
- Inject the configured workspace root into `Verifier` instead of hard-coding `workspace`.
- Enforce cancellation, iteration, tool-call, and timeout limits.
- Add exception handling around tool execution and persistence.
- Add tests for API endpoints, SSE completion, approvals, uploads, and artifact traversal.

### P1: Build the retrieval pipeline

- Add document ingestion for TXT, Markdown, PDF, DOCX, spreadsheets, and images.
- Add local OCR for scanned documents and image extraction.
- Normalize metadata: tenant, project, user clearance, source path, checksum, page, and offsets.
- Chunk content with deterministic overlap and stable chunk IDs.
- Package and run an offline embedding model.
- Add PostgreSQL migrations and the pgvector schema.
- Implement batch indexing, checksum-based deduplication, re-indexing, and deletion.
- Implement vector and hybrid full-text retrieval with metadata filters.
- Add a `RAG_URL` HTTP adapter if retrieval is a separate service.

### P1: Make citations and authorization real

- Preserve source document, page, chunk, and score metadata in every retrieval result.
- Filter retrieval by authenticated tenant, role, clearance, and project.
- Validate every generated citation against retrieved source IDs.
- Treat retrieved text as untrusted data and defend against prompt injection.
- Add audit records for reads, tool calls, approvals, model calls, retrieval, and artifact downloads.

### P2: Complete agent capabilities

- Replace the deterministic per-type plans with model-emitted tool calls (the bounded re-plan loop is done).
- Add explicit planner, actor, observer, verifier, and delivery nodes or equivalent services.
- Add retries and bounded replanning after verification failure.
- Add OCR/VLM tools, code execution in a hardened sandbox, and richer artifact generators.
- Add background workers and a queue so jobs survive API process restarts.
- Add authentication, authorization, tenant isolation, rate limiting, secrets management, and request correlation IDs.

### P2: Offline deployment

- Add PostgreSQL plus pgvector to Docker Compose.
- Add an offline embedding/model service or local model volume.
- Add MinIO or a filesystem object store for large source files and artifacts.
- Add migrations, health checks, backup/restore, and data retention.
- Pin and mirror Python packages and model files for air-gapped installation.
- Add an end-to-end test that disables network access and proves ingestion, retrieval, citation, generation, verification, and artifact delivery.

## 10. Verification Commands

Run the unit tests from the repository root:

```powershell
pytest -q
```

Compile the application modules:

```powershell
python -m compileall app cli.py
```

Inspect the generated API contract after starting Uvicorn:

```powershell
Invoke-RestMethod 'http://localhost:8080/openapi.json'
```

A useful integration definition of done is:

- API starts with the documented environment.
- A job can be created and reaches a terminal status.
- SSE and polling describe the same state.
- Uploaded files are visible to the job's retrieval tool.
- Approval is required and auditable for configured risky actions.
- Verification blocks invalid or uncited artifacts.
- Artifacts can be downloaded without exposing host paths.
- The complete flow works with network access disabled when local models, embeddings, and databases are installed.

## Repository Reference Map

| Area | File | Responsibility |
|---|---|---|
| API assembly | `app/main.py` | Creates dependencies and FastAPI app. |
| HTTP contract | `app/api/routes.py` | REST, SSE, uploads, approvals, artifacts. |
| Schemas | `app/schemas/contracts.py` | Pydantic request and response shapes. |
| Orchestration | `app/orchestrator/service.py` | Workflow state, model call, planning, tools, verification. |
| Model routing | `app/models/router.py` | Task classification and logical model selection. |
| Model adapters | `app/models/adapter.py` | Fake and Ollama provider calls. |
| Policy | `app/policy/engine.py` | Risk tiers and allow/deny/approval decisions. |
| Tools | `app/tools/registry.py` | Search, file operations, and DOCX/XLSX/PPTX/PDF generation. |
| Sandbox | `app/tools/sandbox.py` | No-network execution of generated Python. |
| Tier access | `app/access.py`, `app/rag/tiered.py` | Roles and the downward tier read cascade. |
| Workspace | `app/workspace/manager.py` | Per-job directories and path containment. |
| Persistence | `app/storage/store.py` | Jobs, events, files, approvals, audit and queue. |
| Verification | `app/verification/verifier.py` | Delivery checks. |
| Model config | `config/models.yaml` | Enabled logical model registry entries. |
| Runtime config | `.env.example`, `app/config.py` | Environment variables and defaults. |
| Frontend | `frontend/` | The React dashboard; see its README. |
| Desktop contract | `ELECTRON_INTEGRATION.md` | Contract for a desktop shell that was never built. |
| Architecture notes | `ARCHITECTURE.md` | Intended lifecycle and extension points. |
| CLI | `cli.py` | Local command-line entry point; also `--report` and `--knowledge-transfer`. |
| Tests | `tests/test_core.py` | Current focused unit tests. |
