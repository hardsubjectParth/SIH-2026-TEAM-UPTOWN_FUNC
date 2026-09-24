import base64
from pathlib import Path
from app.policy.engine import Policy,Decision
from app.workspace.manager import Workspace
from app.models.router import ModelRouter
from app.rag.service import RagService

def test_policy_unknown_denied(): assert Policy().check('nope',{}).decision==Decision.DENY
def test_workspace_traversal(tmp_path):
 w=Workspace(tmp_path); w.create('j')
 try:w.safe('j','../../secret')
 except ValueError as e: assert str(e)=='PATH_OUTSIDE_JOB_WORKSPACE'
 else: assert False

def test_router_document(): assert ModelRouter('config/models.yaml').route('summarize inspection report')['task_type']=='document_workflow'
def test_router_multimodal(): assert ModelRouter('config/models.yaml').route('inspect scanned drawing image')['task_type']=='multimodal'

def test_rag_extracts_csv_and_searches_without_ollama(tmp_path):
	source = tmp_path / 'findings.csv'
	source.write_text('finding,status\nfire extinguisher,recertify\n')
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	assert 'fire extinguisher' in rag.extract(source)
	import asyncio
	indexed = asyncio.run(rag.ingest(source))
	assert indexed['chunks'] == 1
	hits = asyncio.run(rag.search('fire extinguisher'))
	assert hits[0]['source'] == 'findings.csv'

def test_rag_extracts_docx(tmp_path):
	from docx import Document
	source = tmp_path / 'report.docx'
	document = Document()
	document.add_paragraph('Pump P-101 requires inspection.')
	document.save(source)
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	assert 'Pump P-101' in rag.extract(source)

def test_rag_extracts_pptx(tmp_path):
	from pptx import Presentation
	source = tmp_path / 'briefing.pptx'
	presentation = Presentation()
	slide = presentation.slides.add_slide(presentation.slide_layouts[1])
	slide.shapes.title.text = 'Turbine Overhaul'
	slide.placeholders[1].text = 'Bearing replacement due Q3.'
	presentation.save(source)
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	extracted = rag.extract(source)
	assert 'Turbine Overhaul' in extracted
	assert 'Bearing replacement due Q3.' in extracted

def test_generate_pdf_tool_writes_readable_pdf(tmp_path):
	from app.tools.registry import ToolRegistry
	workspace = Workspace(tmp_path / 'workspace')
	job_id = 'job'
	workspace.create(job_id)
	tools = ToolRegistry(workspace)
	result = tools.execute(job_id, 'generate_pdf', {
		'filename': 'report.pdf',
		'title': 'Turbine Overhaul Report',
		'sections': [{'heading': 'Findings', 'body': 'Bearing replacement due Q3.'}],
		'citations': ['maintenance_log.csv'],
	})
	output = workspace.safe(job_id, result['path'])
	assert output.read_bytes().startswith(b'%PDF')
	import pymupdf
	doc = pymupdf.open(output)
	text = ''.join(page.get_text() for page in doc)
	doc.close()
	assert 'Turbine Overhaul Report' in text
	assert 'Bearing replacement due Q3.' in text

def test_workbook_report_summarizes_recruitment_data(tmp_path):
	from openpyxl import Workbook
	from app.rag.report import analyze_workbook, write_workbook_report
	source = tmp_path / 'responses.xlsx'
	workbook = Workbook()
	sheet = workbook.active
	sheet.title = 'Form Responses 1'
	sheet.append(['Name', 'Branch', 'Year', 'Domain', 'Rate collaboratively'])
	sheet.append(['A', 'B.Tech CE', '2nd', 'Marketing, Technical', 5])
	sheet.append(['B', 'B.Tech CE', '1st', 'Marketing', 3])
	workbook.save(source)
	analysis = analyze_workbook(source)
	assert analysis['sheets'][0]['rows'] == 2
	assert analysis['sheets'][0]['summary']['domains']['Marketing'] == 2
	result = write_workbook_report(source, tmp_path / 'reports', analysis)
	assert Path(result['docx']).is_file()
	assert Path(result['json']).is_file()

def test_knowledge_transfer_report_combines_sources(tmp_path):
	from app.rag.report import write_knowledge_transfer_report
	sources = [tmp_path / 'problem.md', tmp_path / 'README.md']
	sources[0].write_text('# Problem\nBuild a safe knowledge system.')
	sources[1].write_text('# Setup\nRun the local server.')
	result = write_knowledge_transfer_report(sources, tmp_path / 'reports', lambda path: path.read_text())
	assert Path(result['docx']).is_file()
	assert result['analysis']['sources'][0]['source'] == 'problem.md'

def test_requested_tools_are_scoped_and_auditable(tmp_path):
	from app.tools.registry import ToolRegistry
	from app.rag.tiered import TieredRagService
	workspace = Workspace(tmp_path / 'workspace')
	job_id = 'job'
	workspace.create(job_id)
	input_path = workspace.safe(job_id, 'input/source.md', True)
	input_path.write_text('Contact test@example.com or 9876543210.')
	# Production always routes tool calls through the tier-aware wrapper so a tool
	# invocation cannot silently read across the admin/higher/lower boundary.
	urls = {tier: f'sqlite:///{tmp_path / (tier + "_rag.db")}' for tier in ('admin', 'higher', 'lower')}
	rag = TieredRagService(urls, 'http://localhost:11434', 'nomic-embed-text', 'qwen2.5vl:3b')
	tools = ToolRegistry(workspace, rag)
	identity = {'user_id': 'u1', 'tenant_id': 't1', 'role': 'lower'}
	assert tools.execute(job_id, 'ingest_document', {'path': 'input/source.md', 'identity': identity})['chunks'] == 1
	assert tools.execute(job_id, 'list_sources', {'identity': identity})['sources']
	assert tools.execute(job_id, 'ocr_document', {'path': 'input/source.md'})['text']
	redacted = tools.execute(job_id, 'redact_pii', {'path': 'input/source.md'})
	assert redacted['redactions'] == 2
	assert '[REDACTED_EMAIL]' in workspace.safe(job_id, redacted['path']).read_text()
	assert tools.execute(job_id, 'search_db', {'query': 'SELECT name FROM rag_documents', 'identity': identity})['rows']
	import pytest
	with pytest.raises(ValueError, match='SMTP_NOT_CONFIGURED'):
		tools.execute(job_id, 'send_email', {'to': 'team@example.com', 'subject': 'Draft'})
	assert Policy().check('send_email', {}).decision == Decision.REQUIRE_APPROVAL

def test_conversation_history_is_durable_and_tenant_scoped(tmp_path):
 from app.storage.store import Store
 store = Store(f'sqlite:///{tmp_path / "store.db"}')
 identity = {'user_id': 'u1', 'tenant_id': 't1', 'role': 'user'}
 conversation = store.create_conversation('c1', 't1', 'u1', 'Research')
 assert conversation['title'] == 'Research'
 store.add_message('m1', 'c1', 'user', 'What is in the report?')
 store.add_message('m2', 'c1', 'assistant', 'The report contains findings.', [{'chunk_id': 'x'}])
 assert [message['role'] for message in store.messages('c1')] == ['user', 'assistant']
 assert store.messages('c1')[1]['citations'][0]['chunk_id'] == 'x'
 assert store.conversation('c1', {'user_id': 'u2', 'tenant_id': 't1', 'role': 'user'}) is None

def test_delete_document_removes_indexed_chunks(tmp_path):
 source = tmp_path / 'source.md'
 source.write_text('Retention policy requires annual review.')
 rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
 import asyncio
 asyncio.run(rag.ingest(source, {'file_id': 'file-1', 'tenant_id': 't1'}))
 assert asyncio.run(rag.search('retention policy'))
 assert rag.delete_document('file-1') == 1
 assert asyncio.run(rag.search('retention policy')) == []

def test_file_sharing_and_attachment_scope_are_enforced(tmp_path):
 from app.storage.store import Store
 store = Store(f'sqlite:///{tmp_path / "store.db"}')
 owner = {'user_id': 'alice', 'tenant_id': 't1', 'role': 'user'}
 reader = {'user_id': 'bob', 'tenant_id': 't1', 'role': 'user'}
 store.register_file('f1', 'alice', 't1', 'a.md', str(tmp_path / 'a.md'), {})
 store.register_file('f2', 'alice', 't1', 'b.md', str(tmp_path / 'b.md'), {})
 assert store.accessible_file_ids(reader) == []
 share = store.share_file('f1', owner, 'bob')
 assert share['shared_with_user_id'] == 'bob'
 assert store.accessible_file_ids(reader) == ['f1']
 rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
 first = tmp_path / 'a.md'; second = tmp_path / 'b.md'
 first.write_text('private alpha policy'); second.write_text('private beta policy')
 rag.ingest_sync(first, {'file_id': 'f1', 'tenant_id': 't1', 'owner_id': 'alice'})
 rag.ingest_sync(second, {'file_id': 'f2', 'tenant_id': 't1', 'owner_id': 'alice'})
 hits = rag.search_sync('private policy', file_ids=['f1'])
 assert {hit['metadata']['file_id'] for hit in hits} == {'f1'}
 assert store.revoke_share(share['id'], owner)
 assert store.accessible_file_ids(reader) == []

