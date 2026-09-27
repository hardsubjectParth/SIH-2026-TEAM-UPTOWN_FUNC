import os


def _bool(name, default='false'):
 return os.getenv(name, default).lower() in {'1', 'true', 'yes', 'on'}


class Settings:
 app_name=os.getenv('APP_NAME','Sovereign Agent Orchestrator'); api_host=os.getenv('API_HOST','0.0.0.0'); api_port=int(os.getenv('API_PORT','8080')); database_url=os.getenv('DATABASE_URL','sqlite:///./orchestrator.db'); workspace_root=os.getenv('WORKSPACE_ROOT','./workspace'); model_mode=os.getenv('MODEL_MODE','fake'); ollama_base_url=os.getenv('OLLAMA_BASE_URL','http://localhost:11434'); ollama_model=os.getenv('OLLAMA_MODEL','qwen2.5vl:3b'); ollama_embedding_model=os.getenv('OLLAMA_EMBEDDING_MODEL','nomic-embed-text'); ollama_vision_model=os.getenv('OLLAMA_VISION_MODEL','qwen2.5vl:3b'); ollama_keep_alive=os.getenv('OLLAMA_KEEP_ALIVE','5m'); rag_url=os.getenv('RAG_URL',''); rag_embedding_dimensions=int(os.getenv('RAG_EMBEDDING_DIMENSIONS','768')); require_postgres=_bool('REQUIRE_POSTGRES'); max_iterations=int(os.getenv('MAX_ITERATIONS','3')); max_tool_calls=int(os.getenv('MAX_TOOL_CALLS','12')); job_timeout_seconds=int(os.getenv('JOB_TIMEOUT_SECONDS','120')); tool_timeout_seconds=int(os.getenv('TOOL_TIMEOUT_SECONDS','30')); worker_concurrency=int(os.getenv('WORKER_CONCURRENCY','1')); max_upload_bytes=int(os.getenv('MAX_UPLOAD_BYTES',str(50*1024*1024))); user_storage_quota_bytes=int(os.getenv('USER_STORAGE_QUOTA_BYTES',str(5*1024*1024*1024))); rate_limit_per_minute=int(os.getenv('RATE_LIMIT_PER_MINUTE','600')); clamav_host=os.getenv('CLAMAV_HOST',''); clamav_port=int(os.getenv('CLAMAV_PORT','3310')); malware_scan_required=_bool('MALWARE_SCAN_REQUIRED')
 # Three physically isolated pgvector databases for RAG content, one per access tier.
 # DATABASE_URL above remains the single control-plane database (jobs, files, conversations, audit).
 admin_database_url=os.getenv('ADMIN_DATABASE_URL', os.getenv('DATABASE_URL','sqlite:///./admin_tier.db'))
 higher_database_url=os.getenv('HIGHER_DATABASE_URL', os.getenv('DATABASE_URL','sqlite:///./higher_tier.db'))
 lower_database_url=os.getenv('LOWER_DATABASE_URL', os.getenv('DATABASE_URL','sqlite:///./lower_tier.db'))

 @property
 def tier_database_urls(self):
  return {'admin': self.admin_database_url, 'higher': self.higher_database_url, 'lower': self.lower_database_url}
settings=Settings()


def validate_production_database_settings(settings):
 """When REQUIRE_POSTGRES=true, refuse to start unless every database -- the
 control plane and all three RAG tiers -- is PostgreSQL. Stops a production
 deployment silently falling back to per-process SQLite files."""
 if not settings.require_postgres:
  return
 urls = {'control': settings.database_url, **settings.tier_database_urls}
 invalid = [name for name, url in urls.items() if not url.startswith('postgresql')]
 if invalid:
  raise RuntimeError('POSTGRES_REQUIRED_FOR_PRODUCTION: ' + ', '.join(invalid))
