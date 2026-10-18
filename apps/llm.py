"""
AI ya uandishi kwa mfumo mzima wa JamiiTek: Gemini kwanza, Groq akiba.

Gemini (Google) inaandika Kiswahili vizuri zaidi. Sehemu zote zinazoandika
(blog, habari, spotlight, proposals, mikataba, profile/ankara, hosting, digest,
wafanyakazi, rasimu za JamiiBot knowledge, builder) zinapita hapa kupitia
"shims" mbili zinazoiga kiolesura cha Groq walichotumia awali — kwa hiyo kila
faili linabadilika mstari mmoja tu:

    client = llm.client()          # badala ya Groq(api_key=key)
    client.chat.completions.create(model=..., messages=[...], ...)

    r = llm.post(GROQ_URL, headers=..., json=payload, timeout=25)   # badala ya requests.post
    r.status_code, r.json()['choices'][0]['message']['content']

Gemini ikishindwa (kikomo cha bure, mtandao, key haipo) ombi lilelile linaenda
Groq kama zamani. Kuzima Gemini bila deploy: AI_PROVIDER=groq kwenye Render.

Majibu ya JamiiBot kwa wateja (chatbot/ai_engine) na sauti (transcribe) HAYAPITI
hapa — yanabaki Groq (kasi, na model ya kila bot).
"""
import json as _json
import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'
DEFAULT_GEMINI = 'gemini-2.5-flash'


class LLMError(Exception):
    pass


def _gemini_key():
    from django.conf import settings
    return getattr(settings, 'GEMINI_API_KEY', '') or os.getenv('GEMINI_API_KEY', '')


def _groq_key():
    from django.conf import settings
    return getattr(settings, 'GROQ_API_KEY', '') or os.getenv('GROQ_API_KEY', '')


def gemini_first():
    return bool(_gemini_key()) and os.getenv('AI_PROVIDER', 'gemini').lower() != 'groq'


def any_key():
    return bool(_gemini_key() or _groq_key())


# ── Gemini ──────────────────────────────────────────────────────────