def test_jwt_identity_uses_signed_claims(monkeypatch):
 import jwt
 from app.auth import current_identity
 monkeypatch.setenv('AUTH_MODE', 'jwt')
 monkeypatch.setenv('JWT_SECRET', 'test-secret-with-at-least-32-bytes')
 token = jwt.encode({'sub': 'alice', 'tenant_id': 't1', 'role': 'user', 'clearance': 'internal', 'exp': 4102444800}, 'test-secret-with-at-least-32-bytes', algorithm='HS256')
 identity = current_identity(authorization=f'Bearer {token}')
 assert identity['user_id'] == 'alice'
 assert identity['tenant_id'] == 't1'

def test_local_reranker_marks_and_orders_results(tmp_path):
 rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
 first = tmp_path / 'first.md'; second = tmp_path / 'second.md'
 first.write_text('inspection interval annual review')
 second.write_text('inspection unrelated note')
 rag.ingest_sync(first, {'file_id': 'f1', 'tenant_id': 't1'})
 rag.ingest_sync(second, {'file_id': 'f2', 'tenant_id': 't1'})
 hits = rag.search_sync('inspection annual review', file_ids=['f1', 'f2'])
 assert hits[0]['metadata']['file_id'] == 'f1'
 assert 'local_rerank' in hits[0]['retrieval_method']

def test_request_limiter_blocks_after_limit():
 from app.operations import RequestLimiter
 limiter = RequestLimiter(1)
 assert limiter.allow('user')
 assert not limiter.allow('user')


def test_router_classifies_the_new_task_types():
 router = ModelRouter('config/models.yaml')
 assert router.classify('write a python function with a unit test') == 'coding'
 assert router.classify('calculate the pump flow rate and show the steps') == 'calculation'
 assert router.classify('profile the attached excel workbook') == 'spreadsheet'
 assert router.classify('build a slide deck briefing the board') == 'presentation'
 assert router.classify('transcribe the scanned drawing') == 'multimodal'
 assert router.classify('what time is it') == 'general'
 # A bare "pdf" ask has none of document_workflow's other keywords (report,
 # summary, memo, ...) -- without "pdf" itself in the pattern this fell through
 # to 'general', which never runs a plan, so no generate_pdf tool call ever
 # happened and the model was left to (wrongly) say it can't produce a PDF.
 assert router.classify('give me a pdf explaining the maintenance schedule') == 'document_workflow'


def test_sandbox_runs_code_and_blocks_network(tmp_path):
 from app.tools.sandbox import run_script
 ok = tmp_path / 'ok.py'
 ok.write_text('print(2 + 2)\n')
 result = run_script(ok, tmp_path / 'run', timeout=10)
 assert result['passed'] and result['exit_code'] == 0 and '4' in result['stdout']

 net = tmp_path / 'net.py'
 net.write_text("import socket\nsocket.create_connection(('1.1.1.1', 80), 2)\n")
 blocked = run_script(net, tmp_path / 'run', timeout=10)
 assert not blocked['passed']


def _orchestrator(tmp_path, model):
 from app.storage.store import Store
 from app.tools.registry import ToolRegistry
 from app.verification.verifier import Verifier
 from app.orchestrator.service import Orchestrator
 workspace = Workspace(tmp_path / 'workspace')
 store = Store(f'sqlite:///{tmp_path / "store.db"}')
 tools = ToolRegistry(workspace)
 return Orchestrator(store, workspace, ModelRouter('config/models.yaml'), Policy(), tools, Verifier(str(workspace.root)), model), store


def _job(task):
 return {'job_id': 'j-' + str(abs(hash(task)) % 10000), 'status': 'queued', 'task': task,
         'user_context': {'user_id': 'u', 'role': 'admin', 'tenant_id': 'default'},
         'attachments': [], 'routing': None, 'plan': [], 'tool_calls': [], 'observations': [],
         'verification': None, 'requires_human_approval': False, 'approval': None,
         'artifacts': [], 'final_answer': None, 'error': None}


def test_coding_task_writes_source_and_runs_it_in_the_sandbox(tmp_path):
 import asyncio
 from app.models.adapter import FakeModel
 orchestrator, store = _orchestrator(tmp_path, FakeModel())
 job = _job('write a python function to add two numbers')
 asyncio.run(orchestrator.run(job))
 done = store.get(job['job_id'])
 assert done['status'] == 'done'
 assert done['routing']['task_type'] == 'coding'
 runs = [o for o in done['observations'] if isinstance(o, dict) and o.get('tool') == 'run_python']
 assert runs and runs[0]['passed'] and runs[0]['exit_code'] == 0
 assert done['verification']['checks']['code_executed'] is True
 assert any(a['name'].endswith('.py') for a in done['artifacts'])


def test_document_task_gets_docx_and_pdf_with_a_real_summary(tmp_path):
 import asyncio
 from app.models.adapter import FakeModel
 orchestrator, store = _orchestrator(tmp_path, FakeModel())
 job = _job('summarize the quarterly maintenance report')
 asyncio.run(orchestrator.run(job))
 done = store.get(job['job_id'])
 assert done['status'] == 'done'
 assert done['routing']['task_type'] == 'document_workflow'
 assert any(a['name'].endswith('.docx') for a in done['artifacts'])
 assert any(a['name'].endswith('.pdf') for a in done['artifacts'])
 # final_answer must be a real summary of the model's response, not the old
 # hardcoded "Completed the requested workflow..." placeholder every job used to get.
 assert done['final_answer'] != 'Completed the requested workflow. The verified artifact is available through the artifact API.'
 assert 'document tools' in done['final_answer']


def test_ingest_cites_the_original_filename_not_the_upload_name(tmp_path):
 source = tmp_path / '0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9_inspection.md'
 source.write_text('Extinguisher FE-114 overdue for service.')
 rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
 rag.ingest_sync(source, {'tenant_id': 't1'})
 hits = rag.search_sync('extinguisher overdue')
 assert hits and hits[0]['source'] == 'inspection.md'
 rag.ingest_sync(source, {'tenant_id': 't2', 'source_name': 'Custom Name.md'})
 assert rag.search_sync('extinguisher overdue', metadata={'tenant_id': 't2'})[0]['source'] == 'Custom Name.md'


def test_require_postgres_guard_rejects_sqlite(monkeypatch):
 import importlib
 from app import config as config_module
 monkeypatch.setenv('REQUIRE_POSTGRES', 'true')
 monkeypatch.setenv('DATABASE_URL', 'sqlite:///./x.db')
 importlib.reload(config_module)
 import pytest
 with pytest.raises(RuntimeError, match='POSTGRES_REQUIRED_FOR_PRODUCTION'):
  config_module.validate_production_database_settings(config_module.settings)
 monkeypatch.delenv('REQUIRE_POSTGRES')
 monkeypatch.delenv('DATABASE_URL')
 importlib.reload(config_module)


def test_network_monitor_reports_airgap_status(monkeypatch):
 monkeypatch.setenv('OLLAMA_NO_CLOUD', 'true')
 monkeypatch.delenv('OLLAMA_CLOUD_ENDPOINT', raising=False)
 from app.network import NetworkMonitor
 status = NetworkMonitor().check()
 assert status['ok'] is True and status['ollama_cloud_disabled'] is True
 monkeypatch.setenv('OLLAMA_CLOUD_ENDPOINT', 'https://cloud.example')
 assert NetworkMonitor().check()['ok'] is False


def test_recent_jobs_are_tenant_and_owner_scoped(tmp_path):
 from app.storage.store import Store
 store = Store(f'sqlite:///{tmp_path / "store.db"}')
 store.save({'job_id': 'a', 'status': 'done', 'task': 'one', 'user_context': {'user_id': 'alice', 'tenant_id': 't1'}})
 store.save({'job_id': 'b', 'status': 'done', 'task': 'two', 'user_context': {'user_id': 'bob', 'tenant_id': 't1'}})
 store.save({'job_id': 'c', 'status': 'done', 'task': 'three', 'user_context': {'user_id': 'carol', 'tenant_id': 't2'}})
 alice = {'user_id': 'alice', 'tenant_id': 't1', 'role': 'lower'}
 admin = {'user_id': 'root', 'tenant_id': 't1', 'role': 'admin'}
 assert {j['job_id'] for j in store.recent_jobs(alice)} == {'a'}
 assert {j['job_id'] for j in store.recent_jobs(admin)} == {'a', 'b'}
 assert all('created_at' in j for j in store.recent_jobs(admin))


def test_ollama_adapter_timeout_scales_with_token_budget(monkeypatch):
 from app.models.adapter import OllamaAdapter
 monkeypatch.delenv('LLM_TIMEOUT_SECONDS', raising=False)
 monkeypatch.setenv('LLM_MAX_TOKENS', '100')
 short = OllamaAdapter('http://localhost:11434', 'x')
 assert short.default_timeout == 180  # floor, not shortened for a tiny budget
 monkeypatch.setenv('LLM_MAX_TOKENS', '3072')
 long = OllamaAdapter('http://localhost:11434', 'x')
 assert long.default_timeout == 3072 // 3 + 120  # scales up for a bigger budget
 monkeypatch.setenv('LLM_TIMEOUT_SECONDS', '999')
 override = OllamaAdapter('http://localhost:11434', 'x')
 assert override.default_timeout == 999  # explicit override wins either way
 monkeypatch.delenv('LLM_MAX_TOKENS', raising=False)
 monkeypatch.delenv('LLM_TIMEOUT_SECONDS', raising=False)


