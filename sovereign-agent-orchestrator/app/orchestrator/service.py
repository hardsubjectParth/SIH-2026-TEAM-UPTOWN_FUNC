import base64
import re
import uuid
from pathlib import Path
from typing import TypedDict

try:
    from langgraph.graph import StateGraph, START, END
except ImportError:
    START = '__start__'
    END = '__end__'

    class StateGraph:
        def __init__(self, state_type):
            self.node = None

        def add_node(self, name, fn):
            self.node = fn

        def add_edge(self, *args):
            pass

        def compile(self):
            node = self.node

            class Graph:
                async def ainvoke(self, state):
                    return await node(state)

            return Graph()

from app.models.adapter import OllamaAdapter
from app.models.router import is_image_attachment
from app.schemas.contracts import JobStatus


class State(TypedDict, total=False):
    job: dict


_FENCE = re.compile(r'```([\w+.\-]*)\n(.*?)```', re.S)
# The opening half only, for a block the model never got to close.
_OPEN_FENCE = re.compile(r'```([\w+.\-]*)\n')
_CODE_EXT = {
    'python': '.py', 'py': '.py', 'javascript': '.js', 'js': '.js', 'typescript': '.ts',
    'ts': '.ts', 'bash': '.sh', 'sh': '.sh', 'shell': '.sh', 'json': '.json', 'yaml': '.yml',
    'yml': '.yml', 'sql': '.sql', 'go': '.go', 'rust': '.rs', 'rs': '.rs', 'c': '.c',
    'cpp': '.cpp', 'c++': '.cpp', 'java': '.java', 'html': '.html', 'css': '.css', 'text': '.txt',
}

_TITLES = {
    'document_workflow': 'Document Summary',
    'multimodal': 'Document Review',
    'calculation': 'Worked Calculation',
    'spreadsheet': 'Spreadsheet Analysis',
    'presentation': 'Briefing Deck',
}

# An attached image is sent to the model inline, base64-encoded, so its size lands
# directly in the request and in the model's context window. Uploads are allowed up
# to MAX_UPLOAD_BYTES (50 MB by default), which is far more than a vision model
# needs and enough to blow a 32K context, so anything large is re-encoded down to
# a long edge that still resolves dimension text on a drawing.
_MAX_IMAGE_BYTES = 3 * 1024 * 1024
_MAX_IMAGE_EDGE = 1600

# There is a floor as well as a ceiling. A vision model tokenises an image by area,
# so a small input is not merely low-detail -- it is allotted few visual tokens and
# read coarsely. Measured on a 335x597 engineering drawing: sent at native size the
# model reported "two holes of diameter 8.15" for a `2-R15` fillet callout and a
# width of 14.5 for a section-plane label, inventing features that are not on the
# page, and missed the part's main diameter. The identical image enlarged past this
# floor read the diameter correctly and fabricated nothing, across two independent
# variants. Interpolation adds no optical information -- what it buys is
# tokenisation headroom -- so this is a floor under a bad input, not a substitute
# for scanning the drawing properly.
# The floor applies to the SHORT edge. Constraining the long edge instead leaves a
# portrait page far too narrow -- a 335x597 drawing fitted to a 1400 long edge is only
# 786 wide, and measured at that width the model still misread the main diameter
# (reporting "81.92" for a bare Ø192) where the same drawing at ~1340 wide read it
# correctly. Horizontal pixels per character is what decides whether a callout is
# legible, and that follows the short edge on a portrait scan.
_MIN_IMAGE_SHORT_EDGE = 1200
# Keep the enlarged result inside the ceiling the downscale path targets, so a very
# elongated image cannot be enlarged into something that then needs shrinking.
_MAX_UPSCALED_LONG_EDGE = 2600
# Cap the enlargement so a thumbnail or an icon is not blown up into a megapixel of
# interpolation, which costs tokens and latency and recovers nothing.
_MAX_UPSCALE = 4.0
# Only images that are genuinely starved of pixels are enlarged. A 1600x900 screenshot
# has a narrow short edge but 1.4 MP of detail and reads fine as it is; enlarging it
# would spend tokens and latency to add nothing. The drawing that prompted all of this
# is 0.2 MP.
_UPSCALE_BELOW_PIXELS = 1_200_000

# A scanned PDF is a picture of a page, and until now it never reached the vision
# model: is_image_attachment matched only image MIME types, so a drawing delivered as
# a PDF -- which is how P&IDs, SOPs and maintenance records actually arrive -- was
# answered from whatever ingest-time OCR had managed. Pages whose text layer is thin
# are rasterised and attached alongside the images.
_PDF_RASTER_DPI = 170
# Below this many non-whitespace characters a page is effectively a picture. A real
# text layer needs no vision pass and should not cost ~2.8k tokens a page.
_PDF_TEXT_PER_PAGE = 200

