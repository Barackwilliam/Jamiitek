"""
Email kwa wateja — njia moja, template moja (emails/customer_notice.html juu ya emails/base_email.html).

Awali email nyingi za wateja zilikuwa maandishi matupu (send_mail), baadhi kwa Kiswahili. Sasa kila email ya
mteja inapita hapa: Kiingereza, muundo wa JamiiTek (kichwa, kadi, kitufe, footer yenye mawasiliano), na
maandishi matupu yale yale kama fallback kwa programu zisizosoma HTML.

    send_customer_email(to, subject, body, button=('Pay now', url), rows=[('Plan', 'Business')])

`body` ni maandishi: aya zinatenganishwa na mstari mtupu. Aya ya kwanza ikianza na "Hello/Hi/Dear ...,"
inaonyeshwa kama salamu. Link ndani ya maandishi zinabonyezeka.
"""
import logging
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger('jamiitek.email')

_GREETING = re.compile(r'^(hello|hi|dear)\b[^\n]{0,80},?$', re.I)


def _paragraphs(body):
    if isinstance(body, (list, tuple)):
        parts = [str(p).strip() for p in body]
    else:
        parts = re.split(r'\n\s*\n', str(body or '').strip())
    return [p for p in parts if p]


def render_customer_email(subject, body, button=None, rows=None, alert=None):
    """(maandishi, html) ya email ya mteja."""
    paras = _paragraphs(body)
    greeting = ''
    if paras and _GREETING.match(paras[0]):
        greeting = paras.pop(0).rstrip(',') + ','
    ctx = {
        'subject': subject, 'greeting': greeting, 'paragraphs': paras,
        'button': {'label': button[0], 'url': button[1]} if button else None,
        'rows': [(str(k), str(v)) for k, v in (rows or [])],
        'alert': alert,
    }
    html = render_to_string('emails/customer_notice.html', ctx)
    text = '\n\n'.join(([greeting] if greeting else []) + paras
                       + ([f'{button[0]}: {button[1]}'] if button and button[1] not in '\n'.join(paras) else []))
    if rows:
        text += '\n\n' + '\n'.join(f'{k}: {v}' for k, v in rows)
    return text, html


def send_customer_email(to, subject, body, *, button=None, rows=None, alert=None, category='',
                        bcc=None, reply_to=None, from_email=None, fail_silently=True):
    """Tuma email ya mteja kwa template ya JamiiTek. Inarudisha True ikikubaliwa na backend."""
    recipients = [to] if isinstance(to, str) else [t for t in (to or []) if t]
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        return False
    text, html = render_customer_email(subject, body, button=button, rows=rows, alert=alert)
    msg = EmailMultiAlternatives(
        subject=subject, body=text,
        from_email=from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'JamiiTek <info@jamiitek.com>'),
        to=recipients, bcc=bcc or None, reply_to=reply_to or None,
        headers={'X-JT-Category': category} if category else None,
    )
    msg.attach_alternative(html, 'text/html')
    try:
        return bool(msg.send(fail_silently=fail_silently))
    except Exception:
        if not fail_silently:
            raise
        logger.exception('Email ya mteja haikutumwa: %s', subject[:80])
        return False