def test_ollama_adapter_reports_a_named_error_on_request_failure(monkeypatch):
 import asyncio
 import httpx
 from app.models.adapter import OllamaAdapter

 class _FailingClient:
  def __init__(self, *a, **k): pass
  async def __aenter__(self): return self
  async def __aexit__(self, *a): return False
  async def post(self, *a, **k): raise httpx.ReadTimeout('')  # stringifies to ''

 monkeypatch.setattr('httpx.AsyncClient', _FailingClient)
 adapter = OllamaAdapter('http://localhost:11434', 'qwen-test')
 try:
  asyncio.run(adapter.chat([{'role': 'user', 'content': 'hi'}]))
  assert False, 'expected a RuntimeError'
 except RuntimeError as exc:
  message = str(exc)
  assert 'qwen-test' in message and 'ReadTimeout' in message  # not just an empty string


def test_verification_failure_triggers_bounded_replanning(tmp_path):
 import asyncio

 class FlakyModel:
  model = 'flaky'
  def __init__(self):
   self.calls = 0
  async def chat(self, messages, tools=None, **kwargs):
   self.calls += 1
   if self.calls == 1:
    return {'content': '```python\nraise SystemExit(1)\n```'}
   return {'content': '```python\nprint("fixed")\n```'}

 model = FlakyModel()
 orchestrator, store = _orchestrator(tmp_path, model)
 job = _job('write a python script that prints a value')
 job['options'] = {'max_iterations': 3}
 asyncio.run(orchestrator.run(job))
 done = store.get(job['job_id'])
 assert model.calls == 2
 assert done['status'] == 'done'
 assert done['iteration'] == 2


def test_keep_alive_is_sent_on_every_local_inference_call(monkeypatch):
    """OLLAMA_KEEP_ALIVE has to reach the request body, not just the serve process.

    Ollama's own default is 5 minutes, so without this a 17 GB local model is
    evicted between prompts and every gap longer than that costs a full cold
    reload. The setting was previously read from .env and then never used.
    """
    import asyncio
    import httpx
    from app.models.adapter import OllamaAdapter
    from app.rag.service import RagService

    sent = []

    class _Response:
        status_code = 200
        text = ''

        def raise_for_status(self):
            return None

        def json(self):
            return {'message': {'content': 'ok'}, 'embedding': [0.0]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, **kwargs):
            sent.append(json)
            return _Response()

    monkeypatch.setattr(httpx, 'AsyncClient', _Client)

    adapter = OllamaAdapter('http://localhost:11434', 'qwen3.6:27b', '30m')
    asyncio.run(adapter.chat([{'role': 'user', 'content': 'hi'}]))
    assert sent[-1]['keep_alive'] == '30m'

    rag = RagService('sqlite:///:memory:', 'http://localhost:11434', 'bge-m3', 'qwen3-vl:8b', 1024, '30m')
    asyncio.run(rag._embed('hello'))
    assert sent[-1]['keep_alive'] == '30m', 'embedding calls must keep the embedder resident too'


def test_keep_alive_defaults_to_ollamas_own_default(monkeypatch):
    """Unset means 5m -- the same thing Ollama would do on its own, so wiring this
    through does not silently change memory behaviour for existing deployments."""
    from app.models.adapter import OllamaAdapter

    monkeypatch.delenv('OLLAMA_KEEP_ALIVE', raising=False)
    assert OllamaAdapter('http://localhost:11434', 'm').keep_alive == '5m'

    monkeypatch.setenv('OLLAMA_KEEP_ALIVE', '45m')
    assert OllamaAdapter('http://localhost:11434', 'm').keep_alive == '45m'


def test_an_attached_image_routes_to_the_vision_model(tmp_path):
    """Routing on task text alone sent pictures to a text-only model.

    A question about a picture usually names no visual thing -- "give the
    dimensions for this" classifies as `general` -- so the attachment, not the
    wording, has to decide that vision is required. The task type still comes
    from the text, so the deliverable is unchanged.
    """
    router = ModelRouter('config/models.yaml')
    image = [{'file_id': 'f1', 'name': 'images.jpeg', 'mime_type': 'image/jpeg'}]

    blind = router.route('give the dimensions for this')
    assert blind['capability'] == 'reasoning' and not blind['requires_vision']

    seeing = router.route('give the dimensions for this', image)
    assert seeing['requires_vision'] and seeing['capability'] == 'vision'
    assert seeing['model_name'] == 'qwen3-vl:8b'
    assert seeing['task_type'] == 'general', 'the text still decides the deliverable'

    # A deliverable-producing task keeps its plan but gains sight of the drawing.
    deck = router.route('save this as pptx', image)
    assert deck['task_type'] == 'presentation' and deck['capability'] == 'vision'

    # Non-image attachments are already text by the time they reach the model.
    assert not router.route('summarize this', [{'name': 'report.pdf', 'mime_type': 'application/pdf'}])['requires_vision']


def test_attached_images_are_sent_to_the_model(tmp_path):
    """The image bytes must reach the model, not just its OCR line.

    Before this, an attachment only ever contributed a RAG file_id filter, so
    the model answered about a drawing from a garbled transcription of it.
    """
    import asyncio
    import io
    from PIL import Image

    class Recorder:
        model = 'recorder'
        url = 'fake://local'

        def __init__(self):
            self.messages = None

        async def chat(self, messages, tools=None, **kwargs):
            self.messages = messages
            return {'content': 'The title block reads SHAFT ASSEMBLY, 120 mm overall.'}

    model = Recorder()
    orchestrator, store = _orchestrator(tmp_path, model)
    job = _job('give the dimensions for this')

    root = orchestrator.workspace.create(job['job_id'])
    buffer = io.BytesIO()
    Image.new('RGB', (48, 48), 'white').save(buffer, format='PNG')
    (root / 'input' / 'drawing.png').write_bytes(buffer.getvalue())
    job['attachments'] = [{'file_id': 'f1', 'name': 'drawing.png',
                           'path': 'input/drawing.png', 'mime_type': 'image/png'}]

    asyncio.run(orchestrator.run(job))

    done = store.get(job['job_id'])
    assert done['status'] == 'done'
    assert done['routing']['requires_vision'] and done['routing']['capability'] == 'vision'

    user = [m for m in model.messages if m['role'] == 'user'][-1]
    assert user.get('images'), 'the image never reached the model'
    assert base64.b64decode(user['images'][0])[:4] == b'\x89PNG'

    system = model.messages[0]['content']
    assert 'drawing.png' in system and 'you can see them' in system
    assert 'outrank any OCR text' in system, 'otherwise the OCR line wins over the image'

    assert any(e['type'] == 'images_attached' for e in store.events(job['job_id']))


def test_a_missing_attachment_does_not_take_the_job_down(tmp_path):
    """A path that cannot be read is reported, not raised mid-inference."""
    import asyncio
    from app.models.adapter import FakeModel

    orchestrator, store = _orchestrator(tmp_path, FakeModel())
    job = _job('give the dimensions for this')
    orchestrator.workspace.create(job['job_id'])
    job['attachments'] = [{'file_id': 'f1', 'name': 'gone.png',
                           'path': 'input/gone.png', 'mime_type': 'image/png'}]

    asyncio.run(orchestrator.run(job))

    done = store.get(job['job_id'])
    assert done['status'] == 'done'
    assert any(e['type'] == 'attachment_unreadable' for e in store.events(job['job_id']))


def test_unusable_tesseract_output_falls_back_to_the_vision_model(tmp_path):
    """Tesseract fails silently on drawings: it returns noise, not an error.

    The noise below is the real output that was indexed for `illus056.png`, and
    it became that document's entire searchable content.
    """
    import asyncio

    noise = 'Y i , 7 "Y0DO us snd *juoaf inding un'
    assert RagService._ocr_is_unusable(noise)
    assert RagService._ocr_is_unusable('$ Mechanical Component $'), 'too little to be evidence'
    assert not RagService._ocr_is_unusable(
        'TITLE BLOCK SHAFT ASSEMBLY DRAWING NO 4471 SCALE 1:2 MATERIAL EN8 STEEL')

    from PIL import Image
    source = tmp_path / 'illus056.png'
    Image.new('RGB', (32, 32), 'white').save(source)

    rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
    rag._ocr = staticmethod(lambda path: noise)
    transcript = 'SHAFT ASSEMBLY. Overall length 120 mm, bore 24 mm H7.'

    async def _vision(path):
        return transcript

    rag._vision_extract = _vision

    asyncio.run(rag.ingest(source))
    hits = asyncio.run(rag.search('bore'))
    assert hits and 'bore 24 mm' in hits[0]['content'], 'the noise was indexed instead'


