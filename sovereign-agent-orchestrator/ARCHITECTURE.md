# Architecture & Internals

> A short map of the runtime. The complete architecture, state machine, security
> invariants, API, deployment, testing and roadmap are maintained in
> [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md); [README.md](README.md) is the operational guide.

## Clients

The API is the only integration surface, and it is client-agnostic: REST plus SSE, no
client-side knowledge of models, RAG, databases, tool internals or host filesystem
paths. The client shipped in this repository is the Vite + React dashboard in
`frontend/`, which runs as an ordinary browser app against the API. Any other
REST/SSE client — desktop, web or script — integrates the same way.

## End-to-end lifecycle

1. A client uploads a file, or references one it uploaded earlier.
2. `POST /api/v1/agent/run` (or `POST /api/v1/chat`) creates a durable job and returns
   `job_id` immediately.
3. The router classifies the task deterministically and selects a registry model. An
   attached image overrides the choice to a vision-capable model, because the wording
   of a question about a picture usually names nothing visual.
4. Retrieval runs against the RAG tier databases the caller's role may read. Attached
   images are also passed to the model directly, so a drawing can be read even when
   nothing useful was ever OCR'd from it.
5. The planner emits structured steps. Reasoning is not exposed as the answer:
   `OllamaAdapter` strips inline `<think>` blocks, which thinking models emit into
   `content` whether or not `think: false` was requested.
6. Each proposed tool is resolved through the registry and checked by deterministic
   policy.
7. Approved tools execute only inside the job workspace.
8. Results become observations.
9. The verifier evaluates task-specific completion and blocks delivery on failure.
10. Medium/high-risk actions can pause at `awaiting_approval` and resume only through
    the approval endpoint.
11. Artifacts are discovered inside `output/` and exposed through an API download
    endpoint.
12. The client receives progress via SSE and renders the final answer and artifacts.

## State machine

`queued → planning → acting → observing → verifying → delivering → done`

Alternative paths: `acting → awaiting_approval → acting`; `verifying → planning`
(bounded retry — the model is re-prompted with the failed checks, up to
`MAX_ITERATIONS`); terminal `failed` / `cancelled`.

## Security invariants

- The model never makes authorization decisions.
- RAG authorization is **tier membership**, not a filter. Content lives in three
  separate databases (admin / higher / lower) and a role opens connections only to the
  tiers it may read — see `app/access.py` and `app/rag/tiered.py`. Everything inside a
  readable tier is readable by that role; the system isolates tiers from each other,
  not users within one tier.
- The file surface — listing, download, and attaching a file to a job — is separately
  owner-scoped: owner, active unexpired share, or administrator, within one tenant.
- Unknown tools are denied.
- Paths are canonicalized and must remain under `WORKSPACE_ROOT/<job_id>`.
- No arbitrary URL fetch tool exists.
- Artifact paths are never handed to a client as host paths.
- Generated code runs only through `run_python`, in a no-network sandbox with
  CPU / memory / file-size caps and no host filesystem or Docker socket access
  (`app/tools/sandbox.py`: nsjail / bwrap / firejail on Linux, `sandbox-exec` on
  macOS, rlimits floor). A stronger container/gVisor jail is the production upgrade.
- Uploaded documents are untrusted data. Instructions found inside them are not
  authorization.

## Extension points

| Layer | Now | Next |
|---|---|---|
| Model | Fake → per-model Ollama adapters | OpenAI-compatible vLLM / SGLang |
| RAG | Per-tier SQLite, PostgreSQL + pgvector in production | Shared vector service preserving the tier boundary |
| Sandbox | `run_python` (namespaces / seatbelt / rlimits) | gVisor / Firecracker |
| Artifact | python-docx / python-pptx / openpyxl / pymupdf | Templated generators |
| Storage | SQLite for development | PostgreSQL for production |
| Ingest | Synchronous, so a slow vision-OCR pass blocks the upload | Queued ingest with a job to poll |
