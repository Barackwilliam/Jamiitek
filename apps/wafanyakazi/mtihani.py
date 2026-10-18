"""
Mtihani wa umahiri — kuona timu inavyofanya kazi KABLA ya kuiamini.

Kila mfanyakazi anafanya kazi yake kwenye data halisi ya JamiiTek, ndani ya
transaction inayorudishwa nyuma mwishoni. Kwa hiyo:

  • hakuna kazi inayohifadhiwa, hakuna alama inayobadilika
  • hakuna email wala WhatsApp inayotumwa (wafanyakazi hawatumi; William
    anaandika ripoti tu, haitumi)
  • AI inaitwa kweli (Groq) — ndiyo hasa tunayoipima

Kinachobaki ni rasimu za mfano za kila mfanyakazi, na ukaguzi wa kila moja:
urefu, AI au template, nafasi tupu, kiasi cha pesa kilichobuniwa, link.
"""
import logging
import re

from django.db import transaction
from django.utils import timezone

from . import ai, diana, grace, ibrahimu, selvester, william
from .models import Kazi, Mtihani
from .team import member

logger = logging.getLogger(__name__)

SAMPLES = 3            # rasimu za mfano kwa kila mfanyakazi
AI_PER_WORKER = 4      # maombi ya AI kwa kila mfanyakazi
WORKERS = (('diana', diana), ('selvester', selvester), ('ibrahimu', ibrahimu), ('grace', grace))

AMOUNT_RE = re.compile(r'\d{1,3}(?:,\d{3})+|\d{4,}')
PLACEHOLDER_RE = re.compile(r'\{[^}]*\}|\[[A-Za-z _]+\]|XXX|<jina>|\bINSERT\b', re.I)
LINK_RE = re.compile(r'https?://\S+')


class _Rollback(Exception):
    pass


def _amounts(text):
    found = {a.replace(',', '') for a in AMOUNT_RE.findall(text or '')}
    return {a for a in found if not (len(a) == 4 and 1990 <= int(a) <= 2100)}   # miaka si pesa


def check(kazi, from_ai):
    """Ukaguzi wa rasimu moja. Rudisha orodha ya (sawa?, maelezo)."""
    text = kazi.draft or ''
    checks = [(from_ai, 'Imeandikwa na AI' if from_ai else 'Template ya kawaida (AI haikuandika)')]

    size = len(text)
    good_size = 60 <= size <= (2200 if kazi.channel == 'social' else 1600)
    checks.append((good_size, f'Urefu: herufi {size}'))

    holes = PLACEHOLDER_RE.findall(text)
    checks.append((not holes, 'Hakuna nafasi tupu' if not holes else f'Nafasi tupu: {", ".join(holes[:3])}'))

    known = _amounts(f'{kazi.title} {kazi.detail} {kazi.subject}')
    invented = sorted(a for a in _amounts(text) - known
                      if not any(a in link for link in LINK_RE.findall(text)))
    checks.append((not invented, 'Hakuna kiasi kilichobuniwa' if not invented
                   else f'Kiasi kisichotoka kwenye data: {", ".join(invented[:3])}'))

    if kazi.worker == 'diana' and kazi.ref.startswith('invoices:'):
        has_link = '/invoice/' in text
        checks.append((has_link, 'Ina link ya invoice' if has_link else 'Haina link ya invoice'))
    if kazi.recipient_name and kazi.channel in ('email', 'whatsapp'):
        first = kazi.recipient_name.split()[0]
        named = first.lower() in text.lower()
        checks.append((named, f'Inamtaja {first}' if named else f'Haimtaji {first}'))
    return [{'ok': ok, 'text': note} for ok, note in checks]


def _sample(slug, written):
    rows = []
    qs = Kazi.objects.filter(worker=slug).exclude(draft='').order_by('priority', 'pk')[:SAMPLES]
    for kazi in qs:
        if kazi.channel == 'faq':
            from_ai = True   # knowledge.draft_answer inarudisha jibu la AI au tupu tu
        else:
            from_ai = any(w[:80] in kazi.draft for w in written)
        rows.append({
            'title': kazi.title, 'channel': kazi.get_channel_display(),
            'to': f'{kazi.recipient_name} {kazi.recipient_email or kazi.recipient_phone}'.strip(),
            'subject': kazi.subject, 'draft': kazi.draft,
            'checks': check(kazi, from_ai),
        })
    return rows