def test_leaked_reasoning_is_stripped_from_the_answer():
    """Qwen3-VL ignores `think: false` and emits the tags inline instead.

    The raw chain of thought then arrives as `content` and was shown to the user
    as the answer -- including a repetition loop it never escaped.
    """
    from app.models.adapter import _strip_reasoning

    assert _strip_reasoning('<think>weighing it up</think>\n\nOverall length 1\' 9 7/8".') == 'Overall length 1\' 9 7/8".'
    assert _strip_reasoning('plain answer') == 'plain answer'
    # Budget exhausted mid-thought: there is no answer to keep, so returning an
    # empty string would lose the only thing the model actually read off the page.
    assert _strip_reasoning('<think>never finished') == 'never finished'


def test_an_unreadable_image_indexes_a_marker_not_the_ocr_noise(tmp_path):
    """When OCR is noise and vision is unavailable, index neither.

    The noise was previously stored as the document's whole content, so retrieval
    handed it back as evidence and the model reported the file as unreadable
    garbage instead of answering from the attached image.
    """
    import asyncio
    from PIL import Image

    source = tmp_path / 'scan.png'
    Image.new('RGB', (32, 32), 'white').save(source)

    rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
    rag._ocr = staticmethod(lambda path: 'Y i , 7 "Y0DO us snd *juoaf Uo Le 9 S80G7 Bs F 29')

    async def _unavailable(path):
        return '[OCR unavailable: install Tesseract or configure Ollama vision: nope]'

    rag._vision_extract = _unavailable

    asyncio.run(rag.ingest(source))
    hits = asyncio.run(rag.search('scan'))
    assert hits, 'the file should still be indexed and findable by name'
    content = hits[0]['content']
    assert 'Y0DO' not in content, 'OCR noise was indexed as the document content'
    assert 'no machine-readable text' in content and 'attached to the task' in content


def test_vision_ocr_budget_is_bounded_and_configurable(monkeypatch):
    """Ingest is synchronous, so the vision pass cannot wait indefinitely.

    A dense drawing measured at 393s here, well past any sane upload wait.
    """
    monkeypatch.delenv('OCR_VISION_TIMEOUT_SECONDS', raising=False)
    assert RagService('sqlite:///:memory:').vision_timeout == 180

    monkeypatch.setenv('OCR_VISION_TIMEOUT_SECONDS', '420')
    rag = RagService('sqlite:///:memory:')
    assert rag.vision_timeout == 420
    # Capped at 1024 the reasoning consumed the whole allowance and the call came
    # back with empty content, so the budget has to leave room past the thinking.
    assert rag._vision_options['options']['num_predict'] >= 2048


def test_small_images_are_enlarged_before_they_reach_the_vision_model():
    """A vision model tokenises by area, so a small image is read coarsely.

    Measured on a 335x597 drawing: at native size the model reported "two holes
    of diameter 8.15" for a `2-R15` fillet callout, inventing features that are
    not on the page. Past this floor it fabricated nothing.
    """
    import io
    from PIL import Image
    from app.orchestrator.service import _fit_for_vision, _MIN_IMAGE_SHORT_EDGE

    def encode(width, height):
        buffer = io.BytesIO()
        Image.new('RGB', (width, height), 'white').save(buffer, format='PNG')
        return buffer.getvalue()

    # The floor is on the short edge. Fitting the long edge instead leaves a portrait
    # page only 786 wide, and at that width the model still misread Ø192 as "81.92".
    fitted, note = _fit_for_vision(encode(335, 597))
    enlarged = Image.open(io.BytesIO(fitted))
    assert min(enlarged.size) == _MIN_IMAGE_SHORT_EDGE
    assert enlarged.size == (1200, 2139), 'aspect ratio must be preserved'
    assert note and 'upscaled' in note

    # An icon must not be blown up into a megapixel of pure interpolation.
    fitted, _ = _fit_for_vision(encode(64, 64))
    assert Image.open(io.BytesIO(fitted)).size == (256, 256)

    # A narrow short edge is not on its own a reason to enlarge: a 1600x900 screenshot
    # carries 1.4 MP and reads fine, so enlarging it would only cost tokens.
    original = encode(1600, 900)
    fitted, note = _fit_for_vision(original)
    assert fitted == original and note is None

    # Anything already in band is passed through byte-identical.
    original = encode(1500, 1300)
    fitted, note = _fit_for_vision(original)
    assert fitted == original and note is None


def test_oversized_images_are_still_shrunk():
    """The ceiling still applies: a 50 MB upload would otherwise blow the context."""
    import io
    from PIL import Image
    from app.orchestrator.service import _fit_for_vision, _MAX_IMAGE_EDGE, _MAX_IMAGE_BYTES

    noise = Image.effect_noise((3000, 2400), 64).convert('RGB')
    buffer = io.BytesIO()
    noise.save(buffer, format='PNG')
    assert len(buffer.getvalue()) > _MAX_IMAGE_BYTES, 'fixture must exceed the ceiling'

    fitted, note = _fit_for_vision(buffer.getvalue())
    assert max(Image.open(io.BytesIO(fitted)).size) == _MAX_IMAGE_EDGE
    assert note and 'downscaled' in note


def test_the_request_timeout_follows_a_per_call_token_budget():
    """A caller raising num_predict must get a deadline that fits it.

    The vision path raises the budget per call; with the adapter's construction-time
    timeout that generation would be cut off partway through.
    """
    from app.models.adapter import OllamaAdapter

    adapter = OllamaAdapter('http://localhost:11434', 'qwen3-vl:8b')
    assert adapter.default_timeout == 632, 'baseline from LLM_MAX_TOKENS=1536'
    # 8192 // 3 + 120 = 2850
    assert max(adapter.default_timeout, 8192 // 3 + 120) == 2850


def test_conversation_history_comes_back_in_order(tmp_path):
    """Message ids are random UUIDs, so ordering by id ordered a conversation
    arbitrarily: turns rendered with the prompt below its own answer, and LIMIT
    returned an arbitrary subset instead of the most recent messages. The
    orchestrator passes this same call to the model as history, so the model was
    reading scrambled context as well."""
    import json
    import uuid
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    from app.storage.store import Store

    store = Store(f'sqlite:///{tmp_path / "store.db"}')
    conversation = str(uuid.uuid4())
    store.create_conversation(conversation, 't', 'u', 'Ordering')

    # Written with ids deliberately unsorted against time, which is what real UUIDs
    # are: the previous ORDER BY id returned exactly this insertion-independent mess.
    start = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    expected = []
    with store.engine.begin() as db:
        for index in range(12):
            role = 'user' if index % 2 == 0 else 'assistant'
            content = f'{role}-{index}'
            expected.append(content)
            db.execute(
                text('INSERT INTO messages(id,conversation_id,role,content,citations,created_at) '
                     'VALUES(:id,:conversation,:role,:content,:citations,:created)'),
                {'id': str(uuid.uuid4()), 'conversation': conversation, 'role': role,
                 'content': content, 'citations': json.dumps([]),
                 'created': (start + timedelta(minutes=index)).isoformat()},
            )

    assert [m['content'] for m in store.messages(conversation, 50)] == expected

    # A limit must take the most RECENT messages, still in order -- not whichever
    # ids happened to sort highest.
    assert [m['content'] for m in store.messages(conversation, 4)] == expected[-4:]

    # And a turn must never render with its answer above its prompt.
    assert [m['role'] for m in store.messages(conversation, 50)] == ['user', 'assistant'] * 6


def test_a_truncated_code_fence_is_still_recovered(tmp_path):
    """A response cut off by the token budget ends inside its own fence.

    The block regex needs a closing ```, so it matched nothing and the code was
    silently discarded: the plan fell back to writing a .md file, `code_executed`
    failed, and the job burned every iteration re-planning into the same wall.
    Recovering the tail turns that into code that visibly fails to run.
    """
    from app.models.adapter import FakeModel
    orchestrator, _ = _orchestrator(tmp_path, FakeModel())

    complete = _job('x')
    complete['model_response'] = {'content': 'Here you go.\n\n```python\nprint(1)\n```\n'}
    assert orchestrator._code_blocks(complete) == [('python', 'print(1)')]
    assert not complete.get('_truncated_code')

    truncated = _job('y')
    truncated['model_response'] = {'content': 'Here you go.\n\n```python\ndef f():\n    return 1 +'}
    blocks = orchestrator._code_blocks(truncated)
    assert blocks == [('python', 'def f():\n    return 1 +')]
    assert truncated['_truncated_code'] is True

    # A complete block followed by a truncated one keeps both.
    both = _job('z')
    both['model_response'] = {'content': '```python\nprint(1)\n```\ntext\n```python\nprint(2'}
    assert orchestrator._code_blocks(both) == [('python', 'print(1)'), ('python', 'print(2')]

    # Prose with no fence at all is still no code.
    plain = _job('w')
    plain['model_response'] = {'content': 'No code here at all.'}
    assert orchestrator._code_blocks(plain) == []


def test_a_coding_task_gets_a_budget_that_fits_a_source_file():
    """1536 tokens truncated a "function plus unit test" answer mid-expression."""
    from app.orchestrator.service import _TASK_CHAT_OPTIONS

    assert _TASK_CHAT_OPTIONS['coding']['num_predict'] >= 4096
    assert 'general' not in _TASK_CHAT_OPTIONS, 'a chat answer keeps the default budget'


def _scanned_pdf(pages=1):
    """A PDF whose pages are pictures -- no text layer, as a scanner produces."""
    import pymupdf

    rendered = pymupdf.open()
    source = pymupdf.open()
    sheet = source.new_page(width=595, height=842)
    sheet.insert_text((60, 120), 'DRAWING 4471  SCALE 1:2', fontsize=22)
    pixmap = sheet.get_pixmap(dpi=120)
    source.close()
    for _ in range(pages):
        page = rendered.new_page(width=595, height=842)
        page.insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pixmap)
    data = rendered.tobytes()
    rendered.close()
    return data


