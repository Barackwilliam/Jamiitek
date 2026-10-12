"""
Kutekeleza uamuzi wako juu ya kazi.

Hapa ndipo PEKEE ambapo ujumbe wa mfanyakazi unamfikia mteja — na hufika tu
baada ya wewe kukubali (kwenye panel au kwa "OK code" kupitia wILife).

    approve(kazi)   tuma rasimu (email / WhatsApp / FAQ), tumia kichwa cha SEO, au weka "imefanyika"
    dismiss(kazi)   achana nayo
    complete(kazi)  umeifanya mwenyewe
"""
import logging
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string

from .models import Kazi
from .team import member

logger = logging.getLogger(__name__)


def _digits(phone):
    d = re.sub(r'\D', '', phone or '')
    if d.startswith('0') and len(d) == 10:
        d = '255' + d[1:]
    return d


def wa_link(phone, text=''):
    from urllib.parse import quote
    d = _digits(phone)
    if not d or len(d) > 13:   # LID za WhatsApp si namba za simu
        return ''
    return f'https://wa.me/{d}' + (f'?text={quote(text)}' if text else '')


def _email(kazi):
    who = member(kazi.worker)
    paragraphs = [p.strip() for p in kazi.draft.split('\n\n') if p.strip()]
    html = render_to_string('emails/mfanyakazi.html', {
        'subject': kazi.subject or kazi.title,
        'paragraphs': paragraphs,
        'worker': who,
    })
    msg = EmailMultiAlternatives(
        subject=kazi.subject or kazi.title,
        body=kazi.draft,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'JamiiTek <info@jamiitek.com>'),
        to=[kazi.recipient_email],
        reply_to=[getattr(settings, 'WORKERS_REPLY_TO', '') or 'info@jamiitek.com'],
    )
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=False)
    return f'Email imetumwa kwa {kazi.recipient_email}.'


def _whatsapp(kazi):
    """
    Kupitia JamiiBot ya JamiiTek (bridge). Kama bridge haipo, rudisha link
    ya wa.me ili utume mwenyewe kwa kubonyeza mara moja.
    """
    from apps.chatbot import bridge
    from apps.chatbot.models import Conversation, Message

    from .ibrahimu import bots

    conv = None
    if kazi.ref.startswith('conv:'):
        conv = Conversation.objects.filter(pk=kazi.ref.split(':', 1)[1]).select_related('bot').first()
    bot = conv.bot if conv else bots().first()

    if bot and bridge.is_configured():
        handler = bridge.BaileysHandler(bot)
        jid = (conv.metadata or {}).get('jid') if conv else None
        res = handler.send_text(_digits(kazi.recipient_phone) or kazi.recipient_phone,
                                kazi.draft, jid=jid)
        if res.get('success'):
            if conv:
                Message.objects.create(conversation=conv, role='assistant', content=kazi.draft)
            return True, f'WhatsApp imetumwa kwa {kazi.recipient_name or kazi.recipient_phone}.'
        logger.warning('[wafanyakazi] WhatsApp #%s haikufika: %s', kazi.pk, res.get('error'))

    link = wa_link(kazi.recipient_phone, kazi.draft)
    if link:
        return False, f'Tuma mwenyewe kwa WhatsApp: {link}'
    return False, 'WhatsApp haipatikani kwa sasa na namba si ya kawaida — mjibu kupitia JamiiBot.'


def _faq(kazi):
    from apps.chatbot import knowledge
    from apps.chatbot.models import KnowledgeGap

    gap = KnowledgeGap.objects.filter(pk=kazi.ref.split(':', 1)[1]).select_related('bot').first()
    if not gap:
        raise ValueError('swali hilo halipo tena')
    knowledge.approve(gap, kazi.draft)
    return f'Jibu limeongezwa kwenye FAQ za {gap.bot.bot_name} — bot sasa inajua.'


@transaction.atomic
def approve(kazi_id, draft=None):
    """Rudisha (ok, ujumbe). Imefungwa ili OK mbili za haraka zisitume mara mbili."""
    kazi = Kazi.objects.select_for_update().filter(pk=kazi_id).first()
    if kazi is None:
        return False, 'Kazi hiyo haipo.'
    if not kazi.is_live:
        return False, f'Kazi hii tayari: {kazi.get_status_display()}.'
    if draft is not None and draft.strip():
        kazi.draft = draft.strip()
        kazi.save(update_fields=['draft', 'updated_at'])

    try:
        if kazi.channel == 'email' and kazi.recipient_email and kazi.draft:
            message = _email(kazi)
            kazi.close(Kazi.SENT, message)
            return True, message
        if kazi.channel == 'whatsapp' and kazi.draft:
            sent, message = _whatsapp(kazi)
            kazi.close(Kazi.SENT if sent else Kazi.DONE, message)
            return True, message
        if kazi.channel == 'faq' and kazi.draft:
            message = _faq(kazi)
            kazi.close(Kazi.DONE, message)
            return True, message
        if kazi.channel == 'seo' and kazi.draft:
            from .seo import apply
            message = apply(kazi) or ('Ukurasa huu una kichwa kwenye code — weka kichwa na '
                                      'maelezo haya kwenye template yake.')
            kazi.close(Kazi.DONE, message)
            return True, message
    except Exception as exc:
        logger.exception('[wafanyakazi] kutekeleza kazi #%s', kazi.pk)
        kazi.result = f'Imeshindikana: {exc}'[:400]
        kazi.save(update_fields=['result', 'updated_at'])
        return False, kazi.result

    message = 'Imewekwa kuwa imefanyika.'
    kazi.close(Kazi.DONE, message)
    return True, message


def dismiss(kazi_id, reason='Umeachana nayo.'):
    kazi = Kazi.objects.filter(pk=kazi_id).first()
    if kazi is None:
        return False, 'Kazi hiyo haipo.'
    if not kazi.is_live:
        return False, f'Kazi hii tayari: {kazi.get_status_display()}.'
    kazi.close(Kazi.DISMISSED, reason)
    return True, 'Kazi imeachwa.'


def complete(kazi_id):
    kazi = Kazi.objects.filter(pk=kazi_id).first()
    if kazi is None:
        return False, 'Kazi hiyo haipo.'
    if not kazi.is_live:
        return False, f'Kazi hii tayari: {kazi.get_status_display()}.'
    kazi.close(Kazi.DONE, 'Umeifanya mwenyewe.')
    return True, 'Imewekwa kuwa imekamilika.'