def _exam(now):
    result = {'workers': [], 'bots': [], 'william': ''}
    # Futa kazi zilizopo NDANI ya transaction ili kila mfanyakazi aandike upya
    Kazi.objects.all().delete()

    result['bots'] = [f'{b.bot_name} — {b.business_name} ({b.session_name or "bila session"})'
                      for b in ibrahimu.bots()]

    written = []
    for slug, module in WORKERS:
        ai.reset_budget(AI_PER_WORKER)
        when = now.replace(hour=max(now.hour, grace.START_HOUR + 1)) if slug == 'grace' else now
        entry = {'slug': slug, **{k: member(slug)[k] for k in ('name', 'role', 'icon', 'color', 'photo', 'title')}}
        try:
            with transaction.atomic():   # savepoint: kosa la mmoja lisiharibu wengine
                entry['summary'] = module.run(when)
        except Exception as exc:
            logger.exception('[mtihani] %s', slug)
            entry['error'] = f'{type(exc).__name__}: {exc}'[:300]
        written += ai.written()
        entry['ai_failed'] = ai.failures()
        result['workers'].append(entry)

    # Sampuli mwishoni: Selvester anapokea kazi kutoka kwa Ibrahimu pia
    for entry in result['workers']:
        entry['found'] = Kazi.objects.filter(worker=entry['slug']).count()
        entry['samples'] = _sample(entry['slug'], written)

    ai.reset_budget(2)
    try:
        result['william'] = william.morning_report(now)
    except Exception as exc:
        result['william'] = f'Imeshindwa: {type(exc).__name__}: {exc}'
    result['william_ai'] = bool(ai.written())
    return result


def run(mtihani_id=None, now=None):
    """Endesha mtihani mmoja na uhifadhi matokeo kwenye Mtihani."""
    from django.core.cache import cache

    from .runner import LOCK, LOCK_TTL

    now = timezone.localtime(now) if now else timezone.localtime()
    exam = (Mtihani.objects.get(pk=mtihani_id) if mtihani_id
            else Mtihani.objects.create())
    if not cache.add(LOCK, 'mtihani', LOCK_TTL):
        exam.status = Mtihani.FAILED
        exam.result = {'error': 'Timu iko kazini sasa hivi — jaribu tena baada ya dakika moja.'}
        exam.finished_at = timezone.now()
        exam.save(update_fields=['status', 'result', 'finished_at'])
        return exam
    outcome = {}
    try:
        with transaction.atomic():
            outcome = _exam(now)
            raise _Rollback
    except _Rollback:
        exam.status = Mtihani.DONE
    except Exception as exc:
        logger.exception('[mtihani] umeshindwa')
        exam.status = Mtihani.FAILED
        outcome = {'error': f'{type(exc).__name__}: {exc}'[:400]}
    finally:
        ai.reset_budget()
        cache.delete(LOCK)

    passed = total = 0
    for w in outcome.get('workers', []):
        for s in w['samples']:
            for c in s['checks']:
                total += 1
                passed += c['ok']
    outcome['score'] = {'passed': passed, 'total': total}
    from apps import llm
    outcome['groq'] = bool(ai._key() or llm.gemini_first())
    exam.result = outcome
    exam.finished_at = timezone.now()
    exam.save(update_fields=['status', 'result', 'finished_at'])
    return exam


def run_in_background():
    import threading

    from django.db import connection

    exam = Mtihani.objects.create()

    def target():
        try:
            run(exam.pk)
        except Exception:
            logger.exception('[mtihani] thread')
            Mtihani.objects.filter(pk=exam.pk).update(status=Mtihani.FAILED, finished_at=timezone.now())
        finally:
            connection.close()

    threading.Thread(target=target, name='jamiitek-mtihani', daemon=True).start()
    return exam