def test_a_scanned_pdf_reaches_the_vision_model(tmp_path):
    """A drawing delivered as a PDF is how P&IDs and SOPs actually arrive.

    is_image_attachment matches only image MIME types, so such a file was answered
    from whatever ingest-time OCR managed and its pages never reached a model that
    could see them.
    """
    import asyncio
    from app.models.adapter import FakeModel

    class Recorder(FakeModel):
        messages = None

        async def chat(self, msgs, tools=None, **kwargs):
            Recorder.messages = msgs
            return {'content': 'Read it.'}

    orchestrator, store = _orchestrator(tmp_path, Recorder())
    job = _job('what does this drawing show')
    root = orchestrator.workspace.create(job['job_id'])
    (root / 'input' / 'scan.pdf').write_bytes(_scanned_pdf())
    job['attachments'] = [{'file_id': 'f1', 'name': 'scan.pdf',
                           'path': 'input/scan.pdf', 'mime_type': 'application/pdf'}]

    asyncio.run(orchestrator.run(job))

    done = store.get(job['job_id'])
    assert done['routing']['requires_vision'], 'a scanned PDF must route to a vision model'
    user = [m for m in Recorder.messages if m['role'] == 'user'][-1]
    assert user.get('images') and len(user['images']) == 1
    assert base64.b64decode(user['images'][0])[:4] == b'\x89PNG'

    attached = [e for e in store.events(job['job_id']) if e['type'] == 'images_attached']
    assert attached and attached[0]['data']['names'] == ['scan.pdf p.1']


def test_a_text_pdf_is_not_rasterised(tmp_path):
    """A PDF with a real text layer is already readable and must not cost ~2.8k
    tokens a page to look at."""
    import pymupdf
    from app.orchestrator.service import _pdf_page_images

    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(60, 60, 540, 700), 'Inspection report. ' * 60, fontsize=11)
    data = document.tobytes()
    document.close()

    assert _pdf_page_images(data, 6) == ([], 0)


def test_attached_images_are_capped_to_fit_the_context_window(tmp_path):
    """Measured at ~2,818 tokens per enlarged page, eleven images fill a 32K window.

    Without a cap a long scan produced a prompt the model could not hold, silently.
    """
    import asyncio
    from app.models.adapter import FakeModel
    from app.orchestrator.service import _MAX_ATTACHED_IMAGES

    orchestrator, store = _orchestrator(tmp_path, FakeModel())
    job = _job('read this')
    root = orchestrator.workspace.create(job['job_id'])
    (root / 'input' / 'long.pdf').write_bytes(_scanned_pdf(pages=_MAX_ATTACHED_IMAGES + 3))
    job['attachments'] = [{'file_id': 'f1', 'name': 'long.pdf',
                           'path': 'input/long.pdf', 'mime_type': 'application/pdf'}]

    images, omitted = orchestrator._attached_images(job)
    assert len(images) == _MAX_ATTACHED_IMAGES
    assert omitted == 3

    # The model is told what it is not seeing, rather than answering as though the
    # missing pages did not exist.
    prompt = orchestrator._system_prompt('general', images, omitted)
    assert 'could not be included' in prompt


def test_the_pdf_vision_pass_is_bounded_by_pages_and_a_total_budget(tmp_path, monkeypatch):
    """httpx times out per request, so a per-page bound multiplied by the page count:
    a twenty-page scan could hold an upload open for an hour."""
    import asyncio
    import pymupdf
    from app.rag.service import RagService

    document = pymupdf.open()
    source = pymupdf.open()
    sheet = source.new_page()
    sheet.insert_text((60, 120), 'SCANNED', fontsize=28)
    pixmap = sheet.get_pixmap(dpi=90)
    source.close()
    for _ in range(12):
        page = document.new_page()
        page.insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pixmap)
    scan = tmp_path / 'long_scan.pdf'
    document.save(scan)
    document.close()

    monkeypatch.setenv('OCR_MAX_VISION_PAGES', '3')
    rag = RagService(f'sqlite:///{tmp_path / "r.db"}')
    assert rag.max_vision_pages == 3

    # Every page is a picture, so all twelve are candidates.
    assert rag._pdf_pages_without_text(scan)[1] == 12
    assert len(rag._pdf_pages_without_text(scan)[0]) == 12

    calls = []

    async def _chat(client, payload, timeout=None):
        calls.append(timeout)
        return 'PAGE TEXT that is long enough to read as real words here'

    rag._vision_chat = _chat
    out = asyncio.run(rag._vision_extract_pdf(scan))

    assert len(calls) == 3, 'the page cap must stop the pass'
    assert 'Pages 4-12 were not transcribed' in out, 'and say which pages were skipped'
    assert all(t is not None for t in calls), 'each request bounded by the remaining budget'


def test_a_scanned_pdf_is_judged_on_its_text_layer_not_its_ocr_noise(tmp_path):
    """156 characters of Tesseract noise passed the old "under 24 chars" test, so a
    scanned drawing was indexed as gibberish and the vision model never ran."""
    import asyncio
    import pymupdf
    from app.rag.service import RagService

    source = pymupdf.open()
    sheet = source.new_page()
    sheet.insert_text((60, 120), 'DRAWING 4471', fontsize=28)
    pixmap = sheet.get_pixmap(dpi=110)
    source.close()
    document = pymupdf.open()
    document.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pixmap)
    scan = tmp_path / 'scan.pdf'
    document.save(scan)
    document.close()

    rag = RagService(f'sqlite:///{tmp_path / "r.db"}')
    # The real Tesseract output for this drawing, verbatim.
    rag._ocr_pdf = lambda path: '[Page 1]\nfone Ge - 3 Ss 6jf ut "Y9DQ Us AUST] AL SRUOAF UG 9 sj22/onf 2 ssogr'

    async def _vision(path, only_pages=None):
        assert only_pages == [1], 'only the pages that are pictures'
        return '[Page 1]\nDRAWING 4471 SCALE 1:2 MATERIAL EN8 STEEL OVERALL LENGTH 120 MM'

    rag._vision_extract_pdf = _vision
    asyncio.run(rag.ingest(scan))

    hits = asyncio.run(rag.search('DRAWING'))
    assert hits, 'the scan should be findable'
    assert 'DRAWING 4471' in hits[0]['content']
    assert 'Y9DQ' not in hits[0]['content'], 'OCR noise must not be what gets indexed'


def test_a_text_layer_pdf_never_triggers_a_vision_pass(tmp_path):
    """A readable PDF costs nothing to index and must not pay ~1-2 minutes a page."""
    import asyncio
    import pymupdf
    from app.rag.service import RagService

    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(60, 60, 540, 760), 'Pump P-101 inspection interval. ' * 40, fontsize=11)
    readable = tmp_path / 'report.pdf'
    document.save(readable)
    document.close()

    rag = RagService(f'sqlite:///{tmp_path / "r.db"}')
    assert rag._pdf_pages_without_text(readable)[0] == []

    async def _never(path, only_pages=None):
        raise AssertionError('a text-layer PDF must not be sent to the vision model')

    rag._vision_extract_pdf = _never
    asyncio.run(rag.ingest(readable))
    assert asyncio.run(rag.search('inspection interval'))


def test_indexed_ocr_does_not_contain_the_models_own_reasoning(tmp_path):
    """Qwen3-VL ignores `think: false` and writes <think> straight into content.

    Indexing a transcription wrapped in the model's deliberation pollutes every later
    search against that document.
    """
    import asyncio
    from app.rag.service import RagService

    class _Response:
        status_code = 200
        text = ''

        def raise_for_status(self):
            return None

        def json(self):
            # The answer has to clear the usability floor, as a real transcription does.
            return {'message': {'content': '<think>Let me look at the title block.</think>\n\n'
                                           'DRAWING 4471 SCALE 1:2 MATERIAL EN8 STEEL OVERALL LENGTH 120 MM'}}

    class _Client:
        async def post(self, url, json=None, **kwargs):
            return _Response()

    rag = RagService(f'sqlite:///{tmp_path / "r.db"}')
    out = asyncio.run(rag._vision_chat(_Client(), {}))
    assert out == 'DRAWING 4471 SCALE 1:2 MATERIAL EN8 STEEL OVERALL LENGTH 120 MM'
    assert 'Let me look' not in out, 'the reasoning goes when there is a real answer'


