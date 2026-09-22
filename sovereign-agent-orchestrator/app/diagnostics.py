import os
import platform
import shutil
import subprocess
import ctypes
from pathlib import Path

import httpx
import yaml
from sqlalchemy import text


SUPPORTED_PARSERS = ['txt', 'md', 'pdf', 'docx', 'pptx', 'csv', 'xlsx', 'xlsm', 'png', 'jpg', 'jpeg', 'tiff', 'bmp']


def _gpu_info():
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        rows = []
        for line in result.stdout.strip().splitlines():
            name, memory, driver = [item.strip() for item in line.split(',', 2)]
            rows.append({'name': name, 'vram_mb': int(memory), 'driver': driver})
        return rows
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return []


def hardware_snapshot(workspace_root):
    usage = shutil.disk_usage(workspace_root)
    ram_bytes = None
    if platform.system() == 'Windows':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('memory_load', ctypes.c_ulong), ('total', ctypes.c_ulonglong), ('available', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong), ('page_available', ctypes.c_ulonglong), ('virtual_total', ctypes.c_ulonglong), ('virtual_available', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram_bytes = status.total
    elif hasattr(os, 'sysconf'):
        ram_bytes = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    return {
        'os': platform.platform(),
        'cpu_count': os.cpu_count() or 1,
        'gpu': _gpu_info(),
        'ram_bytes': ram_bytes,
        'disk_free_bytes': usage.free,
    }


def model_profiles(path='config/models.yaml'):
    try:
        with open(path, encoding='utf-8') as stream:
            return yaml.safe_load(stream).get('models', [])
    except (OSError, AttributeError, yaml.YAMLError):
        return []


def recommended_model(profiles, hardware):
    gpu_memory = max((gpu['vram_mb'] for gpu in hardware['gpu']), default=0) / 1024
    enabled = [profile for profile in profiles if profile.get('enabled') and 'embedding' not in profile.get('capabilities', [])]
    if not enabled:
        return None
    viable = [profile for profile in enabled if profile.get('memory_gb', 0) <= max(gpu_memory, 4)]
    return max(viable or enabled, key=lambda profile: profile.get('quality_rank', 0))


def auto_configure(settings):
    if os.getenv('AUTO_CONFIG', 'true').lower() not in {'1', 'true', 'yes'} or os.getenv('OLLAMA_MODEL'):
        return None
    profiles = model_profiles(Path(__file__).resolve().parents[1] / 'config' / 'models.yaml')
    selected = recommended_model(profiles, hardware_snapshot(settings.workspace_root))
    if selected:
        settings.ollama_model = selected['model']
    return selected


def build_capabilities(settings, database, workspace):
    hardware = hardware_snapshot(workspace.root)
    profiles = model_profiles(Path(__file__).resolve().parents[1] / 'config' / 'models.yaml')
    selected = next((profile for profile in profiles if profile.get('model') == settings.ollama_model), None)
    embedding = next((profile for profile in profiles if profile.get('model') == settings.ollama_embedding_model), None)
    return {
        'hardware': hardware,
        'model': {
            'mode': settings.model_mode,
            'name': settings.ollama_model,
            'size': selected.get('size', 'unknown') if selected else 'unknown',
            'quantization': selected.get('quantization', 'unknown') if selected else 'unknown',
            'context_window': selected.get('context_window', 'unknown') if selected else 'unknown',
            'configured_profile': selected,
            'recommended_profile': recommended_model(profiles, hardware),
        },
        'embedding': {
            'name': settings.ollama_embedding_model,
            'quality': embedding.get('quality', 'unknown') if embedding else 'unknown',
            'dimensions': embedding.get('dimensions', 'unknown') if embedding else 'unknown',
        },
        'retrieval': {
            'semantic': bool(settings.ollama_embedding_model),
            'fallback': 'lexical',
            # _rerank runs unconditionally on both search paths, so reporting
            # False here was simply wrong -- and wrong in the direction that
            # invites someone to go looking for a switch that does not exist.
            'reranking': 'local_lexical_blend',
            'quality_evaluation': 'not_configured',
        },
        'document_parsing': {'supported_extensions': SUPPORTED_PARSERS, 'ocr': True, 'vision_fallback': True},
        'runtime': {'database_url': settings.database_url.split('@')[-1], 'workspace': str(workspace.root)},
    }


def check_readiness(settings, store, workspace, capabilities):
    checks = {'database': False, 'workspace': False, 'disk': False, 'model_service': True, 'embedding_service': True}
    errors = []
    try:
        with store.engine.connect() as db:
            db.execute(text('SELECT 1'))
        checks['database'] = True
    except Exception as exc:
        errors.append(f'database: {exc}')
    try:
        workspace.root.mkdir(parents=True, exist_ok=True)
        checks['workspace'] = workspace.root.is_dir()
        checks['disk'] = shutil.disk_usage(workspace.root).free > 512 * 1024 * 1024
    except OSError as exc:
        errors.append(f'workspace: {exc}')
    if settings.model_mode.lower() == 'ollama':
        try:
            response = httpx.get(settings.ollama_base_url.rstrip('/') + '/api/tags', timeout=3)
            response.raise_for_status()

            def _installed(models, wanted):
                # Ollama reports names as "name:tag" and defaults the tag to "latest".
                norm = {name for item in models for name in (item.get('name', ''), item.get('name', '').split(':', 1)[0])}
                return wanted in norm or wanted.split(':', 1)[0] in norm

            model_list = response.json().get('models', [])
            checks['model_service'] = _installed(model_list, settings.ollama_model)
            checks['embedding_service'] = _installed(model_list, settings.ollama_embedding_model)
            if not checks['model_service']:
                errors.append(f'model not installed: {settings.ollama_model}')
            if not checks['embedding_service']:
                errors.append(f'embedding model not installed: {settings.ollama_embedding_model}')
        except Exception as exc:
            checks['model_service'] = False
            checks['embedding_service'] = False
            errors.append(f'ollama: {exc}')
    return {'status': 'ready' if all(checks.values()) else 'degraded', 'checks': checks, 'errors': errors, 'capabilities': capabilities}