def gemini_chat(messages, max_tokens=1000, temperature=0.5, json_mode=False, timeout=60):
    """OpenAI-style messages -> (maandishi, finish_reason). LLMError kwa kosa."""
    from django.conf import settings
    model = getattr(settings, 'GEMINI_MODEL', '') or os.getenv('GEMINI_MODEL') or DEFAULT_GEMINI
    system = '\n\n'.join(m['content'] for m in messages if m.get('role') == 'system' and m.get('content'))
    contents = [{'role': 'model' if m.get('role') == 'assistant' else 'user',
                 'parts': [{'text': str(m.get('content') or '')}]}
                for m in messages if m.get('role') != 'system']
    config = {'temperature': temperature, 'maxOutputTokens': int(max_tokens or 1000)}
    if 'pro' in model:
        config['maxOutputTokens'] += 2048
    else:
        config['thinkingConfig'] = {'thinkingBudget': 0}
    if json_mode:
        config['responseMimeType'] = 'application/json'
    body = {'contents': contents or [{'role': 'user', 'parts': [{'text': ''}]}], 'generationConfig': config}
    if system:
        body['systemInstruction'] = {'parts': [{'text': system}]}
    try:
        r = requests.post(f'{GEMINI_BASE}/models/{model}:generateContent',
                          params={'key': _gemini_key()}, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise LLMError(f'gemini: {type(exc).__name__}') from exc
    if r.status_code != 200:
        raise LLMError(f'gemini HTTP {r.status_code}: {r.text[:200]}')
    data = r.json()
    cands = data.get('candidates') or []
    if not cands:
        raise LLMError(f"gemini: {(data.get('promptFeedback') or {}).get('blockReason', 'no candidates')}")
    parts = (cands[0].get('content') or {}).get('parts') or []
    text = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
    finish = {'MAX_TOKENS': 'length', 'STOP': 'stop'}.get(cands[0].get('finishReason', ''), 'stop')
    if not text:
        raise LLMError(f"gemini empty ({cands[0].get('finishReason', '?')})")
    return text, finish


# ── Shim 1: kiolesura cha Groq SDK ──────────────────────────────────

class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _completion(text, finish, model):
    message = _Obj(content=text, role='assistant')
    return _Obj(choices=[_Obj(message=message, finish_reason=finish, index=0)],
                model=model, usage=_Obj(prompt_tokens=0, completion_tokens=0, total_tokens=0))


class _Completions:
    def create(self, model=None, messages=None, max_tokens=None, temperature=0.5,
               response_format=None, timeout=None, **kwargs):
        messages = messages or []
        if gemini_first():
            try:
                json_mode = bool(response_format and response_format.get('type') == 'json_object')
                text, finish = gemini_chat(messages, max_tokens or 1000, temperature,
                                           json_mode=json_mode, timeout=max(timeout or 60, 45))
                return _completion(text, finish, 'gemini')
            except LLMError as exc:
                logger.warning('Gemini imeshindwa (%s) — natumia Groq', exc)
        if not _groq_key():
            raise LLMError('Gemini imeshindwa na GROQ_API_KEY haipo')
        from groq import Groq
        params = dict(model=model, messages=messages, temperature=temperature, **kwargs)
        if max_tokens is not None:
            params['max_tokens'] = max_tokens
        if response_format is not None:
            params['response_format'] = response_format
        if timeout is not None:
            params['timeout'] = timeout
        return Groq(api_key=_groq_key()).chat.completions.create(**params)


class _Client:
    def __init__(self):
        self.chat = _Obj(completions=_Completions())


def client():
    """Badala ya Groq(api_key=key). None kama hakuna key yoyote."""
    return _Client() if any_key() else None


# ── Shim 2: requests.post kwenda Groq ───────────────────────────────

class _Response:
    def __init__(self, text, model):
        self.status_code = 200
        self._body = {'choices': [{'message': {'role': 'assistant', 'content': text},
                                   'finish_reason': 'stop', 'index': 0}], 'model': model}
        self.text = _json.dumps(self._body)

    def json(self):
        return self._body


def gemini_response(payload, timeout=45):
    """Jibu la Gemini lenye umbo la jibu la Groq (status 200), au None — basi anayeita aende Groq.

        r = llm.gemini_response(payload) or requests.post(GROQ_URL, ...)
    """
    if not (gemini_first() and payload.get('messages')):
        return None
    try:
        fmt = payload.get('response_format') or {}
        text, _ = gemini_chat(payload['messages'], payload.get('max_tokens') or 1000,
                              payload.get('temperature', 0.5),
                              json_mode=fmt.get('type') == 'json_object', timeout=max(timeout or 45, 45))
        return _Response(text, 'gemini')
    except LLMError as exc:
        logger.warning('Gemini imeshindwa (%s) — natumia Groq', exc)
        return None


def post(url, headers=None, json=None, timeout=30, **kwargs):
    """Badala ya requests.post(GROQ_URL, ...). Gemini kwanza; ikishindwa, ombi asili linaenda Groq."""
    payload = json or {}
    if gemini_first() and payload.get('messages'):
        try:
            fmt = payload.get('response_format') or {}
            text, _ = gemini_chat(payload['messages'], payload.get('max_tokens') or 1000,
                                  payload.get('temperature', 0.5),
                                  json_mode=fmt.get('type') == 'json_object', timeout=max(timeout or 30, 45))
            return _Response(text, 'gemini')
        except LLMError as exc:
            logger.warning('Gemini imeshindwa (%s) — natumia Groq', exc)
    if not _groq_key():
        r = requests.models.Response()
        r.status_code, r._content = 503, b'{"error": "no AI key"}'
        return r
    headers = dict(headers or {})
    headers['Authorization'] = f'Bearer {_groq_key()}'
    return requests.post(url, headers=headers, json=payload, timeout=timeout, **kwargs)