def test_a_transcription_buried_in_reasoning_is_kept_not_discarded(tmp_path):
    """On a dense page this model often spends the whole budget reasoning and writes no
    answer -- measured at 8,491 characters of thinking and zero of content. The text it
    read off the page is in that reasoning, so stripping it indexes nothing."""
    import asyncio
    from app.rag.service import RagService

    buried = ('<think>Let me read the title block. It says DRAWING 4471, scale 1:2, '
              'material EN8 steel, and the collars at A are 3/8 by 1/2 inches.')

    class _Response:
        status_code = 200
        text = ''

        def raise_for_status(self):
            return None

        def json(self):
            return {'message': {'content': '', 'thinking': buried}}

    class _Client:
        async def post(self, url, json=None, **kwargs):
            return _Response()

    rag = RagService(f'sqlite:///{tmp_path / "r.db"}')
    out = asyncio.run(rag._vision_chat(_Client(), {}))
    assert 'DRAWING 4471' in out and 'collars at A are 3/8' in out
    assert '<think>' not in out, 'the markers go even when the text stays'


def test_json_columns_decode_from_either_backend():
    """psycopg returns JSONB already decoded; SQLite returns the TEXT it stored.

    Calling json.loads on the decoded dict raised "the JSON object must be str, bytes
    or bytearray, not dict" -- visible only on PostgreSQL, and only via search_sync,
    because the async path returns from the pgvector branch before reaching it.
    """
    from app.rag.service import _decode_json

    assert _decode_json({'tenant_id': 'acme'}, {}) == {'tenant_id': 'acme'}   # postgres
    assert _decode_json('{"tenant_id": "acme"}', {}) == {'tenant_id': 'acme'}  # sqlite
    assert _decode_json([0.1, 0.2], []) == [0.1, 0.2]
    assert _decode_json('[0.1, 0.2]', []) == [0.1, 0.2]
    assert _decode_json(None, {}) == {}
    assert _decode_json('', {}) == {}
    assert _decode_json('   ', []) == []


def test_boolean_columns_work_on_both_backends(tmp_path):
    """SQLite stores booleans as integers, so `archived = 0` worked there.

    PostgreSQL has no boolean = integer operator and rejects the comparison, which
    took out the conversation list (GET /conversations returned 500, so no session
    ever appeared in the sidebar), file-share access, share revocation, and recording
    an approval. TRUE/FALSE are keywords in both backends.
    """
    import uuid
    from app.storage.store import Store

    store = Store(f'sqlite:///{tmp_path / "s.db"}')
    identity = {'tenant_id': 't', 'user_id': 'u', 'role': 'admin'}

    first = str(uuid.uuid4())
    store.create_conversation(first, 't', 'u', 'Older session')
    second = str(uuid.uuid4())
    store.create_conversation(second, 't', 'u', 'Newer session')

    listed = store.conversations(identity)
    assert [c['title'] for c in listed] == ['Newer session', 'Older session'], 'newest first'

    # A share is visible until revoked, then it is not.
    store.register_file('f1', 'u', 't', 'doc.txt', str(tmp_path / 'doc.txt'), {})
    share = store.share_file('f1', identity, 'bob')
    bob = {'tenant_id': 't', 'user_id': 'bob', 'role': 'lower'}
    assert 'f1' in store.accessible_file_ids(bob)
    store.revoke_share(share['id'] if isinstance(share, dict) else share, identity)
    assert 'f1' not in store.accessible_file_ids(bob)

    # And an approval records without a boolean/integer mismatch.
    store.approval('job-1', True, 'reviewer-1')


def test_timestamps_leave_the_store_as_iso_strings(tmp_path):
    """psycopg returns TIMESTAMPTZ as a datetime; SQLite returns the ISO text stored.

    The SSE endpoint serialises events with a plain json.dumps, which cannot encode a
    datetime -- so on PostgreSQL the live event stream died on its first event and the
    progress pane received nothing at all.
    """
    import json
    import uuid
    from datetime import datetime, timezone
    from app.storage.store import Store

    store = Store(f'sqlite:///{tmp_path / "s.db"}')

    # The normaliser is what the backends have in common; check it directly.
    stamp = datetime(2026, 9, 22, 10, 30, tzinfo=timezone.utc)
    assert Store._iso(stamp) == stamp.isoformat()
    assert Store._iso('2026-09-22T10:30:00+00:00') == '2026-09-22T10:30:00+00:00'
    assert Store._iso(None) is None
    assert Store._row({'a': stamp, 'b': 'x'}) == {'a': stamp.isoformat(), 'b': 'x'}
    assert Store._row({'a': 1}, b=2) == {'a': 1, 'b': 2}

    job = {'job_id': str(uuid.uuid4()), 'status': 'queued', 'task': 't'}
    store.save(job)
    store.event(job['job_id'], 'job_created', {'status': 'queued'})

    events = store.events(job['job_id'])
    assert events and isinstance(events[0]['timestamp'], str)
    # The SSE endpoint does exactly this, and it must not raise.
    json.dumps(events[0])

    conversation = str(uuid.uuid4())
    store.create_conversation(conversation, 't', 'u', 'Timestamps')
    store.add_message(str(uuid.uuid4()), conversation, 'user', 'hello', [])
    json.dumps(store.messages(conversation))
    json.dumps(store.conversations({'tenant_id': 't', 'user_id': 'u', 'role': 'admin'}))


def test_a_short_but_correct_vision_reading_is_kept(tmp_path):
    """A nameplate, a valve tag or a stamped part number is a few characters.

    _ocr_is_unusable exists to catch Tesseract noise and both of its tests reject
    such a reading -- "SCAN INGEST744DC0" is 16 characters against a 24-character
    floor, and one alphabetic token of two against a word-ratio floor. Applying it
    to vision output indexed "no machine-readable text" for images the model had
    read perfectly well.
    """
    import asyncio
    from PIL import Image
    from app.rag.service import RagService

    assert RagService._ocr_is_unusable('SCAN INGEST744DC0'), 'the noise heuristic does reject it'
    assert not RagService._vision_failed('SCAN INGEST744DC0'), 'but it is a real reading'
    assert not RagService._vision_failed('P-101')
    assert RagService._vision_failed('')
    assert RagService._vision_failed('   ')
    assert RagService._vision_failed('[OCR unavailable: no tesseract]')

    source = tmp_path / 'nameplate.png'
    Image.new('RGB', (400, 120), 'white').save(source)

    rag = RagService(f'sqlite:///{tmp_path / "r.db"}')
    rag._ocr = lambda path: '[OCR unavailable: tesseract missing]'

    async def _vision(path):
        return 'PUMP P-101'

    rag._vision_extract = _vision
    asyncio.run(rag.ingest(source))

    hits = asyncio.run(rag.search('P-101'))
    assert hits, 'the nameplate should be findable'
    assert 'PUMP P-101' in hits[0]['content']
    assert 'no machine-readable text' not in hits[0]['content']

def test_rag_indexes_source_files_keeping_lines_and_indentation(tmp_path):
	# The prose chunker collapses all whitespace, which for Python discards the
	# indentation that carries the meaning. Source has to survive as source.
	source = tmp_path / 'access.py'
	source.write_text("def resolve(role, scope):\n    if scope not in options:\n        raise HTTPException(422)\n    return options[scope]\n")
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	assert 'resolve' in rag.extract(source)
	import asyncio
	assert asyncio.run(rag.ingest(source))['chunks'] == 1
	hits = asyncio.run(rag.search('resolve scope'))
	assert hits[0]['source'] == 'access.py'
	assert '\n    if scope not in options:' in hits[0]['content']

def test_prose_documents_keep_the_original_chunking(tmp_path):
	# Same bytes, non-code extension: the existing behaviour must not shift,
	# because every retrieval measurement was taken against it.
	text = "def resolve(role, scope):\n    return options[scope]\n"
	assert '\n' not in RagService._chunks_for(Path('notes.txt'), text)[0]
	assert '\n' in RagService._chunks_for(Path('access.py'), text)[0]

def test_minified_source_falls_back_to_character_chunks():
	# One line of megabytes has no structure to preserve, and line-based chunking
	# would emit a single chunk larger than the embedding model accepts.
	chunks = RagService._chunks_for(Path('bundle.min.js'), 'var a=1;' * 900)
	assert len(chunks) > 1
	assert max(len(chunk) for chunk in chunks) <= 1200

def test_long_source_file_chunks_overlap(tmp_path):
	chunks = RagService._chunks_for(Path('big.py'), '\n'.join(f'line_{i} = {i}' for i in range(200)))
	assert len(chunks) > 1
	# Consecutive chunks share trailing context, so a definition split across a
	# boundary is still retrievable from one side of it.
	assert chunks[1].splitlines()[0] in chunks[0]

def test_unsupported_extension_is_still_rejected(tmp_path):
	import pytest
	source = tmp_path / 'archive.zip'
	source.write_bytes(b'PK\x03\x04')
	with pytest.raises(ValueError, match='UNSUPPORTED_DOCUMENT_TYPE'):
		RagService(f'sqlite:///{tmp_path / "rag.db"}').extract(source)
