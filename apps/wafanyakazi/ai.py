"""
AI ya timu — Groq.

Kanuni: AI inaandika tu (rasimu, muhtasari). Kugundua kazi ni code ya kawaida,
kwa hiyo AI ikikosekana timu bado inafanya kazi — inatumia maandishi ya kawaida.

`write()` haitupi exception kamwe: inarudisha '' na mfanyakazi anatumia
template yake. Kila mzunguko una kikomo cha maombi (BUDGET) ili Groq ya bure
isizime JamiiBot za wateja.
"""
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CHAT_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODELS_URL = 'https://api.groq.com/openai/v1/models'
PREFERRED = (
    'openai/gpt-oss-120b',
    'llama-3.3-70b-versatile',
    'moonshotai/kimi-k2-instruct-0905',
    'meta-llama/llama-4-maverick-17b-128e-instruct',
    'openai/gpt-oss-20b',
    'llama-3.1-8b-instant',
)
NOT_CHAT = ('whisper', 'guard', 'tts', 'playai', 'orpheus', 'compound', 'distil')

BUDGET = 12
_state = {'left': BUDGET, 'model': None, 'written': [], 'failed': 0}


def reset_budget(n=BUDGET):
    _state['left'] = n
    _state['written'] = []
    _state['failed'] = 0


def written():
    """Maandishi yaliyotoka kwa AI tangu reset_budget — kwa mtihani wa umahiri."""
    return list(_state['written'])


def failures():
    return _state['failed']


def _key():
    return getattr(settings, 'GROQ_API_KEY', '') or os.getenv('GROQ_API_KEY', '')


def _headers():
    return {'Authorization': f'Bearer {_key()}', 'Content-Type': 'application/json'}


def _pick_replacement(current):
    try:
        r = requests.get(MODELS_URL, headers=_headers(), timeout=10)
        ids = [m['id'] for m in r.json().get('data', [])
               if m.get('active', True) and not any(w in m['id'] for w in NOT_CHAT)]
    except Exception:
        return None
    for name in PREFERRED:
        if name in ids and name != current:
            return name
    return next((i for i in ids if i != current), None)


def write(system, prompt, max_tokens=500, temperature=0.5):
    """Rudisha jibu la AI, au '' (hakuna key, kikomo kimefika, au hitilafu)."""
    from apps import llm
    if not (_key() or llm.gemini_first()) or _state['left'] <= 0:
        return ''
    _state['left'] -= 1
    model = _state['model'] or os.getenv('GROQ_MODEL') or PREFERRED[0]

    def post(name):
        return requests.post(CHAT_URL, headers=_headers(), timeout=25, json={
            'model': name,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens,
            'temperature': temperature,
        })

    try:
        # Gemini kwanza (Kiswahili bora); ikishindwa, Groq kama awali
        r = llm.gemini_response({'messages': [{'role': 'system', 'content': system},
                                              {'role': 'user', 'content': prompt}],
                                 'max_tokens': max_tokens, 'temperature': temperature})
        if r is None and not _key():
            _state['failed'] += 1
            return ''
        r = r or post(model)
        if r.status_code == 404 and 'model_not_found' in r.text:
            replacement = _pick_replacement(model)
            if replacement:
                logger.warning('[wafanyakazi] model %s haipo; natumia %s', model, replacement)
                _state['model'] = model = replacement
                r = post(model)
        if r.status_code != 200:
            logger.warning('[wafanyakazi] groq %s: %s', r.status_code, r.text[:200])
            _state['failed'] += 1
            return ''
        text = (r.json()['choices'][0]['message']['content'] or '').strip()
        if text:
            _state['written'].append(text)
        return text
    except Exception as exc:
        logger.warning('[wafanyakazi] groq: %s', type(exc).__name__)
        _state['failed'] += 1
        return ''


def persona(name, role):
    return (
        f"Wewe ni {name}, {role} wa JamiiTek — kampuni ya kidijitali ya Dar es Salaam "
        "inayotengeneza tovuti, web builder, JamiiBot (chatbot ya WhatsApp), templates za "
        "tovuti, hosting na domain. Andika kwa Kiswahili fasaha, kwa heshima na kwa ufupi. "
        "Usibuni bei, tarehe wala ahadi ambazo hazijatolewa kwako. Usiweke salamu ya "
        "kufunga wala sahihi — itaongezwa yenyewe."
    )
