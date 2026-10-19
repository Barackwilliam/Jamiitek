"""Kuhesabu hatua 4 za kuuza template — ili mmiliki aone wateja wanapotelea.

  views      — ukurasa wa template (/templates/<slug>/) umefunguliwa na mtu (si bot, si staff)
  tries      — website imeanzishwa na template hii kwenye Builder ("Customize free")
  checkouts  — website ya template inayouzwa imefika ukurasa wa malipo (mara moja kwa website)
  paid       — malipo ya template yamethibitishwa (builder/billing.py fulfill)

Hesabu ni kwa siku (TemplateFunnel), na zinaonekana kwenye admin ya Website Templates.
Kuhesabu HAKUWEZI kuvunja kununua: kosa lolote linaandikwa kwenye log tu.
"""
import logging
import re

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

STEPS = ('views', 'tries', 'checkouts', 'paid')
# Google, Bing, preview za WhatsApp/Facebook, Lighthouse n.k. — si wateja
BOT_RE = re.compile(r'bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|lighthouse|headless|python|curl|wget',
                    re.I)


def is_person(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    user = getattr(request, 'user', None)
    return bool(ua) and not BOT_RE.search(ua) and not (user and user.is_authenticated and user.is_staff)


def count(template_id, step):
    if not template_id or step not in STEPS:
        return
    try:
        from .models import TemplateFunnel
        day = timezone.localdate()
        # Savepoint: kosa la DB hapa halivunji transaction ya anayeita (mf. malipo ya Pesapal)
        with transaction.atomic():
            rows = TemplateFunnel.objects.filter(template_id=template_id, day=day)
            if rows.update(**{step: F(step) + 1}):
                return
            try:
                with transaction.atomic():
                    TemplateFunnel.objects.create(template_id=template_id, day=day, **{step: 1})
            except IntegrityError:                 # ombi jingine liliunda safu hiyo hiyo sekunde hiyo hiyo
                rows.update(**{step: F(step) + 1})
    except Exception:
        logger.exception('template funnel: %s %s', template_id, step)
