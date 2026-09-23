import csv
import json
import os
import re
import sqlite3
import smtplib
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path
from docx import Document
from openpyxl import Workbook, load_workbook
from sqlalchemy import text

from app.rag.report import write_knowledge_transfer_report
from app.tools.sandbox import run_script

DEFAULT_TOOL_IDENTITY = {'role': 'lower', 'tenant_id': 'default', 'user_id': 'tool-user'}


_EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
_PHONE = re.compile(r'(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)')


def _redact_text(content):
    """``(redacted text, count)`` -- the patterns both file types share."""
    count = len(_EMAIL.findall(content))
    content = _EMAIL.sub('[REDACTED_EMAIL]', content)
    count += len(_PHONE.findall(content))
    return _PHONE.sub('[REDACTED_PHONE]', content), count


def _redact_docx(path, output):
    """Redact a .docx into a real .docx, rather than through its raw bytes.

    Reading a .docx with read_text() gets the bytes of a zip archive, so the
    regexes match almost nothing and the file written back is a corrupt archive
    carrying the original personal data intact -- a redaction tool that returns
    an unopenable document and redacts nothing is worse than one that refuses.

    Runs are the unit of replacement because Word splits a paragraph across them
    at every formatting change, which routinely cuts an address in half. Each
    paragraph is redacted as a whole string, then written into its first run
    with the rest cleared, so a match spanning a boundary is still caught. The
    cost is that mixed formatting within a redacted paragraph collapses to the
    formatting of its first run; for a sanitised copy that is an acceptable
    trade, and it is the only way to catch split matches without rebuilding the
    paragraph's run structure.
    """
    document = Document(str(path))
    total = 0

    def redact_paragraphs(paragraphs):
        nonlocal total
        for paragraph in paragraphs:
            if not paragraph.runs:
                continue
            redacted, count = _redact_text(paragraph.text)
            if not count:
                continue
            total += count
            paragraph.runs[0].text = redacted
            for run in paragraph.runs[1:]:
                run.text = ''

    redact_paragraphs(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                redact_paragraphs(cell.paragraphs)
    for section in document.sections:
        redact_paragraphs(section.header.paragraphs)
        redact_paragraphs(section.footer.paragraphs)

    document.save(str(output))
    return total


class ToolRegistry:
    def __init__(self, workspace, rag=None):
        self.workspace = workspace
        self.rag = rag

    def names(self):
        return [
            'search_documents',
            'read_file',
            'write_file',
            'generate_docx',
            'ingest_document',
            'list_sources',
            'export_report',
            'spreadsheet_profile',
            'redact_pii',
            'extract_tables',
            'ocr_document',
            'search_db',
            'send_email',
            'create_calendar_event',
            'run_python',
            'generate_xlsx',
            'generate_pptx',
            'generate_pdf',
        ]

    def execute(self, jid, name, args):
        if name == 'search_documents':
            q = args.get('query', '').lower()
            if self.rag:
                identity = args.get('identity') or DEFAULT_TOOL_IDENTITY
                hits = self.rag.search_sync(q, identity, args.get('top_k', 5), args.get('metadata'), args.get('file_ids'))
                return {
                    'hits': hits,
                    'count': len(hits),
                    'sources': [{'name': hit['source'], 'source': hit['source']} for hit in hits],
                }
            hits = []

            input_root = self.workspace.root / jid / 'input'

            if input_root.exists():
                for p in input_root.rglob('*'):
                    if (
                        p.is_file()
                        and p.suffix.lower() in {'.txt', '.md'}
                    ):
                        t = p.read_text(errors='ignore')

                        if q in t.lower() or not q:
                            hits.append({
                                'name': p.name,
                                'snippet': t[:500],
                                'source': str(
                                    p.relative_to(
                                        self.workspace.root / jid
                                    )
                                ),
                            })

            return {
                'hits': hits,
                'count': len(hits),
                'sources': [
                    {
                        'name': h['name'],
                        'source': h['source'],
                    }
                    for h in hits
                ],
            }

        if name == 'ingest_document':
            if not self.rag:
                raise ValueError('RAG_NOT_CONFIGURED')
            identity = args.get('identity') or DEFAULT_TOOL_IDENTITY
            path = self.workspace.safe(jid, args['path'])
            return self.rag.ingest_sync(path, identity, args.get('scope'), {'job_id': jid, **(args.get('metadata') or {})})

        if name == 'list_sources':
            if not self.rag:
                raise ValueError('RAG_NOT_CONFIGURED')
            identity = args.get('identity') or DEFAULT_TOOL_IDENTITY
            return {'sources': self.rag.list_sources(identity)}

        if name == 'export_report':
            paths = [self.workspace.safe(jid, value) for value in args.get('paths', [])]
            if not paths:
                paths = [path for path in (self.workspace.root / jid / 'input').rglob('*') if path.is_file()]
            result = write_knowledge_transfer_report(paths, self.workspace.safe(jid, 'output', True), self.rag.extract if self.rag else lambda path: path.read_text(errors='ignore'))
            return {'path': str(Path(result['docx']).relative_to(self.workspace.root / jid)), 'json_path': str(Path(result['json']).relative_to(self.workspace.root / jid)), 'sources': len(paths)}

        if name == 'spreadsheet_profile':
            path = self.workspace.safe(jid, args['path'])
            workbook = load_workbook(path, read_only=True, data_only=True)
            sheets = []
            for sheet in workbook.worksheets:
                rows = list(sheet.iter_rows(min_row=1, max_row=2, values_only=True))
                sheets.append({'name': sheet.title, 'rows': max(sheet.max_row - 1, 0), 'columns': sheet.max_column, 'headers': [str(value) if value is not None else '' for value in rows[0]] if rows else []})
            return {'file': path.name, 'sheets': sheets}

        if name == 'redact_pii':
            path = self.workspace.safe(jid, args['path'])
            output = self.workspace.safe(jid, args.get('output', f'working/{path.stem}_redacted{path.suffix}'), True)
            if path.suffix.lower() == '.docx':
                redactions = _redact_docx(path, output)
            else:
                content = path.read_text(errors='ignore')
                content, redactions = _redact_text(content)
                output.write_text(content, encoding='utf-8')
            return {'path': str(output.relative_to(self.workspace.root / jid)), 'redactions': redactions}

        if name == 'extract_tables':
            path = self.workspace.safe(jid, args['path'])
            tables = []
            if path.suffix.lower() in {'.xlsx', '.xlsm'}:
                workbook = load_workbook(path, read_only=True, data_only=True)
                for sheet in workbook.worksheets:
                    tables.append({'name': sheet.title, 'rows': [[value for value in row] for row in sheet.iter_rows(values_only=True)]})
            elif path.suffix.lower() == '.csv':
                with path.open(newline='', encoding='utf-8-sig', errors='ignore') as stream:
                    tables.append({'name': path.stem, 'rows': list(csv.reader(stream))})
            elif path.suffix.lower() == '.docx':
                document = Document(path)
                for index, table in enumerate(document.tables, 1):
                    tables.append({'name': f'table_{index}', 'rows': [[cell.text for cell in row.cells] for row in table.rows]})
            else:
                raise ValueError('UNSUPPORTED_TABLE_DOCUMENT')
            return {'file': path.name, 'tables': tables}

        if name == 'ocr_document':
            if not self.rag:
                raise ValueError('RAG_NOT_CONFIGURED')
            path = self.workspace.safe(jid, args['path'])
            return {'file': path.name, 'text': self.rag.extract(path)}

        if name == 'search_db':
            if not self.rag:
                raise ValueError('DATABASE_NOT_CONFIGURED')
            identity = args.get('identity') or DEFAULT_TOOL_IDENTITY
            # Raw SQL only ever runs against the caller's own tier database, never a merged
            # cross-tier read, so a crafted query cannot pull rows from a higher tier.
            own_tier = identity.get('role') if identity.get('role') in self.rag.services else 'lower'
            query = args.get('query', '').strip()
            if not re.match(r'^(SELECT|WITH)\b', query, re.IGNORECASE) or ';' in query:
                raise ValueError('READ_ONLY_SELECT_REQUIRED')
            tables = set(re.findall(r'\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)', query, re.IGNORECASE))
            if not tables.issubset({'rag_documents', 'rag_chunks'}):
                raise ValueError('DATABASE_TABLE_NOT_ALLOWED')
            with self.rag.service_for(own_tier).engine.connect() as db:
                result = db.execute(text(query), args.get('params') or {})
                return {'columns': list(result.keys()), 'rows': [list(row) for row in result.fetchmany(int(args.get('limit', 100)))]}

        if name in {'send_email', 'create_calendar_event'}:
            if name == 'send_email':
                smtp_host = os.getenv('SMTP_HOST', '').strip()
                if not smtp_host:
                    raise ValueError('SMTP_NOT_CONFIGURED')
                message = EmailMessage()
                message['From'] = os.getenv('SMTP_FROM', 'orchestrator@localhost')
                message['To'] = args['to']
                message['Subject'] = args.get('subject', '')
                message.set_content(args.get('body', ''))
                with smtplib.SMTP(smtp_host, int(os.getenv('SMTP_PORT', '25')), timeout=15) as client:
                    client.send_message(message)
                return {'status': 'sent', 'external_delivery': True, 'to': args['to']}
            outbox = self.workspace.safe(jid, 'output/outbox', True)
            outbox.mkdir(parents=True, exist_ok=True)
            payload = {'tool': name, 'status': 'local_event', 'created_at': datetime.now().isoformat(), 'request': args}
            target = outbox / f'{name}_{datetime.now().strftime("%Y%m%d%H%M%S%f")}.json'
            target.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
            return {'status': 'local_event', 'path': str(target.relative_to(self.workspace.root / jid)), 'external_delivery': False}

        if name == 'run_python':
            target = self.workspace.safe(jid, args['path'])
            if target.suffix != '.py':
                raise ValueError('RUN_PYTHON_EXPECTS_PY_FILE')
            if not target.exists():
                raise ValueError('RUN_PYTHON_TARGET_MISSING')
            run_dir = self.workspace.safe(jid, 'working/sandbox', True)
            return run_script(target, run_dir, timeout=args.get('timeout', 15))

        if name == 'generate_xlsx':
            p = self.workspace.safe(jid, 'output/' + args.get('filename', 'analysis.xlsx'), True)
            workbook = Workbook()
            summary_sheet = workbook.active
            summary_sheet.title = 'Summary'
            summary_sheet['A1'] = 'Task summary'
            for row, line in enumerate((args.get('summary') or 'No summary produced.').splitlines() or ['No summary produced.'], start=2):
                summary_sheet.cell(row=row, column=1, value=line)
            for index, table in enumerate(args.get('tables') or [], start=1):
                sheet = workbook.create_sheet(title=(table.get('name') or f'Table {index}')[:31])
                for r_index, row in enumerate(table.get('rows') or [], start=1):
                    for c_index, value in enumerate(row, start=1):
                        sheet.cell(row=r_index, column=c_index, value=value if value is None or isinstance(value, (str, int, float)) else str(value))
            meta = workbook.create_sheet(title='Provenance')
            meta['A1'] = 'Source'
            meta['B1'] = args.get('source', 'n/a')
            meta['A2'] = 'Generated by'
            meta['B2'] = 'Sovereign Agent Orchestrator (local)'
            workbook.save(p)
            return {'path': str(p.relative_to(self.workspace.root / jid)), 'name': p.name,
                    'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}

        if name == 'generate_pptx':
            from pptx import Presentation
            from pptx.util import Inches, Pt
            p = self.workspace.safe(jid, 'output/' + args.get('filename', 'briefing_deck.pptx'), True)
            presentation = Presentation()
            title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
            title_slide.shapes.title.text = args.get('title', 'Briefing')
            if len(title_slide.placeholders) > 1:
                title_slide.placeholders[1].text = 'Generated locally by the Sovereign Agent Orchestrator'

            def _add(heading, text):
                slide = presentation.slides.add_slide(presentation.slide_layouts[1])
                slide.shapes.title.text = heading
                body = slide.placeholders[1].text_frame
                body.word_wrap = True
                lines = [ln.strip() for ln in (text or '').splitlines() if ln.strip()] or ['(no content)']
                body.text = lines[0][:400]
                for line in lines[1:12]:
                    para = body.add_paragraph()
                    para.text = line[:400]
                    para.font.size = Pt(16)

            blocks = re.split(r'\n\s*\n', (args.get('body') or '').strip())
            for index, block in enumerate([b for b in blocks if b.strip()][:8], start=1):
                first, _, rest = block.partition('\n')
                _add(first.strip(':').strip()[:80] or f'Point {index}', rest or first)
            if args.get('evidence'):
                _add('Evidence Used', args['evidence'])
            if args.get('provenance'):
                _add('Provenance', args['provenance'])
            presentation.save(p)
            return {'path': str(p.relative_to(self.workspace.root / jid)), 'name': p.name,
                    'mime_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}

        if name == 'read_file':
            return {
                'text': self.workspace.safe(
                    jid,
                    args['path']
                ).read_text(errors='ignore')
            }

        if name == 'write_file':
            p = self.workspace.safe(
                jid,
                args['path'],
                True
            )

            p.write_text(
                args.get('content', '')
            )

            return {
                'path': str(
                    p.relative_to(
                        self.workspace.root / jid
                    )
                )
            }

        if name == 'generate_docx':
            p = self.workspace.safe(
                jid,
                'output/' + args.get(
                    'filename',
                    'approval_note.docx'
                ),
                True
            )

            d = Document()

            d.add_heading(
                args.get(
                    'title',
                    'Approval Note'
                ),
                0
            )

            for s in args.get('sections', []):
                d.add_heading(
                    s.get(
                        'heading',
                        'Section'
                    ),
                    1
                )

                d.add_paragraph(
                    s.get(
                        'body',
                        ''
                    )
                )

            citations = args.get('citations', [])

            if citations:
                d.add_heading(
                    'References',
                    1
                )

                for citation in citations:
                    d.add_paragraph(
                        str(citation)
                    )

            d.save(p)

            return {
                'path': str(
                    p.relative_to(
                        self.workspace.root / jid
                    )
                ),
                'name': p.name,
                'mime_type': (
                    'application/vnd.openxmlformats-officedocument'
                    '.wordprocessingml.document'
                ),
                'citations': citations,
            }

        if name == 'generate_pdf':
            # A plain, paginated text PDF -- same call shape as generate_docx (title,
            # sections, citations) so callers can ask for either format from one plan.
            # pymupdf is already a dependency (used for OCR page rendering) and its
            # built-in "helv" base font needs no external font files, so this stays
            # fully offline.
            import pymupdf
            p = self.workspace.safe(jid, 'output/' + args.get('filename', 'report.pdf'), True)
            title = args.get('title', 'Report')
            parts = [title, '=' * len(title), '']
            for section in args.get('sections', []):
                heading = section.get('heading', 'Section')
                parts += [heading, '-' * len(heading), section.get('body', ''), '']
            citations = args.get('citations', [])
            if citations:
                parts += ['References', '-' * len('References'), *[str(c) for c in citations]]
            full_text = '\n'.join(parts)
            doc = pymupdf.open()
            rect = pymupdf.Rect(50, 50, 545, 792)
            # Conservative chars-per-page budget for 10pt text in the rect above --
            # sized to stay well under what actually fits, not measured precisely.
            chars_per_page = 3200
            chunks = [full_text[i:i + chars_per_page] for i in range(0, len(full_text), chars_per_page)] or ['']
            for chunk in chunks:
                page = doc.new_page(width=612, height=792)
                page.insert_textbox(rect, chunk, fontsize=10, fontname='helv')
            doc.save(p)
            doc.close()
            return {
                'path': str(p.relative_to(self.workspace.root / jid)),
                'name': p.name,
                'mime_type': 'application/pdf',
                'citations': citations,
            }

        raise ValueError('UNKNOWN_TOOL')