def test_redact_pii_on_docx_writes_a_real_docx_without_the_pii(tmp_path):
	# Reading a .docx as text gets zip bytes: the regexes match nothing and the
	# file written back is a corrupt archive still carrying the personal data.
	from docx import Document
	from app.tools.registry import ToolRegistry
	from app.workspace.manager import Workspace
	workspace = Workspace(str(tmp_path))
	source = workspace.safe('job1', 'input/addendum.docx', True)
	document = Document()
	document.add_paragraph('Notices are served on Meera Raghavan at meera.raghavan@kaveripumps.example')
	document.add_paragraph('or on +91 98200 41127 during working hours.')
	table = document.add_table(rows=1, cols=1)
	table.rows[0].cells[0].text = 'Escalation: arun.deshpande@ktps.example'
	document.save(str(source))

	result = ToolRegistry(workspace).execute('job1', 'redact_pii', {'path': 'input/addendum.docx'})
	assert result['redactions'] == 3

	out = workspace.root / 'job1' / result['path']
	assert out.suffix == '.docx'
	written = Document(str(out))
	text = '\n'.join(p.text for p in written.paragraphs)
	text += '\n' + '\n'.join(c.text for t in written.tables for r in t.rows for c in r.cells)
	assert 'meera.raghavan@kaveripumps.example' not in text
	assert 'arun.deshpande@ktps.example' not in text
	assert '98200 41127' not in text
	assert '[REDACTED_EMAIL]' in text and '[REDACTED_PHONE]' in text
	assert 'Meera Raghavan' in text  # names are not in the patterns; only contact details go

def test_redact_pii_on_text_is_unchanged(tmp_path):
	from app.tools.registry import ToolRegistry
	from app.workspace.manager import Workspace
	workspace = Workspace(str(tmp_path))
	source = workspace.safe('job2', 'input/notes.txt', True)
	source.write_text('reach me at ops@example.com or +91 98200 41127\n')
	result = ToolRegistry(workspace).execute('job2', 'redact_pii', {'path': 'input/notes.txt'})
	assert result['redactions'] == 2
	body = (workspace.root / 'job2' / result['path']).read_text()
	assert '[REDACTED_EMAIL]' in body and '[REDACTED_PHONE]' in body
	assert 'ops@example.com' not in body

def test_redact_pii_catches_contacts_split_across_runs(tmp_path):
	# Word splits a paragraph at every formatting change, so an address is often
	# spread over several runs and matches nothing when examined run by run.
	from docx import Document
	from app.tools.registry import ToolRegistry
	from app.workspace.manager import Workspace
	workspace = Workspace(str(tmp_path))
	source = workspace.safe('job3', 'input/split.docx', True)
	document = Document()
	paragraph = document.add_paragraph()
	paragraph.add_run('write to meera.')
	paragraph.add_run('raghavan@kaveri')
	paragraph.add_run('pumps.example today')
	document.save(str(source))

	result = ToolRegistry(workspace).execute('job3', 'redact_pii', {'path': 'input/split.docx'})
	assert result['redactions'] == 1
	out = workspace.root / 'job3' / result['path']
	text = '\n'.join(p.text for p in Document(str(out)).paragraphs)
	assert 'meera.raghavan@kaveripumps.example' not in text
	assert '[REDACTED_EMAIL]' in text

def test_equipment_tag_extractor_finds_real_tags():
	from app.rag.service import extract_equipment_tags
	assert extract_equipment_tags('Boiler feed pump P-204B and standby P-204A.') == ['P-204A', 'P-204B']
	assert extract_equipment_tags('HV-1127 CL300 WCB') == ['HV-1127']
	assert extract_equipment_tags('Report number: INS-2026-0912') == ['INS-2026-0912']
	assert extract_equipment_tags('note ECN-4471 against TK-07 and HX-3B') == ['ECN-4471', 'HX-3B', 'TK-07']
	# Without a two-segment prefix this matches at BFP-07, an identifier that
	# appears nowhere in the document it was taken from.
	assert extract_equipment_tags('procedure SOP-BFP-07 applies') == ['SOP-BFP-07']

def test_equipment_tag_extractor_rejects_lookalikes():
	# A false tag is worse than a missed one: it pollutes the filter for every
	# other document, silently.
	from app.rag.service import extract_equipment_tags
	assert extract_equipment_tags('Date of survey: 2026-09-12') == []          # date
	assert extract_equipment_tags('call +91 98200 41127 today') == []          # phone
	assert extract_equipment_tags('damages of INR 18,00,000 apply') == []      # currency
	assert extract_equipment_tags('see section 7.1 on page 3') == []           # section/page
	assert extract_equipment_tags('a follow-up-2 and a well-2 reading') == []  # lowercase
	assert extract_equipment_tags('effective SEP-2026 and DEC-2025') == []     # month
	assert extract_equipment_tags('the COVID-19 protocol') == []               # long prefix
	assert extract_equipment_tags('disc pack 41-7720 superseded') == []        # no prefix

def test_equipment_tags_are_capped_per_chunk():
	from app.rag.service import extract_equipment_tags
	assert len(extract_equipment_tags(' '.join(f'P-{i}' for i in range(200)))) == 32

def test_ingested_chunks_carry_their_own_tags(tmp_path):
	import asyncio
	source = tmp_path / 'survey.txt'
	source.write_text('Pump P-204B exceeded alarm. Valve HV-1127 was isolated.\n')
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	asyncio.run(rag.ingest(source, {'tenant_id': 't1', 'file_id': 'f1'}))
	hits = asyncio.run(rag.search('pump'))
	tags = hits[0]['metadata']['equipment_tags']
	assert 'P-204B' in tags and 'HV-1127' in tags
	# Adding a key must not disturb what was already filtered on.
	assert hits[0]['metadata']['file_id'] == 'f1'
	assert hits[0]['metadata']['tenant_id'] == 't1'

def test_tag_filter_selects_only_matching_chunks(tmp_path):
	import asyncio
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	pump = tmp_path / 'pump.txt'
	pump.write_text('Pump P-204B bearing temperature rose over four shifts.\n')
	valve = tmp_path / 'valve.txt'
	valve.write_text('Valve HV-1127 was isolated for the changeover.\n')
	asyncio.run(rag.ingest(pump, {'tenant_id': 't1'}))
	asyncio.run(rag.ingest(valve, {'tenant_id': 't1'}))

	found = asyncio.run(rag.search('anything', metadata={'equipment_tags': ['HV-1127']}))
	assert [hit['source'] for hit in found] == ['valve.txt']
	found = asyncio.run(rag.search('anything', metadata={'equipment_tags': ['P-204B']}))
	assert [hit['source'] for hit in found] == ['pump.txt']
	assert asyncio.run(rag.search('anything', metadata={'equipment_tags': ['X-999']})) == []

def test_scalar_metadata_filters_are_unaffected_by_list_support(tmp_path):
	import asyncio
	rag = RagService(f'sqlite:///{tmp_path / "rag.db"}')
	source = tmp_path / 'a.txt'
	source.write_text('Pump P-204B reading.\n')
	asyncio.run(rag.ingest(source, {'tenant_id': 't1', 'file_id': 'f1'}))
	assert asyncio.run(rag.search('pump', metadata={'tenant_id': 't1'}))
	assert asyncio.run(rag.search('pump', metadata={'tenant_id': 'other'})) == []
	assert asyncio.run(rag.search('pump', metadata={'file_id': 'f1'}))
	assert asyncio.run(rag.search('pump', metadata={'file_id': 'nope'})) == []

def _general_job(tmp_path, retrieval):
	return {
		'job_id': 'j-general', 'task_type': 'general', 'plan': [],
		'observations': [], 'artifacts': [], 'tool_calls': [],
		'retrieval': retrieval,
	}

def test_a_question_is_verified_not_stamped_passed(tmp_path):
	# General tasks used to short-circuit with {'passed': True, 'checks': {}} and
	# never reach the verifier, so REQUIRE_EVIDENCE could not apply to the one
	# path users spend all their time on.
	from app.verification.verifier import Verifier
	result = Verifier(str(tmp_path)).verify(_general_job(tmp_path, [{'chunk_id': 'c1', 'source': 'sop.pdf'}]))
	assert result['checks'], 'a question must produce real checks, not an empty dict'
	assert result['checks']['evidence_grounded'] is True
	# A question writes no files and runs no plan; those checks are not-applicable
	# for it, the way citations_present already is outside a document workflow.
	assert result['checks']['artifacts_exist'] is True
	assert result['checks']['plan_completed'] is True
	assert result['passed'] is True

def test_an_ungrounded_question_is_blocked_when_evidence_is_required(tmp_path, monkeypatch):
	monkeypatch.setenv('REQUIRE_EVIDENCE', 'true')
	from app.verification.verifier import Verifier
	result = Verifier(str(tmp_path)).verify(_general_job(tmp_path, []))
	assert result['checks']['evidence_grounded'] is False
	assert result['passed'] is False
	assert 'evidence_grounded' in result['notes'][0]

