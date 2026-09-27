from contextlib import asynccontextmanager
import asyncio
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings, validate_production_database_settings
from app.network import network_monitor
from app.storage.store import Store
from app.workspace.manager import Workspace
from app.models.router import ModelRouter
from app.models.adapter import OllamaAdapter, FakeModel
from app.policy.engine import Policy
from app.tools.registry import ToolRegistry
from app.verification.verifier import Verifier
from app.orchestrator.service import Orchestrator
from app.rag.tiered import TieredRagService
from app.api.routes import router, init_service
from app.queue import run_worker
from app.diagnostics import auto_configure, build_capabilities, check_readiness
from app.operations import RuntimeControls, REQUESTS, REQUEST_LATENCY
from time import perf_counter

validate_production_database_settings(settings)
store = Store(settings.database_url)
ws = Workspace(settings.workspace_root)
auto_configure(settings)
# Three physically isolated pgvector databases: admin, higher, lower.
# Role-based read/write routing lives in app/access.py and app/rag/tiered.py
# so the model is never handed context from a database a user cannot query.
rag = TieredRagService(settings.tier_database_urls, settings.ollama_base_url, settings.ollama_embedding_model, settings.ollama_vision_model, settings.rag_embedding_dimensions, settings.ollama_keep_alive)

model_router = ModelRouter('config/models.yaml')

if settings.model_mode.lower() == 'ollama':
    model = OllamaAdapter(
        settings.ollama_base_url,
        settings.ollama_model,
        settings.ollama_keep_alive,
    )
else:
    model = FakeModel()

svc = Orchestrator(
    store,
    ws,
    model_router,
    Policy(),
    ToolRegistry(ws, rag),
    Verifier(settings.workspace_root),
    model,
    ollama_base_url=settings.ollama_base_url,
    model_mode=settings.model_mode,
    keep_alive=settings.ollama_keep_alive,
    max_iterations=settings.max_iterations,
    max_tool_calls=settings.max_tool_calls,
)
svc.controls = RuntimeControls(store, settings)
svc.network = network_monitor
if settings.model_mode.lower() == 'ollama':
    from urllib.parse import urlparse
    _o = urlparse(settings.ollama_base_url)
    network_monitor.probe_local(_o.hostname or '127.0.0.1', _o.port or 11434)

svc.capabilities = build_capabilities(settings, store, ws)
svc.readiness = check_readiness(settings, store, ws, svc.capabilities)

init_service(svc)

@asynccontextmanager
async def lifespan(_app):
    svc.readiness = check_readiness(settings, store, ws, svc.capabilities)
    worker = asyncio.create_task(run_worker(store, svc, settings.worker_concurrency)) if os.getenv('RUN_WORKER', 'true').lower() in {'1', 'true', 'yes'} else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()

app = FastAPI(
    title=settings.app_name,
    version='1.0.0',
    lifespan=lifespan,
)

cors_origins = [origin.strip() for origin in os.getenv('CORS_ALLOW_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'DELETE', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type'],
)

# Liveness and scrape endpoints are polled by the browser, container healthchecks and
# Prometheus. Counting them against the request budget spends it on traffic that is not
# user work -- and because the budget is keyed by client IP, on a single-workstation
# deployment (every console tab arriving as 127.0.0.1) that budget is shared by the
# whole installation rather than held per person.
UNLIMITED_PATHS = frozenset({'/api/v1/health', '/api/v1/ready', '/metrics'})


@app.middleware('http')
async def operational_middleware(request, call_next):
    started = perf_counter()
    status = 500
    exempt = (request.url.path or '/') in UNLIMITED_PATHS
    if not exempt and not svc.controls.limiter.allow(request.client.host if request.client else 'unknown'):
        status = 429
        from fastapi.responses import JSONResponse
        response = JSONResponse({'detail': 'RATE_LIMIT_EXCEEDED'}, status_code=status)
    else:
        response = await call_next(request)
        status = response.status_code
    elapsed = perf_counter() - started
    path = request.url.path or '/'
    REQUESTS.labels(request.method, path, str(status)).inc()
    REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    return response

app.include_router(router)
