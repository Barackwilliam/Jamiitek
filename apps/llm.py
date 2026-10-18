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
    """OpenAI-style messages -> (maandishi, finish_reason). LLMError kwa kosa (na onyo kwenye /manage)."""
    try:
        result = _gemini_call(messages, max_tokens, temperature, json_mode, timeout)
    except LLMError as exc:
        _record_fail(exc)
        raise
    _record_ok()
    return result


MODEL_KEY = 'llm:gemini_model_replacement'


def _models_list():
    try:
        r = requests.get(f'{GEMINI_BASE}/models', params={'key': _gemini_key()}, timeout=10)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    return [m['name'].split('/', 1)[-1] for m in r.json().get('models', [])
            if 'generateContent' in m.get('supportedGenerationMethods', [])]


def _version(name):
    import re
    m = re.search(r'gemini-(\d+(?:\.\d+)?)', name)
    return float(m.group(1)) if m else 0.0


def replacement_models(current, error_text=''):
    """Model za kujaribu Google ikiondoa model (404): iliyopendekezwa kwenye ujumbe, kisha mpya zaidi ya familia ileile."""
    import re
    out = []
    m = re.search(r'use (?:models/)?(gemini-[\w.\-]+)', error_text or '')
    if m:
        out.append(m.group(1).rstrip('.'))
    family = 'pro' if 'pro' in current else 'flash'
    special = ('tts', 'image', 'audio', 'live', 'embedding', 'thinking', 'exp', 'lite')
    same = [n for n in _models_list() if family in n and not any(x in n for x in special)]
    same.sort(key=lambda n: ('preview' not in n, _version(n)), reverse=True)
    seen = set()
    return [n for n in out + same if not (n in seen or seen.add(n)) and n != current]


def _gemini_call(messages, max_tokens, temperature, json_mode, timeout):
    from django.conf import settings
    from django.core.cache import cache
    wanted = getattr(settings, 'GEMINI_MODEL', '') or os.getenv('GEMINI_MODEL') or DEFAULT_GEMINI
    try:
        swaps = cache.get(MODEL_KEY) or {}
    except Exception:
        swaps = {}
    model = swaps.get(wanted, wanted)
    system = '\n\n'.join(m['content'] for m in messages if m.get('role') == 'system' and m.get('content'))
    contents = [{'role': 'model' if m.get('role') == 'assistant' else 'user',
                 'parts': [{'text': str(m.get('content') or '')}]}
                for m in messages if m.get('role') != 'system']

    def post(name):
        config = {'temperature': temperature, 'maxOutputTokens': int(max_tokens or 1000)}
        if 'pro' in name:
            config['maxOutputTokens'] += 2048
        else:
            config['thinkingConfig'] = {'thinkingBudget': 0}
        if json_mode:
            config['responseMimeType'] = 'application/json'
        body = {'contents': contents or [{'role': 'user', 'parts': [{'text': ''}]}], 'generationConfig': config}
        if system:
            body['systemInstruction'] = {'parts': [{'text': system}]}
        try:
            return requests.post(f'{GEMINI_BASE}/models/{name}:generateContent',
                                 params={'key': _gemini_key()}, json=body, timeout=timeout)
        except requests.RequestException as exc:
            raise LLMError(f'gemini: {type(exc).__name__}') from exc

    r = post(model)
    tried = {model}
    for _ in range(3):   # model imeondolewa na Google -> jaribu mbadala
        if r.status_code != 404:
            break
        nxt = next((n for n in replacement_models(model, r.text) if n not in tried), None)
        if not nxt:
            break
        logger.warning('Gemini model %s haipo; najaribu %s', model, nxt)
        tried.add(nxt)
        r = post(nxt)
        if r.status_code == 200:
            try:
                cache.set(MODEL_KEY, dict(swaps, **{wanted: nxt}), timeout=7 * 24 * 3600)
            except Exception:
                pass
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


# ── Hali ya AI: onyo kwenye /manage ───────────────────────────────────
# Inahifadhiwa kwenye cache (Redis/DatabaseCache — inashirikiwa na workers wote).

HEALTH_KEY = 'llm:gemini_health'


def reason(exc):
    """Sababu fupi, inayoeleweka, ya Gemini kushindwa (bila key wala data nyeti)."""
    import re
    text = str(exc)
    low = text.lower()
    m = re.search(r'HTTP (\d{3})', text)
    code = int(m.group(1)) if m else 0
    if code == 429 or 'resource_exhausted' in low or 'quota' in low:
        return 'Kikomo cha bure kimeisha kwa sasa (429)'
    if code in (401, 403) or 'api key' in low or 'api_key' in low:
        return 'GEMINI_API_KEY haikubaliki — angalia Render → Environment'
    if code >= 500:
        return f'Seva za Google zina tatizo kwa sasa ({code})'
    if 'timeout' in low:
        return 'Muda umeisha — Gemini haikujibu'
    if 'connection' in low:
        return 'Mtandao — imeshindwa kuifikia Gemini'
    return text[:200]


def _record_fail(exc):
    from django.core.cache import cache
    from django.utils import timezone
    try:
        now = timezone.now()
        today = timezone.localdate().isoformat()
        old = cache.get(HEALTH_KEY) or {}
        count = old.get('count', 0) + 1 if old.get('day') == today else 1
        cache.set(HEALTH_KEY, {'at': now.isoformat(), 'reason': reason(exc), 'day': today, 'count': count},
                  timeout=24 * 3600)
    except Exception:   # onyo ni taarifa tu — lisizuie uandishi
        logger.exception('llm health record failed')


def _record_ok():
    from django.core.cache import cache
    try:
        if cache.get(HEALTH_KEY):
            cache.delete(HEALTH_KEY)
    except Exception:
        logger.exception('llm health record failed')


def health():
    """None kama Gemini iko sawa; vinginevyo {'level': 'fallback'|'down', 'title', 'reason', 'at', 'count'}."""
    from datetime import datetime
    from django.core.cache import cache
    groq_ok = bool(_groq_key())
    if not any_key():
        return {'level': 'down', 'title': 'Hakuna AI iliyowekwa — AI haiwezi kuandika',
                'reason': 'Weka GEMINI_API_KEY (na GROQ_API_KEY ya akiba) kwenye Render → Environment.',
                'at': None, 'count': 0}
    if os.getenv('AI_PROVIDER', 'gemini').lower() == 'groq':
        return None   # Groq imechaguliwa makusudi
    if not _gemini_key():
        return {'level': 'fallback', 'title': 'Gemini haijawekwa — Groq ndiyo inaandika',
                'reason': 'GEMINI_API_KEY haipo kwenye Render → Environment.', 'at': None, 'count': 0}
    try:
        state = cache.get(HEALTH_KEY)
    except Exception:
        state = None
    if not state:
        return None
    try:
        at = datetime.fromisoformat(state['at'])
    except (KeyError, ValueError):
        at = None
    from django.utils import timezone
    count = state.get('count', 0) if state.get('day') == timezone.localdate().isoformat() else 0
    return {'level': 'fallback' if groq_ok else 'down',
            'title': 'Gemini imeshindwa — Groq ndiyo inaandika kwa sasa' if groq_ok
                     else 'Gemini imeshindwa na hakuna Groq ya akiba — AI haiandiki',
            'reason': state.get('reason', ''), 'at': at, 'count': count}


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
