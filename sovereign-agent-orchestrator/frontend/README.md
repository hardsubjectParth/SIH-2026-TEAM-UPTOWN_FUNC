# Frontend

The Sovereign Agent Orchestrator dashboard: React + TypeScript + Vite, talking to the
FastAPI backend over REST and SSE. This is the only client in the repository.

## Stack

React 19, TypeScript, Vite, React Router, Tailwind CSS v4, Framer Motion, Radix UI
(tabs, dialog), SWR for polling. Dev server on `http://localhost:5173`; the API on
`http://127.0.0.1:8080`.

## Structure

```text
frontend/src/
├── components/
│   ├── Login.tsx                 Dev-login form (Admin / Higher / Lower)
│   ├── ProtectedRoute.tsx        Redirects unauthenticated users to /login
│   ├── shell/
│   │   ├── Shell.tsx             App frame around every /app route
│   │   ├── Sidebar.tsx           Navigation and session/role display
│   │   ├── icons.tsx             Inline SVG icon set
│   │   └── rank.ts               Role → display rank helpers
│   ├── feed/
│   │   ├── Composer.tsx          Prompt input and attachment picker
│   │   ├── ProtocolPipeline.tsx  Live six-stage run readout, driven by job events
│   │   ├── ActivityTimeline.tsx  Raw event log (collapsed under the pipeline)
│   │   ├── ApprovalGate.tsx      Approve/reject UI for awaiting_approval jobs
│   │   ├── ArtifactsRail.tsx     Artifacts produced by the current turn
│   │   └── MetricsCard.tsx       Per-run counters
│   ├── knowledge/
│   │   └── IngestPanel.tsx       Upload with a server-provided scope selector
│   └── shared/                   StatCard, StatusDot, StatusPill, TierLabel, …
├── pages/
│   ├── IntelligenceFeedPage.tsx  Conversation view; the main workspace
│   ├── AgentTasksPage.tsx        Job list
│   ├── KnowledgeBasePage.tsx     Indexed-document search and file listing
│   ├── IngestKnowledgePage.tsx   Upload and index documents
│   └── ArtifactsPage.tsx         Generated artifacts, with download
├── hooks/                        useConversations, useJob, useFiles,
│                                 useKnowledgeSearch, useSystem
├── context/AuthContext.tsx       Session token and user, persisted
├── services/api.ts               The single place that talks to the API
├── types/api.ts                  Response contracts
├── App.tsx                       Routes and motion config
└── index.css                     Design tokens and base styles
```

## Routing

```text
/                        → redirect to /app/feed
/login                   Dev login
/app/feed                Intelligence Feed (new conversation)
/app/feed/:id            Intelligence Feed (existing conversation)
/app/tasks               Agent Tasks
/app/knowledge           Knowledge Base
/app/knowledge/ingest    Ingest
/app/artifacts           Artifacts
```

Unknown paths redirect to `/app/feed`. Every `/app/*` route renders inside `Shell`.

## Authentication

Authentication is real, not mocked. `AuthContext` calls `devLogin()` in
`services/api.ts`, which posts to `POST /api/v1/auth/dev/login` and stores the returned
JWT and user. Every subsequent request sends `Authorization: Bearer <token>`.

The three accounts — `Admin`, `Higher`, `Lower` — correspond to the backend's three
access tiers, and their passwords are the `DEV_*_PASSWORD` values in the backend `.env`.
This endpoint only exists while `DEV_AUTH_ENABLED=true`; a production deployment gets
its tokens from an OIDC provider instead, and only `AuthContext` and `api.ts` would
change.

## Backend connection

`services/api.ts` is the only module that performs network calls. Its base URL comes
from `VITE_API_BASE_URL` (see `frontend/.env`), defaulting to
`http://127.0.0.1:8080/api/v1`.

Endpoints in use:

```text
POST   /auth/dev/login                       obtain a session token
GET    /health  /ready                       status and model readiness
GET    /files          POST /files           list and upload documents
GET    /files/scopes                         tiers this role may upload into
DELETE /files/{id}                           remove a document
POST   /knowledge/search                     search the readable tiers
GET    /conversations  POST /conversations   threads
GET    /conversations/{id}/messages          history
POST   /chat                                 submit a prompt, returns a job_id
GET    /agent                                job list
GET    /agent/{job_id}                       job detail
GET    /agent/{job_id}/events                SSE progress stream
POST   /agent/{job_id}/approve  /cancel      approval and cancellation
GET    /agent/{job_id}/artifacts             list and download artifacts
```

The upload scope selector is populated from `GET /files/scopes` — the browser never
chooses a database tier. The API validates the JWT, derives the role, and routes each
upload and query server-side.

## Architecture rule

The frontend talks to the FastAPI API and nothing else. It must never reach a model, a
model router, RAG, PostgreSQL, an agent tool or the sandbox directly, and it never sees
host filesystem paths — artifacts are fetched through the artifact endpoint.

```text
React frontend
      │ REST + SSE
      ▼
FastAPI API
      │
      ▼
Agent Orchestrator
      ├── Model router / models
      ├── RAG (per-tier databases)
      ├── Tools
      ├── Policy
      ├── Verification
      └── Storage
```

## Running it

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The backend must be running for anything past the login screen.
[../start.md](../start.md) is the full runbook for the whole local stack; the short
version, from `sovereign-agent-orchestrator/`:

```bash
set -a; . ./.env; set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Build and typecheck:

```bash
npm run build        # tsc -b && vite build
npm run lint
```

## Tier test script

Worth running after any change to upload, search or auth — it is the check that the
access model still holds end to end.

- **Admin**: upload an admin-scoped file containing a unique phrase. Search it as Admin
  (must appear); sign out and search as Higher and Lower (must not appear).
- **Higher**: upload a higher-scoped file with a second unique phrase. Search it as
  Higher and Admin (must appear); search as Lower (must not appear).
- **Any role**: upload a lower/everyone-scoped file with a third phrase. Search it as
  Lower, Higher and Admin (must appear).
- **Lower**: the scope selector must not offer Higher or Admin options.

Note what this does *not* test, because the backend does not provide it: two users of
the same tier and tenant can retrieve each other's documents. Tier isolation is the
guarantee; per-user isolation within a tier is not.
