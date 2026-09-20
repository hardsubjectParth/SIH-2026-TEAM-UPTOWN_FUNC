from typing import Protocol
import httpx
import json
import os
import re


class ModelAdapter(Protocol):
    async def chat(self, messages, tools=None, **kwargs):
        ...


# Ollama only strips reasoning into the `thinking` field when `think` is enabled and
# the model supports it. Qwen3-VL ignores `think: false` and emits the tags inline
# instead, so the raw chain of thought lands in `content` and was shown to the user
# as the answer. Strip it here rather than per-caller.
_THINK_BLOCK = re.compile(r'<think>.*?</think>', re.S | re.I)
_THINK_OPEN = re.compile(r'<think>', re.I)

_CODE_HINT = re.compile(r'\b(cod(?:e|ing)|python|function|script|program|implement|algorithm|unit test)\b', re.I)
_CALC_HINT = re.compile(r'\b(calculat|comput|estimat|sizing|how many|what is the|convert)\b', re.I)


class FakeModel:
    """Deterministic stand-in used by the tests and by ``MODEL_MODE=fake``.

    It never calls a model server. The reply is shaped to the task so the whole
    pipeline -- including the coding/sandbox path -- can be exercised offline:
    a coding task gets a runnable fenced Python block, a calculation task gets a
    worked answer, everything else gets a short document body.
    """

    model = 'fake'
    url = 'fake://local'

    async def chat(self, messages, tools=None, **kwargs):
        task = ''
        for message in messages:
            if message.get('role') == 'user':
                task = str(message.get('content', ''))
        if _CODE_HINT.search(task):
            return {'content': (
                'Here is a small, self-contained solution.\n\n'
                '```python\n'
                'def add(a, b):\n'
                '    """Return the sum of two numbers."""\n'
                '    return a + b\n\n\n'
                'if __name__ == "__main__":\n'
                '    assert add(2, 3) == 5\n'
                '    print("add(2, 3) =", add(2, 3))\n'
                '```\n\n'
                'The block above defines `add` and checks it with an assertion.'
            )}
        if _CALC_HINT.search(task):
            return {'content': (
                'Worked solution:\n'
                '1. Identify the quantities given in the task.\n'
                '2. Apply the relevant formula step by step.\n'
                '3. State the result with units.\n\n'
                'Result: (deterministic stub -- run with a real local model for a real figure).'
            )}
        return {'content': 'Use the registered document tools and produce a verified artifact.'}


class OllamaAdapter:
    def __init__(self, base_url, model, keep_alive=None):
        self.base_url = base_url.rstrip('/')
        self.url = self.base_url + '/api/chat'
        self.model = model
        # How long Ollama keeps the weights resident after a call. Ollama's own
        # default is 5 minutes, which on a 17 GB local model means any gap longer
        # than that costs a full cold reload before the next answer -- so this is
        # sent per request rather than left to the server's default. OLLAMA_KEEP_ALIVE
        # on the `ollama serve` process sets the same thing, but the orchestrator
        # cannot rely on how that process was launched.
        self.keep_alive = keep_alive or os.getenv('OLLAMA_KEEP_ALIVE', '5m')
        # Qwen3 / Qwen3.5 are "thinking" models: left unchecked they emit a long
        # chain of thought before the answer, which is slow and blows the budget.
        # `think: false` disables it; `num_predict` caps the answer; both are
        # overridable per deployment.
        self.think = os.getenv('LLM_ENABLE_THINKING', 'false').lower() in {'1', 'true', 'yes'}
        self.num_ctx = int(os.getenv('OLLAMA_NUM_CTX', '8192'))
        self.num_predict = int(os.getenv('LLM_MAX_TOKENS', '1536'))
        # An explicit override wins; otherwise scale with the token budget so a
        # large LLM_MAX_TOKENS on a slow/CPU/cold-loading local model doesn't get
        # cut off by httpx mid-generation -- that surfaces as an opaque, often
        # message-less exception, not a clean "model failed" error.
        env_timeout = os.getenv('LLM_TIMEOUT_SECONDS', '').strip()
        self.default_timeout = int(env_timeout) if env_timeout else max(180, self.num_predict // 3 + 120)

    async def chat(self, messages, tools=None, **kwargs):
        num_predict = kwargs.get('num_predict', self.num_predict)
        payload = {
            'model': self.model,
            'messages': messages,
            'stream': False,
            'think': self.think,
            'keep_alive': self.keep_alive,
            'options': {
                'num_ctx': self.num_ctx,
                'num_predict': num_predict,
                'temperature': kwargs.get('temperature', 0.3),
            },
        }

        if tools:
            payload['tools'] = tools

        # Convert UUID and other non-JSON-native objects to strings
        payload = json.loads(json.dumps(payload, default=str))

        # The timeout has to follow the budget actually in play, not the one this
        # adapter was constructed with. A caller raising num_predict for a single
        # call -- the vision path does exactly that -- would otherwise keep the
        # default's shorter deadline and be cut off mid-generation.
        timeout = kwargs.get('timeout', max(self.default_timeout, num_predict // 3 + 120))
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(self.url, json=payload)
                if r.status_code == 400 and 'think' in r.text.lower():
                    # Older Ollama or a non-thinking model rejects `think`; retry without it.
                    payload.pop('think', None)
                    r = await c.post(self.url, json=payload)
                r.raise_for_status()
        except httpx.HTTPError as exc:
            # Some httpx exceptions (notably ReadTimeout with no args) stringify to
            # '', which surfaces upstream as an unhelpful "Model invocation failed: ".
            # Name the failure and the budget that was in play so it's diagnosable.
            detail = str(exc) or type(exc).__name__
            raise RuntimeError(
                f'Ollama request to {self.model} failed after {timeout}s (num_predict={payload["options"]["num_predict"]}): {detail}'
            ) from exc

        message = r.json().get('message', {})
        if not (message.get('content') or '').strip() and message.get('thinking'):
            message['content'] = message['thinking']
        message['content'] = _strip_reasoning(message.get('content') or '')
        return message


def _strip_reasoning(content):
    """Drop inline <think> reasoning, keeping the answer that follows it.

    An unterminated block means the model ran out of budget mid-thought and never
    reached an answer. There is no answer to keep, so the reasoning itself becomes
    the content -- it is the only thing the model actually produced -- but the
    stray tag goes, so it is never rendered as markup.
    """
    return _THINK_OPEN.sub('', _THINK_BLOCK.sub('', content)).strip()