def test_an_ungrounded_question_is_advisory_when_evidence_is_not_required(tmp_path, monkeypatch):
	# Default deployment: the failure is still reported, it just does not block --
	# some questions legitimately have no corpus to ground against.
	monkeypatch.setenv('REQUIRE_EVIDENCE', 'false')
	from app.verification.verifier import Verifier
	result = Verifier(str(tmp_path)).verify(_general_job(tmp_path, []))
	assert result['checks']['evidence_grounded'] is False
	assert result['passed'] is True

def test_artifact_tasks_still_require_artifacts(tmp_path):
	# The general-task escapes must not weaken any other task type.
	from app.verification.verifier import Verifier
	job = _general_job(tmp_path, [{'chunk_id': 'c1', 'source': 'sop.pdf'}])
	job['task_type'] = 'document_workflow'
	result = Verifier(str(tmp_path)).verify(job)
	assert result['checks']['artifacts_exist'] is False
	assert result['passed'] is False

def test_a_reviewer_sees_only_the_jobs_waiting_on_them(tmp_path):
	# Enforcing who may approve is useless if reviewers cannot see what needs
	# approving -- but the window must be exactly that, not a general read.
	from app.storage.store import Store
	store = Store(f'sqlite:///{tmp_path / "store.db"}')
	store.save({'job_id': 'own', 'status': 'done', 'task': 'mine', 'user_context': {'user_id': 'rev', 'tenant_id': 't1'}})
	store.save({'job_id': 'pending', 'status': 'awaiting_approval', 'task': 'needs review', 'user_context': {'user_id': 'alice', 'tenant_id': 't1'}})
	store.save({'job_id': 'other', 'status': 'done', 'task': 'not theirs', 'user_context': {'user_id': 'alice', 'tenant_id': 't1'}})
	store.save({'job_id': 'foreign', 'status': 'awaiting_approval', 'task': 'other tenant', 'user_context': {'user_id': 'zed', 'tenant_id': 't2'}})

	reviewer = {'user_id': 'rev', 'tenant_id': 't1', 'role': 'higher'}
	analyst = {'user_id': 'rev', 'tenant_id': 't1', 'role': 'lower'}
	assert {j['job_id'] for j in store.recent_jobs(reviewer)} == {'own', 'pending'}
	# The tenant boundary still holds, and an analyst gains nothing.
	assert {j['job_id'] for j in store.recent_jobs(analyst)} == {'own'}

def test_file_listing_applies_the_owner_filter_before_the_limit(tmp_path):
	# The limit used to be applied to every file in the tenant and the owner check
	# afterwards in Python, so a user whose uploads sorted late saw none of them.
	from app.storage.store import Store
	store = Store(f'sqlite:///{tmp_path / "store.db"}')
	for index in range(120):
		store.register_file(f'other-{index:03}', 'bob', 't1', f'aaa-{index:03}.txt', '/tmp/x', {})
	for index in range(5):
		store.register_file(f'mine-{index}', 'alice', 't1', f'zzz-{index}.txt', '/tmp/x', {})

	alice = {'user_id': 'alice', 'tenant_id': 't1', 'role': 'lower'}
	listed = store.files(alice)
	assert len(listed) == 5, 'a user must see all of their own files, not a truncated page'
	assert all(record['name'].startswith('zzz-') for record in listed)

def test_administrators_still_see_every_file_in_the_tenant(tmp_path):
	from app.storage.store import Store
	store = Store(f'sqlite:///{tmp_path / "store.db"}')
	store.register_file('f1', 'alice', 't1', 'a.txt', '/tmp/x', {})
	store.register_file('f2', 'bob', 't1', 'b.txt', '/tmp/x', {})
	store.register_file('f3', 'zed', 't2', 'c.txt', '/tmp/x', {})
	admin = {'user_id': 'root', 'tenant_id': 't1', 'role': 'admin'}
	assert {record['id'] for record in store.files(admin)} == {'f1', 'f2'}

def test_approval_request_ignores_a_body_supplied_reviewer(tmp_path):
	# The field is still accepted so existing callers do not break, but it carries
	# no authority: the route records identity['user_id'].
	from app.schemas.contracts import ApprovalRequest
	assert ApprovalRequest(approved=True).reviewer_user_id is None
	assert ApprovalRequest(approved=True, reviewer_user_id='someone-else').approved is True

def test_dev_login_accepts_an_email_or_a_bare_role(monkeypatch):
	# The console's sign-in field is type="email", so a browser will not submit a
	# bare "admin" -- the redesigned frontend could not log in at all until the
	# local part was accepted. Scripts and the CLI still pass the role name.
	import app.dev_auth as dev_auth
	monkeypatch.setenv('DEV_AUTH_ENABLED', 'true')
	monkeypatch.setenv('JWT_SECRET', 'x' * 40)
	monkeypatch.setenv('DEV_ADMIN_PASSWORD', 'secret-admin')

	def login(username, password):
		return dev_auth.issue_dev_token(dev_auth.DevLoginRequest(username=username, password=password))

	assert login('admin@sovereign.io', 'secret-admin').user['role'] == 'admin'
	assert login('admin', 'secret-admin').user['role'] == 'admin'
	assert login('ADMIN@Example.COM', 'secret-admin').user['role'] == 'admin'

def test_dev_login_still_rejects_a_bad_password_or_unknown_account(monkeypatch):
	# The domain carries no authority: accepting the local part decides which
	# account is named, nothing more.
	import pytest
	from fastapi import HTTPException
	import app.dev_auth as dev_auth
	monkeypatch.setenv('DEV_AUTH_ENABLED', 'true')
	monkeypatch.setenv('JWT_SECRET', 'x' * 40)
	monkeypatch.setenv('DEV_ADMIN_PASSWORD', 'secret-admin')

	for username, password in (('admin@sovereign.io', 'wrong'), ('nobody@sovereign.io', 'secret-admin')):
		with pytest.raises(HTTPException) as raised:
			dev_auth.issue_dev_token(dev_auth.DevLoginRequest(username=username, password=password))
		assert raised.value.status_code == 401
		assert raised.value.detail == 'INVALID_CREDENTIALS'

def test_uploads_record_when_they_arrived(tmp_path):
	from app.storage.store import Store
	store = Store(f'sqlite:///{tmp_path / "store.db"}')
	store.register_file('f1', 'alice', 't1', 'a.txt', str(tmp_path / 'a.txt'), {})
	record = store.files({'user_id': 'alice', 'tenant_id': 't1', 'role': 'lower'})[0]
	assert record['created_at'], 'the interface reads this; without it every row says "unknown"'
	assert record['created_at'].startswith('20')

def test_file_listing_is_newest_first(tmp_path):
	import time
	from app.storage.store import Store
	store = Store(f'sqlite:///{tmp_path / "store.db"}')
	for name in ('first.txt', 'second.txt', 'third.txt'):
		store.register_file(name, 'alice', 't1', name, str(tmp_path / name), {})
		time.sleep(0.01)
	listed = store.files({'user_id': 'alice', 'tenant_id': 't1', 'role': 'lower'})
	assert [r['name'] for r in listed] == ['third.txt', 'second.txt', 'first.txt']

def test_a_database_without_created_at_is_migrated_and_backfilled(tmp_path):
	# _create_schema returns early against an already-provisioned database, so a
	# CREATE TABLE change never reaches the databases this matters to. The column
	# is added separately, and backfilled from the upload's mtime -- which is when
	# it was written, so it is the real upload time and not a placeholder.
	import os
	import time
	from sqlalchemy import create_engine, text
	from app.storage.store import Store

	url = f'sqlite:///{tmp_path / "old.db"}'
	upload = tmp_path / 'legacy.txt'
	upload.write_text('uploaded before the column existed')
	written = time.time() - 3600
	os.utime(upload, (written, written))

	engine = create_engine(url)
	with engine.begin() as db:
		db.execute(text('CREATE TABLE files(id VARCHAR(255) PRIMARY KEY, owner_id VARCHAR(255) NOT NULL, tenant_id VARCHAR(255) NOT NULL, name VARCHAR(255) NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL)'))
		db.execute(text("INSERT INTO files VALUES('old','alice','t1','legacy.txt',:path,'{}')"), {'path': str(upload)})

	store = Store(url)  # constructing it runs the migration
	record = store.files({'user_id': 'alice', 'tenant_id': 't1', 'role': 'lower'})[0]
	assert record['name'] == 'legacy.txt'
	assert record['created_at'], 'the existing row should have been backfilled'
	assert record['created_at'].startswith('20')

def test_a_row_whose_upload_is_gone_stays_unknown(tmp_path):
	# Better an honest "unknown" than a made-up timestamp.
	from sqlalchemy import create_engine, text
	from app.storage.store import Store

	url = f'sqlite:///{tmp_path / "missing.db"}'
	engine = create_engine(url)
	with engine.begin() as db:
		db.execute(text('CREATE TABLE files(id VARCHAR(255) PRIMARY KEY, owner_id VARCHAR(255) NOT NULL, tenant_id VARCHAR(255) NOT NULL, name VARCHAR(255) NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL)'))
		db.execute(text("INSERT INTO files VALUES('gone','alice','t1','gone.txt','/nonexistent/gone.txt','{}')"))

	store = Store(url)
	record = store.files({'user_id': 'alice', 'tenant_id': 't1', 'role': 'lower'})[0]
	assert record['created_at'] is None