# Measured at 2,818 tokens for one enlarged drawing, so eleven images fill a 32K
# window with nothing left for the answer. The cap leaves room for the system prompt,
# retrieved evidence, history and an 8k vision reply; anything past it is reported
# rather than silently dropped into a truncated prompt.
_MAX_ATTACHED_IMAGES = 6

# Generation settings for a call that carries an image, all three measured on
# qwen3-vl:8b against a dense engineering drawing.
#
# num_predict: the model reasons before answering whatever `think` is set to, and that
# reasoning scales with image size -- on an enlarged drawing it ran to 12,277
# characters. At 1536 it never reached an answer at all; at 4096 it produced 400
# characters and was cut off mid-sentence. 8192 leaves room for the answer.
#
# temperature: reading dimensions off a page is transcription, not composition, so the
# sampler should be close to greedy. An early run at 0.3 fell into a repetition loop
# ("1 1/2" (another)" ~100 times) and 0.6 was adopted to escape it -- but that loop was
# budget starvation at num_predict=1536, and it does not reproduce at 8192. Measured
# over repeated samples on the same image, 0.2 scored 8/10 known labels twice with
# byte-identical output, while 0.6 scored 6/10 and 7/10 and flipped a `150` to `158`
# between runs. High temperature was buying variance, not robustness.
_VISION_CHAT_OPTIONS = {'num_predict': 8192, 'temperature': 0.2}

# Generation budget per task type. The default 1536 tokens is ample for a chat answer
# and nowhere near enough for one that carries a file: a "function plus a unit test"
# request came back at 4,931 characters and was still cut off mid-expression, leaving
# an unterminated ``` fence. _code_blocks then matched nothing, the plan had no source
# file to run, `code_executed` failed, and the job spent all three iterations
# re-planning into the same wall -- seven minutes to produce a truncated .md file.
_TASK_CHAT_OPTIONS = {
    'coding': {'num_predict': 6144},
    'document_workflow': {'num_predict': 3072},
    'presentation': {'num_predict': 3072},
    'spreadsheet': {'num_predict': 3072},
    'calculation': {'num_predict': 3072},
}


def _pdf_page_images(data, limit):
    """Rendered pages of a PDF that carry no usable text layer.

    Returns ``(pages, needing_vision)``. Only `limit` pages are rasterised -- that is
    the expensive part -- but every page that would have needed one is counted, so the
    caller can report honestly how much of the document the model did not see.
    """
    import pymupdf

    pages = []
    needing_vision = 0
    document = pymupdf.open(stream=data, filetype='pdf')
    try:
        for index in range(document.page_count):
            page = document.load_page(index)
            if len(re.sub(r'\s+', '', page.get_text() or '')) >= _PDF_TEXT_PER_PAGE:
                continue
            needing_vision += 1
            if len(pages) < limit:
                pages.append((index + 1, page.get_pixmap(dpi=_PDF_RASTER_DPI).tobytes('png')))
    finally:
        document.close()
    return pages, needing_vision


def _fit_for_vision(data):
    """Bring an attached image into the size band the vision model reads well.

    Returns ``(bytes, note)``; the note describes any resize, for the event stream.
    Anything unreadable is passed through untouched rather than failing the job.
    """
    try:
        import io
        from PIL import Image

        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert('RGB')
            width, height = image.size
            long_edge = max(width, height)

            if len(data) > _MAX_IMAGE_BYTES:
                image.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE), Image.LANCZOS)
                # JPEG for the downscale path: these are large photos and scans,
                # where the size saving matters more than the last of the detail.
                return _encode(image, 'JPEG', (width, height), 'downscaled')

            short_edge = min(width, height)
            if short_edge < _MIN_IMAGE_SHORT_EDGE and width * height < _UPSCALE_BELOW_PIXELS:
                scale = min(
                    _MIN_IMAGE_SHORT_EDGE / short_edge,
                    _MAX_UPSCALED_LONG_EDGE / long_edge,
                    _MAX_UPSCALE,
                )
                if scale <= 1.0:
                    return data, None
                image = image.resize((round(width * scale), round(height * scale)), Image.LANCZOS)
                # PNG for the upscale path: the inputs that need it are line art,
                # and JPEG ringing around thin dimension lines is exactly the
                # detail the enlargement exists to preserve.
                return _encode(image, 'PNG', (width, height), 'upscaled')

        return data, None
    except Exception:
        return data, None


def _encode(image, fmt, original_size, action):
    import io

    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **({'quality': 85} if fmt == 'JPEG' else {}))
    note = f'{action} {original_size[0]}x{original_size[1]} -> {image.width}x{image.height}'
    return buffer.getvalue(), note


