"""
Muhtasari wa asubuhi.

MSINGI: AI haifanyi ugunduzi. Code inakusanya ukweli, AI inaupanga kwa
lugha nzuri. Groq ikizimika, muhtasari wa kawaida unatumwa — hakuna
kinachopotea.

Inatuma DELTAS pekee: kilichobadilika tangu jana, si hali ya kila kitu.
Ukipokea ujumbe uleule kila siku, utaacha kuusoma.
"""
import logging
import os
from datetime import timedelta

from django.utils import timezone

from . import alerts as alert_engine
from .integrations import base
from .live_config import live_config
from .models import IntegrationSnapshot, ManagedWebsite
from .notify import notify

logger = logging.getLogger(__name__)

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

SYSTEM = (
    'Wewe ni msaidizi wa JamiiTek, kampuni ya Tanzania inayotengeneza na '
    'kusimamia tovuti. Andika muhtasari MFUPI wa asubuhi kwa Kiswahili kwa '
    'mmiliki. Anza na kinachohitaji hatua leo. Usirudie takwimu zote — taja '
    'zilizobadilika tu. Usitumie emoji zaidi ya moja. Aya mbili au tatu, '
    'si zaidi.'
)


def _yesterday_status(website):
    """Hali ya jana kwa kulinganisha."""
    since = timezone.now() - timedelta(days=1)
    snap = (IntegrationSnapshot.objects
            .filter(integration__website=website,
                    integration__provider='render',
                    checked_at__lt=since)
            .order_by('-checked_at').first())
    return (snap.metrics or {}).get(base.HOSTING_STATUS) if snap else None


def gather():
    """Kusanya ukweli. Hakuna AI hapa."""
    facts = {'changed': [], 'alerts': [], 'quiet': 0, 'total': 0}

    websites = (ManagedWebsite.objects
                .exclude(status='terminated')
                .select_related('client')
                .prefetch_related('integrations', 'domains'))

    for w in websites:
        facts['total'] += 1
        cfg = live_config(w)
        now_status = cfg.live_status
        was = _yesterday_status(w)

        if was and now_status != 'unknown' and was != now_status:
            facts['changed'].append({
                'name': w.name, 'from': was, 'to': now_status})
        else:
            facts['quiet'] += 1

    for a in alert_engine.collect():
        facts['alerts'].append({
            'level': a.level, 'site': a.website.name, 'title': a.title})

    return facts


def _plain(facts):
    """Muhtasari bila AI — huu ndio wa kutegemewa."""
    lines = [f"<b>JamiiTek — {timezone.now():%d/%m/%Y}</b>", '']

    crit = [a for a in facts['alerts'] if a['level'] == 'critical']
    warn = [a for a in facts['alerts'] if a['level'] == 'warning']

    if crit:
        lines.append('🔴 <b>Hatua sasa</b>')
        for a in crit:
            lines.append(f"  • {a['site']} — {a['title']}")
        lines.append('')
    if warn:
        lines.append('🟡 <b>Angalia</b>')
        for a in warn:
            lines.append(f"  • {a['site']} — {a['title']}")
        lines.append('')
    if facts['changed']:
        lines.append('<b>Mabadiliko</b>')
        for c in facts['changed']:
            lines.append(f"  • {c['name']}: {c['from']} → {c['to']}")
        lines.append('')
    if not crit and not warn and not facts['changed']:
        lines.append(f"✅ Projects {facts['total']} zote ziko sawa. "
                     'Hakuna kinachohitaji hatua.')

    return '\n'.join(lines)


def _ai(facts):
    from apps import llm
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not (key or llm.gemini_first()):
        return None
    try:
        import json

        import requests
        payload = {'model': MODEL, 'temperature': 0.3, 'max_tokens': 400,
                   'messages': [{'role': 'system', 'content': SYSTEM},
                                {'role': 'user', 'content': json.dumps(facts, ensure_ascii=False)}]}
        r = llm.gemini_response(payload)
        if r is None and not key:
            return None
        r = r or requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {key}',
                     'Content-Type': 'application/json'},
            json={'model': MODEL, 'temperature': 0.3, 'max_tokens': 400,
                  'messages': [
                      {'role': 'system', 'content': SYSTEM},
                      {'role': 'user', 'content': json.dumps(facts,
                                                             ensure_ascii=False)},
                  ]},
            timeout=25)
        if r.status_code != 200:
            logger.info('Groq amerudisha %s', r.status_code)
            return None
        text = r.json()['choices'][0]['message']['content'].strip()
        return text or None
    except Exception as e:
        logger.info('Groq imeshindikana: %s', type(e).__name__)
        return None


def build():
    facts = gather()
    plain = _plain(facts)

    smart = _ai(facts)
    if smart:
        return f'{smart}\n\n———\n{plain}'
    return plain


def send():
    return notify(build())
