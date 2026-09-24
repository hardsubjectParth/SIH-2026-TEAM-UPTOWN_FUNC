# Starting the project manually

Everything was stopped at the end of the last session (API, frontend dev
server, and `ollama serve`). This is the full sequence to bring it back up
from a cold machine, in order.

## 0. One-time setup (skip if already done)

```bash
cd sovereign-agent-orchestrator

# Backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

Backend `.env` — this checkout has no `.env` yet, only `.env.example`. Create
one:

```bash
cp .env.example .env
```

Then edit `.env` and set, at minimum:

```bash
MODEL_MODE=ollama
DEV_AUTH_ENABLED=true
DEV_ADMIN_PASSWORD=<pick-something>
JWT_SECRET=<32+ random characters — dev login 503s below that>
```

(`AUTH_MODE=jwt` and the other `DEV_*` values already default sensibly in
`.env.example`; `MODEL_MODE=fake` is the file's default and needs no model
server at all — see the fake-mode section below if that's all you need.)

⚠️ **Do not set `DATABASE_URL` on its own.** The three RAG tier databases fall
back to it when their own variables are unset:

```python
admin_database_url = os.getenv('ADMIN_DATABASE_URL', os.getenv('DATABASE_URL', 'sqlite:///./admin_tier.db'))
```

So setting only `DATABASE_URL` — the obvious move when pointing a local run at
Postgres — silently collapses the control plane and all three tiers into one
database, and every tier can then read every document. `REQUIRE_POSTGRES` does
not catch this, because all four *are* Postgres. Either leave all four unset
(the default gives four distinct SQLite files), or set all four:

```bash
DATABASE_URL=...          # control plane: jobs, files, conversations, audit
ADMIN_DATABASE_URL=...    # RAG tier: admin
HIGHER_DATABASE_URL=...   # RAG tier: higher
LOWER_DATABASE_URL=...    # RAG tier: lower
```

`docker-compose.yml` sets all four explicitly, so this only bites runs outside
Docker. To check what a given `.env` actually resolves to:

```bash
set -a; . ./.env; set +a
.venv/bin/python -c "
from app.config import settings
print('control:', settings.database_url)
for t,u in settings.tier_database_urls.items(): print(f'{t:>7}:', u)
print('distinct:', len({settings.database_url, *settings.tier_database_urls.values()}))"
```

Expect `distinct: 4`.

Frontend `.env` (already present in this checkout, `frontend/.env`):

```bash
VITE_API_BASE_URL=http://localhost:8080/api/v1
```

## 0b. PostgreSQL + pgvector (optional; SQLite is the default)

Four databases, one control plane and one per RAG tier. Order matters: the `vector`
extension needs a superuser, but the schema must be applied **as the owning role**, or
the app connects as a role that cannot index its own tables.

```bash
brew install postgresql@17 pgvector
brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

# roles and databases
psql -d postgres -c "CREATE ROLE orchestrator LOGIN PASSWORD '...'"   # repeat for
psql -d postgres -c "CREATE ROLE rag_admin    LOGIN PASSWORD '...'"   # rag_higher
psql -d postgres -c "CREATE ROLE rag_lower    LOGIN PASSWORD '...'"   # and rag_higher
psql -d postgres -c "CREATE DATABASE orchestrator OWNER orchestrator"  # and rag_* likewise

# extension as superuser, schema as the owner
for db in rag_admin rag_higher rag_lower; do psql -d $db -c "CREATE EXTENSION IF NOT EXISTS vector"; done
PGPASSWORD=... psql -h 127.0.0.1 -U orchestrator -d orchestrator -f migrations/core/001_operational.sql
PGPASSWORD=... psql -h 127.0.0.1 -U rag_admin    -d rag_admin    -f migrations/tier/001_initial_pgvector.sql
# ... rag_higher, rag_lower the same
```

The tier migration defaults to `vector(1024)` for bge-m3. For a 768-dimension embedder
apply it with `-v embedding_dim=768` and set `RAG_EMBEDDING_DIMENSIONS` to match, or
every chunk insert fails on a dimension the error message does not name.

Then set **all four** URLs in `.env` -- see the warning in section 0 about what setting
`DATABASE_URL` alone does -- and `REQUIRE_POSTGRES=true` so the service refuses to start
if any of them silently falls back to SQLite.

Check with the one-liner in section 0; expect `distinct: 4`. Retrieval should then
report `pgvector+local_rerank` rather than `embedding+local_rerank`.

## 1. Start Ollama

```bash
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