class Orchestrator:
    def __init__(
        self,
        store,
        workspace,
        router,
        policy,
        tools,
        verifier,
        model,
        *,
        ollama_base_url=None,
        model_mode=None,
        keep_alive=None,
        max_iterations=3,
        max_tool_calls=12,
    ):
        self.store = store
        self.workspace = workspace
        self.router = router
        self.policy = policy
        self.tools = tools
        self.verifier = verifier
        self.model = model
        self.ollama_base_url = ollama_base_url
        self.model_mode = model_mode
        self.keep_alive = keep_alive
        self.max_iterations = max(1, int(max_iterations))
        self.max_tool_calls = max(1, int(max_tool_calls))
        self._adapters = {}
        self.tasks = {}
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ model

    def _adapter_for(self, routing):
        """Return the adapter for the model the router actually chose.

        In ``ollama`` mode this builds (and caches) one ``OllamaAdapter`` per
        model name, so a job routed to ``qwen-coder`` is served by ``qwen-coder``
        rather than by whatever single model the process started with. Any other
        mode keeps the injected adapter (the FakeModel used by tests / offline).
        """
        if (self.model_mode or '').lower() != 'ollama' or not self.ollama_base_url:
            return self.model
        name = (routing or {}).get('model_name')
        if not name or name == 'fake':
            return self.model
        if name not in self._adapters:
            self._adapters[name] = OllamaAdapter(self.ollama_base_url, name, self.keep_alive)
        return self._adapters[name]

    def _attached_images(self, j):
        """Base64 payloads for the attachments a vision model can look at directly.

        Ollama takes these as ``images`` on the user message. Without them the
        model only ever saw the RAG extractor's OCR line for the file, which on
        an engineering drawing is close to useless -- so a question about a
        picture got answered from a garbled transcription rather than the
        picture.
        """
        out = []
        omitted = 0
        for item in j.get('attachments') or []:
            name = item.get('name') or Path(str(item.get('path', ''))).name
            is_pdf = str(item.get('mime_type') or '').lower().endswith('/pdf') or name.lower().endswith('.pdf')
            if not is_image_attachment(item) and not is_pdf:
                continue
            try:
                data = self.workspace.safe(j['job_id'], item['path']).read_bytes()
            except (OSError, ValueError, KeyError) as exc:
                self._emit(j, 'attachment_unreadable', {'name': name, 'error': str(exc)})
                continue

            if is_pdf:
                # Only the pages that are pictures. A PDF with a real text layer is
                # already readable as text and costs nothing to skip.
                try:
                    rendered, needing_vision = _pdf_page_images(data, _MAX_ATTACHED_IMAGES - len(out))
                except Exception as exc:
                    self._emit(j, 'attachment_unreadable', {'name': name, 'error': f'PDF render failed: {exc}'})
                    continue
                if not needing_vision:
                    continue
                omitted += needing_vision - len(rendered)
                candidates = [(f'{name} p.{number}', png) for number, png in rendered]
            else:
                candidates = [(name, data)]

            for label, payload in candidates:
                if len(out) >= _MAX_ATTACHED_IMAGES:
                    omitted += 1
                    continue
                fitted, note = _fit_for_vision(payload)
                out.append({'name': label, 'note': note, 'data': base64.b64encode(fitted).decode('ascii')})
        return out, omitted

    async def _call_model(self, j, feedback=None, images=(), omitted=0):
        context = ''
        if getattr(self.tools, 'rag', None):
            user_context = j.get('user_context', {})
            attached_ids = [item['file_id'] for item in j.get('attachments', []) if item.get('file_id')]
            hits = await self.tools.rag.search(
                j['task'], user_context, 8,
                {'tenant_id': user_context.get('tenant_id', 'default')},
                attached_ids or None,
            )
            j['retrieval'] = hits
            j['citations'] = hits
            if hits:
                j['observations'].append({'hits': hits, 'sources': [{'name': h['source'], 'source': h['source']} for h in hits]})
            context = (
                '\n\nRetrieved company evidence:\n' + '\n'.join(f"[{h['source']}] {h['content']}" for h in hits)
                if hits else '\n\nNo indexed company evidence matched this task.'
            )

        task_type = j.get('routing', {}).get('task_type', 'general')
        messages = [{'role': 'system', 'content': self._system_prompt(task_type, images, omitted)}]
        if j.get('conversation_id'):
            history = self.store.messages(j['conversation_id'], 20)
            if history and history[-1]['role'] == 'user' and history[-1]['content'] == j['task']:
                history = history[:-1]
            messages.extend({'role': item['role'], 'content': item['content']} for item in history)

        user = j['task'] + context
        if feedback:
            user += (
                '\n\nA previous attempt did not pass verification for this reason:\n'
                f'{feedback}\nProduce a corrected response.'
            )
        message = {'role': 'user', 'content': user}
        if images:
            message['images'] = [image['data'] for image in images]
            self._emit(j, 'images_attached', {
                'names': [image['name'] for image in images],
                'resized': [f"{image['name']}: {image['note']}" for image in images if image.get('note')],
                'omitted': omitted,
            })
        messages.append(message)

        adapter = self._adapter_for(j['routing'])
        options = dict(_TASK_CHAT_OPTIONS.get(task_type, {}))
        if images:
            options.update(_VISION_CHAT_OPTIONS)
        try:
            response = await adapter.chat(messages, **options)
        except Exception as exc:
            # The routed model may not be pulled on this host. Degrade to the
            # process default (or FakeModel) rather than failing the whole job.
            if adapter is self.model:
                raise
            self._emit(j, 'model_fallback', {
                'from': j['routing'].get('model_name'), 'to': getattr(self.model, 'model', 'fallback'), 'error': str(exc),
            })
            adapter = self.model
            response = await adapter.chat(messages, **options)

        j['model_response'] = response
        j['_model_name'] = getattr(adapter, 'model', j['routing'].get('model_name', 'unknown'))
        j['_model_url'] = getattr(adapter, 'base_url', getattr(adapter, 'url', 'unknown'))

        if j.get('conversation_id'):
            self.store.add_message(str(uuid.uuid4()), j['conversation_id'], 'assistant', response.get('content', str(response)), j.get('retrieval', []))

        self._emit(j, 'model_response', {'model_id': j['routing']['model_id'], 'response': response})
        return response

    @staticmethod
    def _system_prompt(task_type, images=None, omitted=0):
        base = (
            'You are the local planning model for the Sovereign Agent Orchestrator. '
            'Use conversation history and retrieved evidence when provided. For factual '
            'claims, cite evidence using [source] markers. If the evidence is insufficient, '
            'say so explicitly. Do not claim to have accessed files unless they are provided '
            'through the orchestrator tools. You cannot save, download, or export files '
            'yourself, and you do not need to -- the orchestrator packages your response into '
            'the requested document/spreadsheet/slide deck/PDF automatically after you answer. '
            'If asked for a report, document, or PDF, just write the actual content requested; '
            'never say you are unable to generate or send a file.'
        )
        if task_type == 'coding':
            base += (
                ' The task is a coding task. Return the solution as fenced code blocks '
                '(```python ... ```). Include a runnable check or assertions in the main block. '
                'Keep it self-contained and dependency-free.'
            )
        if task_type == 'calculation':
            base += ' Show the calculation step by step and state the final result with units.'
        if task_type == 'presentation':
            base += ' Structure the answer as short titled sections suitable for slides.'
        if images:
            names = ', '.join(image['name'] for image in images)
            # Without this the retrieval instruction above works against us: the
            # evidence block also carries the OCR line for these same files, and a
            # drawing OCRs to noise, so the model dutifully reported that the
            # evidence was insufficient while the image sat unread in its context.
            base += (
                f' The user attached {len(images)} image(s) ({names}), included directly in this '
                'message -- you can see them. Answer from what you actually observe in them: read '
                'off dimensions, labels, callouts, tag numbers, title blocks and annotations as '
                'they appear. The images are the primary evidence and outrank any OCR text for '
                'the same filenames in the retrieved evidence below, which is a machine '
                'transcription and is often garbled. Do not say the evidence is insufficient '
                'without first describing what you can see. State plainly if a value genuinely '
                'is not legible or not shown, rather than guessing it.'
            )
            if omitted:
                base += (
                    f' {omitted} further page(s) or image(s) were attached but could not be included '
                    'in this message. Answer only from what you were given and say that the remainder '
                    'was not available to you.'
                )
        return base

    # ------------------------------------------------------------------ plan

    def _evidence_body(self, j):
        hits = j.get('retrieval') or []
        if not hits:
            return (
                'No indexed evidence matched this task. Nothing in this artifact is backed '
                'by retrieved company records.'
            )
        return '\n\n'.join(
            f"[{i}] {h.get('source', 'unknown')} (score {round(float(h.get('score', 0)), 3)}):\n{(h.get('content') or '').strip()}"
            for i, h in enumerate(hits, 1)
        )

    def _provenance_body(self, j):
        routing = j.get('routing', {})
        return (
            f"Model: {j.get('_model_name', routing.get('model_name', 'unknown'))} "
            f"(routed for: {routing.get('task_type', 'general')}, capability: {routing.get('capability', 'n/a')})\n"
            f"Inference endpoint: {j.get('_model_url', 'unknown')}\n"
            'Invocation path: OllamaAdapter -> /api/chat (local). All inference and retrieval ran on this machine.'
        )

    def _citations(self, j):
        out = []
        for h in j.get('retrieval') or []:
            cid = str(h.get('chunk_id', ''))[:8]
            out.append(f"{h.get('source', 'unknown')} (chunk {cid}, score {round(float(h.get('score', 0)), 3)})")
        return out or ['No retrieved evidence; artifact reflects the local model response only.']

    def _artifact_title(self, j):
        task = j['task'].lower()
        if 'approval' in task:
            return 'Approval Note'
        if 'analysis' in task or 'analyse' in task or 'analyze' in task:
            return 'Analysis Report'
        return _TITLES.get(j.get('routing', {}).get('task_type'), 'Agent Report')

    def _search_step(self, j):
        return {
            'step_id': 's1',
            'description': 'Retrieve supporting evidence from the local knowledge base',
            'tool': 'search_documents',
            'tool_args': {
                'query': j['task'][:200],
                'metadata': {'tenant_id': j.get('user_context', {}).get('tenant_id', 'default')},
                'file_ids': [i['file_id'] for i in j.get('attachments', []) if i.get('file_id')] or None,
                'identity': j.get('user_context', {}),
            },
            'status': 'pending',
        }

    def _doc_sections(self, j, body_heading='Findings'):
        body = (j.get('model_response', {}).get('content') or '').strip() or f"The local model returned no content. Task: {j['task']}"
        return [
            {'heading': 'Task', 'body': j['task']},
            {'heading': body_heading, 'body': body},
            {'heading': 'Evidence Used', 'body': self._evidence_body(j)},
            {'heading': 'Provenance', 'body': self._provenance_body(j)},
        ]

    def _plan(self, j):
        task_type = j.get('routing', {}).get('task_type', 'general')
        if task_type == 'general':
            j['plan'] = []
            return
        builder = {
            'coding': self._coding_plan,
            'calculation': self._calc_plan,
            'spreadsheet': self._spreadsheet_plan,
            'presentation': self._presentation_plan,
        }.get(task_type, self._document_plan)
        j['plan'] = builder(j)

    def _document_plan(self, j):
        title = self._artifact_title(j)
        sections = self._doc_sections(j)
        citations = self._citations(j)
        slug = title.lower().replace(' ', '_')
        return [
            self._search_step(j),
            {
                'step_id': 's2',
                'description': f'Generate {title} (.docx)',
                'tool': 'generate_docx',
                'tool_args': {
                    'filename': slug + '.docx',
                    'title': title,
                    'sections': sections,
                    'citations': citations,
                },
                'status': 'pending',
            },
            {
                'step_id': 's3',
                'description': f'Generate {title} (.pdf)',
                'tool': 'generate_pdf',
                'tool_args': {
                    'filename': slug + '.pdf',
                    'title': title,
                    'sections': sections,
                    'citations': citations,
                },
                'status': 'pending',
            },
        ]

    def _calc_plan(self, j):
        sections = self._doc_sections(j, body_heading='Method and Steps')
        citations = self._citations(j)
        steps = [
            self._search_step(j),
            {
                'step_id': 's2',
                'description': 'Generate the worked calculation (.docx)',
                'tool': 'generate_docx',
                'tool_args': {
                    'filename': 'worked_calculation.docx',
                    'title': 'Worked Calculation',
                    'sections': sections,
                    'citations': citations,
                },
                'status': 'pending',
            },
            {
                'step_id': 's3',
                'description': 'Generate the worked calculation (.pdf)',
                'tool': 'generate_pdf',
                'tool_args': {
                    'filename': 'worked_calculation.pdf',
                    'title': 'Worked Calculation',
                    'sections': sections,
                    'citations': citations,
                },
                'status': 'pending',
            },
        ]
        blocks = self._code_blocks(j)
        if any(lang in ('python', 'py') for lang, _ in blocks):
            steps.insert(1, {
                'step_id': 's1b',
                'description': 'Check the calculation by running it in the sandbox',
                'tool': 'write_file',
                'tool_args': {'path': 'working/check.py', 'content': next(b for l, b in blocks if l in ('python', 'py'))},
                'status': 'pending',
            })
            steps.insert(2, {
                'step_id': 's1c',
                'description': 'Execute the check',
                'tool': 'run_python',
                'tool_args': {'path': 'working/check.py', 'timeout': 15},
                'status': 'pending',
            })
        return steps

    def _spreadsheet_plan(self, j):
        sheet = next((a for a in j.get('attachments', []) if str(a.get('name', '')).lower().endswith(('.xlsx', '.xlsm', '.csv'))), None)
        if not sheet:
            return self._document_plan(j)
        return [
            {
                'step_id': 's1',
                'description': 'Profile the attached spreadsheet',
                'tool': 'spreadsheet_profile',
                'tool_args': {'path': sheet['path']},
                'status': 'pending',
            },
            {
                'step_id': 's2',
                'description': 'Extract the tables',
                'tool': 'extract_tables',
                'tool_args': {'path': sheet['path']},
                'status': 'pending',
            },
            {
                'step_id': 's3',
                'description': 'Write the analysis workbook (.xlsx)',
                'tool': 'generate_xlsx',
                'tool_args': {
                    'filename': 'spreadsheet_analysis.xlsx',
                    'summary': (j.get('model_response', {}).get('content') or '').strip(),
                    'source': sheet['name'],
                    'tables': '$tables',
                },
                'status': 'pending',
            },
        ]

    def _presentation_plan(self, j):
        body = (j.get('model_response', {}).get('content') or '').strip()
        return [
            self._search_step(j),
            {
                'step_id': 's2',
                'description': 'Generate the briefing deck (.pptx)',
                'tool': 'generate_pptx',
                'tool_args': {
                    'filename': 'briefing_deck.pptx',
                    'title': self._artifact_title(j),
                    'body': body,
                    'evidence': self._evidence_body(j),
                    'provenance': self._provenance_body(j),
                },
                'status': 'pending',
            },
        ]

    # ------------------------------------------------------------------ coding

    def _code_blocks(self, j):
        content = j.get('model_response', {}).get('content', '') or ''
        blocks = []
        for lang, body in _FENCE.findall(content):
            body = body.strip('\n')
            if body.strip():
                blocks.append((lang.lower(), body))

        # A response cut off by the token budget ends inside its own fence, so the
        # regex above -- which needs a closing ``` -- matches nothing at all and the
        # code is silently discarded. Take the tail as a block so the failure surfaces
        # as code that will not run, rather than as "no fenced code found".
        consumed = content.rfind('```')
        opening = _OPEN_FENCE.search(content, 0 if not blocks else consumed)
        if opening and '```' not in content[opening.end():]:
            body = content[opening.end():].strip('\n')
            if body.strip():
                blocks.append(((opening.group(1) or '').lower(), body))
                j['_truncated_code'] = True
        return blocks

    def _coding_plan(self, j):
        blocks = self._code_blocks(j)
        content = (j.get('model_response', {}).get('content') or '').strip()
        if not blocks:
            return [{
                'step_id': 's1',
                'description': 'Save the model response (no fenced code found)',
                'tool': 'write_file',
                'tool_args': {'path': 'output/solution.md', 'content': content or f"No content. Task: {j['task']}"},
                'status': 'pending',
            }]
        steps = []
        used = set()
        py_files = []
        for index, (lang, body) in enumerate(blocks, 1):
            suffix = _CODE_EXT.get(lang, '.txt')
            name = f'snippet_{index}{suffix}'
            while name in used:
                index += 1
                name = f'snippet_{index}{suffix}'
            used.add(name)
            steps.append({
                'step_id': f's{len(steps) + 1}',
                'description': f'Write {lang or "code"} to {name}',
                'tool': 'write_file',
                'tool_args': {'path': f'output/{name}', 'content': body + '\n'},
                'status': 'pending',
            })
            if suffix == '.py':
                py_files.append(name)
        for name in py_files:
            steps.append({
                'step_id': f's{len(steps) + 1}',
                'description': f'Run {name} in the no-network sandbox',
                'tool': 'run_python',
                'tool_args': {'path': f'output/{name}', 'timeout': 15},
                'status': 'pending',
            })
        steps.append({
            'step_id': f's{len(steps) + 1}',
            'description': 'Save the full model response as a transcript',
            'tool': 'write_file',
            'tool_args': {'path': 'output/response.md', 'content': content},
            'status': 'pending',
        })
        return steps

    # ------------------------------------------------------------------ run

    def _build_graph(self):
        g = StateGraph(State)

        async def workflow(state):
            await self._run_impl(state['job'])
            return state

        g.add_node('ORCHESTRATOR', workflow)
        g.add_edge(START, 'ORCHESTRATOR')
        g.add_edge('ORCHESTRATOR', END)
        return g.compile()

    async def run(self, j):
        await self.graph.ainvoke({'job': j})

    def _emit(self, j, t, data=None):
        self.store.event(j['job_id'], t, data or {})
        self.store.save(j)

    def _status(self, j, s):
        j['status'] = s.value
        self._emit(j, 'status_changed', {'status': s.value})

    async def _run_impl(self, j):
        self.workspace.create(j['job_id'])
        self._status(j, JobStatus.planning)

        # Resolved before routing: whether a PDF is a scan or a text document is only
        # knowable by opening it, and the answer decides which model must serve the job.
        # Done once here rather than per iteration, and deliberately not stored on the
        # job -- base64 pages would be persisted to the database on every save.
        images, omitted = self._attached_images(j)
        j['routing'] = self.router.route(j['task'], j.get('attachments'), force_vision=bool(images))
        j['task_type'] = j['routing']['task_type']
        self._emit(j, 'model_selected', j['routing'])

        max_iterations = int((j.get('options') or {}).get('max_iterations') or self.max_iterations)
        feedback = None

        for attempt in range(1, max_iterations + 1):
            j['iteration'] = attempt
            j['observations'] = []

            try:
                await self._call_model(j, feedback=feedback, images=images, omitted=omitted)
            except Exception as exc:
                j['error'] = f'Model invocation failed: {exc}'
                self._emit(j, 'model_error', {'error': str(exc), 'model_id': j['routing']['model_id']})
                self._status(j, JobStatus.failed)
                return

            self._plan(j)
            self._emit(j, 'plan_created', {'steps': j['plan'], 'iteration': attempt})

            if j['routing']['task_type'] == 'general':
                # A question answers straight from the model and its retrieved
                # context -- no tools, no artifacts. It still goes through the
                # verifier rather than stamping itself passed, because otherwise
                # REQUIRE_EVIDENCE cannot apply to the one kind of task most
                # likely to answer from nothing, and 'every answer is checked'
                # would be untrue of exactly the path users spend their time on.
                j['final_answer'] = j['model_response'].get('content', str(j['model_response']))
                v = self._finish_checks(j)
                if v['passed']:
                    self._status(j, JobStatus.done)
                    self._emit(j, 'job_completed', {'final_answer': j['final_answer']})
                    return
                if attempt < max_iterations:
                    feedback = '; '.join(v.get('notes') or ['verification failed']) + \
                        ' Failed checks: ' + ', '.join(k for k, ok in v['checks'].items() if not ok)
                    self._emit(j, 'replanning', {'iteration': attempt, 'notes': v.get('notes', []), 'checks': v['checks']})
                    continue
                j['error'] = f'Verification failed after {max_iterations} attempt(s)'
                self._status(j, JobStatus.failed)
                return

            outcome = self._execute_steps(j)
            if outcome == 'paused':
                return          # resume() drives the rest
            if outcome == 'failed':
                self._status(j, JobStatus.failed)
                return

            v = self._finish_checks(j)
            if v['passed']:
                self._deliver(j)
                return

            if attempt < max_iterations:
                feedback = '; '.join(v.get('notes') or ['verification failed']) + \
                    ' Failed checks: ' + ', '.join(k for k, ok in v['checks'].items() if not ok)
                self._emit(j, 'replanning', {'iteration': attempt, 'notes': v.get('notes', []), 'checks': v['checks']})
                continue

            j['error'] = f'Verification failed after {max_iterations} attempt(s)'
            self._status(j, JobStatus.failed)
            return

    def _pipe_context(self, j):
        """Outputs from already-run steps that a later step can consume via a
        ``$name`` placeholder in its tool_args (a light data pipe over the
        otherwise static plan)."""
        ctx = {}
        for o in j.get('observations', []):
            if not isinstance(o, dict):
                continue
            if o.get('tables') is not None:
                ctx['tables'] = o['tables']
            if o.get('sheets') is not None:
                ctx['profile'] = o
            if o.get('text'):
                ctx['ocr_text'] = o['text']
        return ctx

    @staticmethod
    def _resolve_args(args, ctx):
        return {k: (ctx[v[1:]] if isinstance(v, str) and v.startswith('$') and v[1:] in ctx else v) for k, v in args.items()}

    def _execute_steps(self, j):
        for step in j['plan']:
            if step.get('status') == 'done':
                continue
            self._status(j, JobStatus.acting)
            self._emit(j, 'step_started', {'step_id': step['step_id']})

            if len(j['tool_calls']) >= self.max_tool_calls:
                j['error'] = 'MAX_TOOL_CALLS_EXCEEDED'
                return 'failed'

            step['tool_args'] = self._resolve_args(step['tool_args'], self._pipe_context(j))
            decision = self.policy.check(step['tool'], j['user_context'])
            tc = {
                'call_id': str(uuid.uuid4()),
                'tool': step['tool'],
                'risk_tier': self.policy.risks.get(step['tool'], 99),
                'policy_decision': decision.decision.value,
                'success': None,
                'result_summary': decision.reason,
            }
            j['tool_calls'].append(tc)
            self._emit(j, 'tool_started', tc)

            if decision.decision.value == 'deny':
                tc['success'] = False
                j['error'] = decision.reason
                return 'failed'

            if decision.decision.value == 'require_approval':
                j['requires_human_approval'] = True
                j['approval'] = {
                    'risk_tier': tc['risk_tier'],
                    'reason': decision.reason,
                    'pending_tool': step['tool'],
                    'pending_args': step['tool_args'],
                    'pending_step_id': step['step_id'],
                }
                self._status(j, JobStatus.awaiting_approval)
                self._emit(j, 'approval_required', j['approval'])
                return 'paused'

            try:
                result = self.tools.execute(j['job_id'], step['tool'], step['tool_args'])
            except Exception as exc:
                tc['success'] = False
                tc['result_summary'] = f'{type(exc).__name__}: {exc}'[:300]
                j['error'] = f"Tool {step['tool']} failed: {exc}"
                self._emit(j, 'tool_completed', {'call_id': tc['call_id'], 'error': str(exc)})
                return 'failed'

            tc['success'] = True
            tc['result_summary'] = str(result)[:300]
            step['status'] = 'done'
            j['observations'].append(result)
            self._emit(j, 'tool_completed', {'call_id': tc['call_id'], 'result': result})
            self._emit(j, 'step_completed', {'step_id': step['step_id']})

        return 'complete'

    def _finish_checks(self, j):
        self._status(j, JobStatus.observing)
        self._emit(j, 'observation', {'summary': 'Tool outputs collected.'})
        self._status(j, JobStatus.verifying)
        j['artifacts'] = self._artifacts(j)
        v = self.verifier.verify(j)
        j['verification'] = v
        self._emit(j, 'verification_passed' if v['passed'] else 'verification_failed', v)
        return v

    def _deliver(self, j):
        self._status(j, JobStatus.delivering)
        j['final_answer'] = self._summary(j)
        self._emit(j, 'artifact_created', {'artifacts': j['artifacts']})
        self._status(j, JobStatus.done)
        self._emit(j, 'job_completed', {'final_answer': j['final_answer']})

    def _summary(self, j):
        """A short, real paragraph for jobs that also produce a downloadable
        artifact -- the UI shows this above the artifact, not instead of it,
        so it only needs to be a gist, not the full document body."""
        content = (j.get('model_response', {}).get('content') or '').strip()
        names = ', '.join(a['name'] for a in j.get('artifacts', []) if a.get('name'))
        if not content:
            return f'Completed the requested workflow. See {names or "the artifact"} below.' if names \
                else 'Completed the requested workflow. The verified artifact is available through the artifact API.'
        # Strip fenced code blocks -- those belong in the artifact, not the summary -- then
        # take whole sentences up to ~400 chars so the cut never lands mid-word.
        text = _FENCE.sub('', content).strip()
        sentences = re.split(r'(?<=[.!?])\s+', text) if text else []
        summary = ''
        for sentence in sentences:
            candidate = f'{summary} {sentence}'.strip()
            if len(candidate) > 400 and summary:
                break
            summary = candidate
            if len(summary) > 400:
                break
        summary = summary[:400].strip() or text[:400].strip()
        if names and names.lower() not in summary.lower():
            summary = f'{summary}\n\nSee {names} below.'
        return summary or 'Completed the requested workflow. The verified artifact is available through the artifact API.'

    def _artifacts(self, j):
        out = self.workspace.root / j['job_id'] / 'output'
        mimes = {
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.pdf': 'application/pdf',
            '.md': 'text/markdown', '.py': 'text/x-python', '.json': 'application/json', '.txt': 'text/plain',
        }
        result = []
        if not out.exists():
            return result
        for p in sorted(out.rglob('*')):
            if p.is_file():
                result.append({
                    'artifact_id': str(uuid.uuid4()),
                    'name': p.name,
                    'mime_type': mimes.get(p.suffix, 'application/octet-stream'),
                    'size_bytes': p.stat().st_size,
                    'url': f"/api/v1/agent/{j['job_id']}/artifacts/{p.name}",
                })
        return result

    async def resume(self, j, approved, reviewer):
        self.store.approval(j['job_id'], approved, reviewer)
        j['approval']['reviewer_user_id'] = reviewer
        j['approval']['approved'] = approved

        if not approved:
            j['requires_human_approval'] = False
            j['error'] = 'APPROVAL_REJECTED'
            self._status(j, JobStatus.failed)
            self._emit(j, 'approval_rejected', j['approval'])
            return

        j['requires_human_approval'] = False
        self._emit(j, 'approval_approved', j['approval'])

        pending = j['approval']['pending_tool']
        args = j['approval']['pending_args']
        step_id = j['approval'].get('pending_step_id')
        self._status(j, JobStatus.acting)

        try:
            result = self.tools.execute(j['job_id'], pending, args)
        except Exception as exc:
            j['error'] = f'Tool {pending} failed: {exc}'
            self._status(j, JobStatus.failed)
            self._emit(j, 'tool_completed', {'tool': pending, 'error': str(exc)})
            return

        j['observations'].append(result)
        for step in j.get('plan', []):
            if step.get('step_id') == step_id or step.get('tool') == pending:
                step['status'] = 'done'
                break
        self._emit(j, 'tool_completed', {'tool': pending, 'result': result})

        # Finish any steps that came after the approval gate.
        outcome = self._execute_steps(j)
        if outcome == 'paused':
            return
        if outcome == 'failed':
            self._status(j, JobStatus.failed)
            return

        v = self._finish_checks(j)
        if not v['passed']:
            j['error'] = 'Verification failed'
            self._status(j, JobStatus.failed)
            return
        self._deliver(j)
