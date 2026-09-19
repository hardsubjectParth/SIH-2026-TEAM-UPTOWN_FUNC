
import re
import yaml
from pathlib import Path

# Task classification is deterministic and ordered: the first pattern that matches
# wins. Order matters -- coding and multimodal are checked before the broader
# document/general buckets so "summarise the scanned drawing" routes to vision,
# not to the document workflow.
_PATTERNS = [
    ('coding', re.compile(r'\b(code|coding|python|javascript|typescript|golang|rust|function|program|programme|script|algorithm|refactor|debug|compile)\b|\bunit tests?\b', re.I)),
    ('multimodal', re.compile(r'\b(images?|scans?|scanned|drawings?|photos?|photograph|pictures?|figure|diagram|p&id|pid|ocr|handwritten|blueprint|screenshot)\b', re.I)),
    ('presentation', re.compile(r'\b(presentation|slides?|slide deck|deck|powerpoint|pptx)\b|\.ppt', re.I)),
    ('spreadsheet', re.compile(r'\b(spreadsheet|excel|xlsx|xlsm|workbook)\b|\bpivot table\b|\btabular\b', re.I)),
    ('calculation', re.compile(r'\bcalculat(?:e|es|ed|ing|ion|ions|or)\b|\bcomput(?:e|es|ed|ing|ation|ational)\b|\bestimat(?:e|es|ed|ing|ion)\b|\bsizing\b|\bload factor\b|\bflow rate\b|\bpressure drop\b|\bhow many\b|\bconvert\b.+\bto\b', re.I)),
    ('document_workflow', re.compile(r'\b(document|approval|reports?|inspection|docx|pdf|word file|artifact|summar\w*|memo|notes?|letter|minutes|briefing)\b', re.I)),
]

# task_type -> the model capability that should serve it.
_CAPABILITY = {
    'coding': 'coding',
    'multimodal': 'vision',
    'presentation': 'document',
    'spreadsheet': 'document',
    'calculation': 'reasoning',
    'document_workflow': 'document',
    'general': 'reasoning',
}

# Preferred registry id per capability; falls back to any enabled model that
# advertises the capability, then to the first enabled model.
_PREFERRED = {
    'coding': 'qwen-coder',
    'vision': 'qwen-vision',
    'document': 'qwen-quality',
    'reasoning': 'qwen-reasoning',
}

# Attachments a local vision model can actually look at. Anything else (PDF,
# DOCX, XLSX) is already turned into text by the RAG extractor before it
# reaches the model, so it needs no vision capability.
_IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp', '.gif'}


def is_image_attachment(attachment):
    if not isinstance(attachment, dict):
        return False
    if str(attachment.get('mime_type') or '').lower().startswith('image/'):
        return True
    return Path(str(attachment.get('name') or '')).suffix.lower() in _IMAGE_SUFFIXES


def has_image_attachments(attachments):
    return any(is_image_attachment(item) for item in attachments or [])


class ModelRouter:
    def __init__(self, path='config/models.yaml'):
        data = yaml.safe_load(Path(path).read_text()) if Path(path).exists() else {'models': []}
        self.models = data.get('models', [])

    def classify(self, task):
        for task_type, pattern in _PATTERNS:
            if pattern.search(task or ''):
                return task_type
        return 'general'

    def _enabled(self):
        return [m for m in self.models if m.get('enabled') and 'embedding' not in m.get('capabilities', [])]

    def route(self, task, attachments=None):
        task_type = self.classify(task)
        capability = _CAPABILITY[task_type]

        # An attached image decides how the model must be *invoked*, and the task
        # text decides what gets *produced*, so these are routed separately. The
        # wording of a question about a picture usually contains no visual
        # keyword at all -- "give the dimensions for this" classifies as
        # `general` -- and routing on text alone therefore sent drawings and
        # photos to a text-only model, which answered from the (often garbled)
        # OCR line instead of from the image. Overriding only the capability
        # keeps the task type, plan and deliverable intact: a "save this as
        # pptx" with a drawing attached still produces a deck, but the model
        # building it can see the drawing.
        requires_vision = has_image_attachments(attachments)
        if requires_vision:
            capability = 'vision'

        preferred = _PREFERRED.get(capability)

        enabled = self._enabled()
        model = next((m for m in enabled if m['id'] == preferred), None)
        if model is None:
            model = next((m for m in enabled if capability in m.get('capabilities', [])), None)
        if model is None:
            model = enabled[0] if enabled else {'id': 'fake-model', 'provider': 'fake', 'model': 'fake', 'capabilities': []}

        exact = model['id'] == preferred or capability in model.get('capabilities', [])
        if exact and requires_vision:
            reason = (
                f'Classified as {task_type}; an attached image requires vision, '
                f'matched capability "vision" to model "{model["id"]}".'
            )
        elif exact:
            reason = f'Classified as {task_type}; matched capability "{capability}" to model "{model["id"]}".'
        elif requires_vision:
            reason = (
                f'Classified as {task_type}; an attached image requires vision, but no enabled '
                f'model advertises "vision" -- fell back to "{model["id"]}", which cannot see it.'
            )
        else:
            reason = f'Classified as {task_type}; no model advertises "{capability}", fell back to "{model["id"]}".'

        return {
            'task_type': task_type,
            'model_id': model['id'],
            'model_name': model.get('model'),
            'provider': model.get('provider', 'fake'),
            'tier': model.get('tier', 'default'),
            'capability': capability,
            'requires_vision': requires_vision,
            'confidence': (0.96 if exact else 0.7) - (0.1 if task_type == 'multimodal' else 0.0),
            'reason': reason,
            'fallback_model_id': next((m['id'] for m in enabled if m['id'] != model['id']), None),
        }
