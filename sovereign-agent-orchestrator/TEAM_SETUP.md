# Team Setup And Collaboration

> Setup, ownership, API, deployment, and operational guidance are consolidated into [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md). This file is retained for historical collaboration notes.

## Recommended sharing model

Share the source through a private GitHub, GitLab, or Azure DevOps repository. Do not share the folder as a ZIP once development starts; Git gives the team branches, reviews, history, and conflict resolution.

Commit source code, migrations, tests, configuration templates, and documentation. Each developer should create their own `.env`, virtual environment, database volume, workspace, and Ollama model cache.

Never commit `.env`, API keys, `.venv/`, `orchestrator.db`, PostgreSQL data volumes, `workspace/` uploads, company documents, generated artifacts, logs, model weights, or Python caches. These paths are covered by `.gitignore`.

## First-time setup

```powershell
git clone <PRIVATE_REPOSITORY_URL>
cd sovereign-agent-orchestrator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
pytest -q
```

Start the local API:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

## System dependency: Tesseract (for image / scanned-document OCR)

```text
macOS:          brew install tesseract
Debian/Ubuntu:  sudo apt-get install -y tesseract-ocr
Windows:        install Tesseract OCR and put tesseract.exe on PATH
```

Without it, image and scanned-PDF OCR falls back to the local vision model
(`OCR_PREFER_VISION=true` forces the vision model even when Tesseract is present).

## Local Ollama setup

Install Ollama separately. Start it with these tuning flags -- benchmarked on a
32 GB M1 Max with `qwen3.6:27b`: flash attention alone is +25% generation speed
(6.1 -> 7.7 tok/s), and none of these cost measurable speed:

```bash
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

Two ways to get the models:

**A. From the shared local GGUF set** (no re-download; models live in
`~/sovereign-agent/models/`):

```bash
MODELS_DIR=~/sovereign-agent/models ./scripts/ollama_setup.sh
```

This registers `sov-local`, `sov-vision`, `sov-coder` and pulls `nomic-embed-text`.

**B. From the Ollama registry** -- these are the models `config/models.yaml` already
names, so nothing needs editing:

```bash
ollama pull qwen3.6:27b   # reasoner + coder + calc + docs + general (~17 GB)
ollama pull qwen3-vl:8b   # vision: scans, drawings, screenshots (~6 GB)
ollama pull bge-m3        # embeddings, multilingual (~1.2 GB)
```

Settings in `.env` for option B (this is what `.env.example` ships):

```text
MODEL_MODE=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.6:27b
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_VISION_MODEL=qwen3-vl:8b
RAG_EMBEDDING_DIMENSIONS=1024
LLM_ENABLE_THINKING=false
```

For option A instead, set `OLLAMA_MODEL=sov-local`, `OLLAMA_VISION_MODEL=sov-vision`,
`OLLAMA_EMBEDDING_MODEL=nomic-embed-text` and `RAG_EMBEDDING_DIMENSIONS=768`, and point
the `model:` fields in `config/models.yaml` at the `sov-*` names. The embedding
dimension must match the embedder or PostgreSQL rejects the vectors.

## Shared PostgreSQL/pgvector setup

Use Docker Compose for an integration environment:

```powershell
docker compose up --build
```

The PostgreSQL data volume is local to that machine. Do not put volume contents or company documents into Git.

## Authentication and tenant testing

Get a token from the dev-login endpoint (needs `DEV_AUTH_ENABLED=true` and a
`JWT_SECRET` of at least 32 characters):

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/dev/login \
  -H 'content-type: application/json' \
  -d '{"username":"Admin","password":"'"$DEV_ADMIN_PASSWORD"'"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/ready
```

The accounts are `Admin`, `Higher` and `Lower`, matching the three access tiers. Log in
as each and confirm a document uploaded by Admin is invisible to Lower -- that is the
isolation check that matters. Use different `X-Tenant-Id` values to verify tenant
separation on top of it. In production, tokens come from OIDC/JWT instead.

> Be careful with `DATABASE_URL`: the three tier variables fall back to it when unset,
> so setting it alone collapses the control plane and all three tiers into one database
> and every tier can read everything. Leave all four unset for local SQLite, or set all
> four. See `.env.example`.

## Git workflow

```powershell
git switch -c feat/document-ingestion
pytest -q
python -m compileall app cli.py
git diff
git add .
git diff --cached --stat
git commit -m "Describe the focused change"
git push -u origin feat/document-ingestion
```

Open a pull request and require review plus passing CI before merging. Review the staged diff for secrets, databases, uploads, and generated artifacts.

Suggested ownership: API/auth and tier isolation, SQLAlchemy/migrations/pgvector, extraction/OCR/embeddings, orchestration/policy/tools, the `frontend/` dashboard, and deployment/secrets/backups should each have a named owner.

## CI minimum

```powershell
pip install -r requirements.txt
pytest -q
python -m compileall app cli.py
```

Integration CI should start PostgreSQL with pgvector, apply `migrations/tier/001_initial_pgvector.sql` and `migrations/core/001_operational.sql`, upload test fixtures, and verify tenant filtering, citation validation, queue recovery, and artifact download.

## Remotes

The repository has two:

```text
origin      the team's working repository
submission  the repository the SIH submission is published from
```

Work on a feature branch and open a pull request; do not push directly to `main` on
either remote. Check `git remote -v` and `git status --short` before pushing, and
review the staged diff for secrets, databases, uploads and generated artifacts.