Run this in its own terminal tab (it stays in the foreground), or backgrounded:

```bash
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 nohup ollama serve > /tmp/ollama.log 2>&1 &
```

Confirm the models used by `.env.example`'s recommended set are pulled:

```bash
ollama list
```

Expect `qwen3.6:27b`, `qwen3-vl:8b`, `bge-m3`. If missing:

```bash
ollama pull qwen3.6:27b   # reasoner + coder + calc + docs + general (~17 GB)
ollama pull qwen3-vl:8b   # vision: scans, screenshots, drawings, handwriting (~6 GB)
ollama pull bge-m3        # embeddings, multilingual (~1.2 GB)
```

Real-model runs are memory-heavy: `qwen3.6:27b` is ~17.8 GB resident, and the
first prompt after startup pays the full load before it generates anything.
It runs fine on this machine at the settings above. An earlier freeze was
memory pressure with many other apps open rather than the model itself — if
you're running something larger, keep an eye on `Activity Monitor` → wired
memory, or `sysctl vm.swapusage`.

Use `MODEL_MODE=fake` (below) for quick UI checks that don't need real model
output.

## 2. Start the backend API

⚠️ **The app does not auto-load `.env`** — there's no `python-dotenv` wired
in on this branch, so a `.env` file sitting on disk is silently ignored
unless you actually export its values into the shell first. From
`sovereign-agent-orchestrator/`:

```bash
set -a
. ./.env
set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

(`set -a` / `set +a` makes every variable `source`d in between exported
automatically — plain `source .env` alone will not pass them to uvicorn.)

Verify:

```bash
curl -s http://127.0.0.1:8080/api/v1/health
curl -s http://127.0.0.1:8080/api/v1/ready | python3 -m json.tool
```

`/ready` reports the active model, embedding model, and vision model, and
whether each backing service is actually reachable.

### Fake mode (no Ollama needed)

For quick dashboard/UI checks without a model server, set `MODEL_MODE=fake`
in `.env` (its default) instead of `ollama`, and skip step 1 entirely — the
whole pipeline runs on deterministic stub responses.

## 3. Start the frontend

In a separate terminal, from `sovereign-agent-orchestrator/frontend/`:

```bash
npm run dev
```

Vite serves on `http://localhost:5173` by default.

## 4. Open and log in

Go to **http://localhost:5173**. The console signs in with an **email address**,
not a role name — the field is `type="email"`, so a browser will not submit a bare
`admin`.

| Email | Role | Password (`.env`) |
|---|---|---|
| `admin@sovereign.io` | Workspace Administrator | `DEV_ADMIN_PASSWORD` — currently `test-pass-123` |
| `higher@sovereign.io` | Operations Reviewer | `DEV_HIGHER_PASSWORD` |
| `lower@sovereign.io` | Operations Analyst | `DEV_LOWER_PASSWORD` |

Only the part before the `@` decides the account, so any domain works —
`admin@anything.com` signs in as the administrator. The domain carries no
authority and the password is still checked. Scripts and the CLI can still pass
a bare `admin` / `higher` / `lower`.

> ⚠️ `DEV_ADMIN_PASSWORD` is written above for the team's convenience. It grants
> administrator access to every tier whenever `DEV_AUTH_ENABLED=true`. Set
> `DEV_AUTH_ENABLED=false` in anything resembling a real deployment, and change
> these passwords before this repository is shared beyond the team.

This dev-login screen only works while `DEV_AUTH_ENABLED=true` — it's not
present/usable in a production deployment.

### If the login silently does nothing

Three causes, all seen in practice:

1. **CORS.** `CORS_ALLOW_ORIGINS` in `.env` lists the frontend's origin. If you
   start Vite on any port other than 5173 — because 5173 is already taken — the
   browser blocks the login call before it reaches the API and the form just sits
   there. Add the port you are using, e.g.
   `http://localhost:5174,http://127.0.0.1:5174`.
2. **Preview data.** If `VITE_PREVIEW_DATA=true` is set for the frontend, the
   console answers from built-in fixtures and never calls the backend: sign-in
   accepts any password, and you see three invented jobs and two invented
   documents. Leave it unset for a real run.
3. **Expired session.** Dev tokens last `DEV_AUTH_TTL_SECONDS` (default 900, max
   3600). When one expires the Knowledge Base renders "No documents ingested yet"
   rather than sending you back to the login screen — it looks like lost data, not
   a timeout. Set `DEV_AUTH_TTL_SECONDS=3600` and sign in fresh before a demo.

### Watching a run

Send a prompt from **Intelligence Feed**. The assistant turn renders a live
six-stage pipeline — task received → model selection → execution plan → tool
execution → verification → delivery — driven by the job's SSE event stream.
Completed stages tick and fill the connector; the active one pulses.

Each stage shows what the backend actually reported: the routed model with its
task type, confidence and reason; the planned steps and their tools; each tool
call marked `ok` / `failed` / `denied by policy` as it finishes; the
verification checklist; and the artifacts produced. The raw event log sits
collapsed underneath.

Note on modes: in `MODEL_MODE=fake` a job finishes in well under a second, so
the pipeline jumps straight to its completed state. To actually watch it
advance stage by stage, run with `MODEL_MODE=ollama` — the first prompt will
also sit on *Model Selection* for a while as the 27B loads into memory.

### Attaching an image

Attaching an image routes the job to `qwen3-vl:8b` whatever the prompt says —
a question about a picture rarely names anything visual ("give the dimensions
for this"), so the attachment decides, not the wording. The Model Selection
stage shows `capability: vision` with the reason. The image itself is sent to
the model, so it is read directly rather than through whatever OCR indexed.

Two things to expect on a first run:

- Swapping between the 27B and the 8B vision model costs a reload each way.
  `OLLAMA_MAX_LOADED_MODELS=1` (step 1) means only one stays resident, which is
  the right trade on 32 GB but makes an alternating text/image conversation
  slow. Measured: ~160s for a dimensioned engineering drawing once loaded.
- Uploading an image whose text Tesseract cannot read triggers a vision-OCR
  pass during ingest, and ingest is synchronous — the upload request blocks on
  it, bounded by `OCR_VISION_TIMEOUT_SECONDS` (default 180). A dense drawing
  measured at 393s, so it will sometimes hit that ceiling; the file is then
  indexed as having no readable text rather than as OCR noise, and questions
  about it are still answered from the attached image.

## Stopping everything

Stop by port, not by process name:

```bash
kill $(lsof -nP -iTCP:8080 -sTCP:LISTEN -t)    # backend API
kill $(lsof -nP -iTCP:5173 -sTCP:LISTEN -t)    # frontend
pkill -f "ollama serve"                         # model server
```

Stopping `ollama serve` also unloads the model and returns its ~17.8 GB.

> ⚠️ Do not use `pkill -f "uvicorn app.main:app"` or `pkill -f "node .*/vite"`.
> Those patterns are not specific to this project: on a machine with another
> FastAPI or Vite project open they will kill that one instead, which has
> happened. Killing by listening port only ever hits the service you meant.

To check what a port actually belongs to before killing it:

```bash
lsof -a -p <pid> -d cwd -Fn      # prints the process's working directory
```

Or just `Ctrl+C` each foreground terminal if you didn't background them.

## Quick reference — what's running, where

| Service | Command | Port | Depends on |
|---|---|---|---|
| Ollama | `ollama serve` | 11434 | nothing |
| Backend API | `uvicorn app.main:app` | 8080 | Ollama (unless `MODEL_MODE=fake`) |
| Frontend | `npm run dev` (vite) | 5173 | Backend API |

Start in that order; stop in reverse (or just `pkill` all three, order
doesn't matter there).
