"""
Email backend inayotuma kupitia HTTPS badala ya SMTP.

KWA NINI

Render inazuia outbound traffic kwenda ports 25, 465 na 587 kwenye free
web services (tangu 26 Sep 2025). Muunganisho hauzuiliwi kwa kukataliwa
— unaachwa ukisubiri, hadi gunicorn inaua worker:

    File "smtplib.py", line 312, in _get_socket
        return socket.create_connection((host, port), timeout, ...)
    ...
    Worker (pid:79) was sent SIGKILL!

Port 443 haiwezi kuzuiliwa — server ingeshindwa kufanya kazi kabisa.
Kwa hiyo tunatuma kupitia REST API ya Brevo badala ya SMTP.

INAFANYA KAZI NA CODE ILIYOPO BILA KUBADILISHWA

Hii ni `BaseEmailBackend` kamili. `send_mail()`, `EmailMessage` na
`EmailMultiAlternatives` zote zinaendelea kufanya kazi kama kawaida —
`apps/utils/email_notifications.py` inatumia HTML alternative, na hiyo
inashughulikiwa.

KUSANIDI

    BREVO_API_KEY   = <kutoka app.brevo.com > SMTP & API > API Keys>
    EMAIL_HOST_USER = info@jamiitek.com   (lazima iwe imethibitishwa Brevo)

Brevo free: email 300 kwa siku. Sender lazima ithibitishwe —
Senders > Add a sender, kisha bonyeza kiungo kilichotumwa.
"""
import logging

import requests
from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings

logger = logging.getLogger('jamiitek.email')

BREVO_URL = 'https://api.brevo.com/v3/smtp/email'
TIMEOUT = 20

# Aina ya barua inakisiwa kutoka kichwa, kwa zile zisizotuma
# `X-JT-Category` yenyewe. Inatumika kuchuja kwenye /manage/emails/.
_CATEGORY_HINTS = (
    ('suspend', 'suspension'),
    ('restored', 'restored'),
    ('final notice', 'expiry_warning'),
    ('expiry', 'expiry_warning'),
    ('expires', 'expiry_warning'),
    ('renewal', 'renewal'),
    ('receipt', 'receipt'),
    ('payment', 'payment'),
    ('support', 'support'),
    ('registration', 'registration'),
    ('contact form', 'contact'),
    ('welcome', 'welcome'),
    ('karibu', 'welcome'),
    ('blog', 'blog'),
    ('habari', 'news'),
    ('imeacha kujibu', 'bot_paused'),
    ('binadamu', 'handoff'),
    # Alert za mfumo (apps/notify.py) — "[JamiiTek] 🔴 *SSL inakaribia kuisha*"
    ('ssl', 'alert'),
    ('tatizo', 'alert'),
    ('down', 'alert'),
    ('[jamiitek]', 'alert'),
    ('jaribio', 'test'),
)


def _guess_category(subject):
    low = (subject or '').lower()
    for needle, name in _CATEGORY_HINTS:
        if needle in low:
            return name
    return 'other'


class BrevoEmailBackend(BaseEmailBackend):
    """Inatuma kila EmailMessage kupitia HTTPS."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, 'BREVO_API_KEY', '') or ''
        self.default_from = (
            getattr(settings, 'DEFAULT_FROM_EMAIL', '')
            or getattr(settings, 'EMAIL_HOST_USER', '')
            or 'info@jamiitek.com'
        )

    # ── Visaidizi ─────────────────────────────────────────────

    @staticmethod
    def _split(addr):
        """
        "JamiiTek <info@jamiitek.com>" -> {'name': 'JamiiTek', 'email': '...'}
        Brevo inadai muundo huu; Django inatumia maandishi.
        """
        addr = (addr or '').strip()
        if '<' in addr and addr.endswith('>'):
            name, email = addr.rsplit('<', 1)
            return {'name': name.strip().strip('"'), 'email': email[:-1].strip()}
        return {'email': addr}

    @staticmethod
    def _bodies(message):
        """
        Inarudisha (maandishi, html).

        `EmailMultiAlternatives` inaweka HTML kwenye `alternatives`, si
        kwenye `body`. Bila kuiangalia, email za onyo za wateja
        zingetoka bila muundo wowote.
        """
        text = message.body or ''
        html = ''
        for content, mimetype in getattr(message, 'alternatives', []) or []:
            if mimetype == 'text/html':
                html = content
                break
        if getattr(message, 'content_subtype', '') == 'html':
            html, text = text, ''
        return text, html

    # ── API ya Django ─────────────────────────────────────────

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not self.api_key:
            logger.error('BREVO_API_KEY haijawekwa — hakuna email itakayotoka')
            if not self.fail_silently:
                raise ValueError('BREVO_API_KEY haijawekwa')
            return 0

        sent = 0
        for message in email_messages:
            if self._send_one(message):
                sent += 1
        return sent

    def _send_one(self, message):
        recipients = list(message.to or [])
        if not recipients:
            return False

        text, html = self._bodies(message)

        payload = {
            'sender': self._split(message.from_email or self.default_from),
            'to': [{'email': a} for a in recipients],
            'subject': message.subject or '(hakuna kichwa)',
        }
        if html:
            payload['htmlContent'] = html
            if text:
                payload['textContent'] = text
        else:
            # Brevo inadai mojawapo. Maandishi matupu yanakataliwa.
            payload['textContent'] = text or ' '

        if message.cc:
            payload['cc'] = [{'email': a} for a in message.cc]
        if message.bcc:
            payload['bcc'] = [{'email': a} for a in message.bcc]
        if message.reply_to:
            payload['replyTo'] = self._split(message.reply_to[0])

        try:
            resp = requests.post(
                BREVO_URL,
                headers={
                    'api-key': self.api_key,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                json=payload,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            logger.error('Brevo: muunganisho umeshindwa — %s', e)
            if not self.fail_silently:
                raise
            return False

        if resp.status_code in (200, 201, 202):
            # `messageId` ndiyo inayounganisha barua hii na matukio
            # yatakayorudi kwenye webhook (delivered, bounced...).
            # Bila kuihifadhi, hatuwezi kamwe kujua hatima ya barua.
            try:
                message_id = (resp.json() or {}).get('messageId', '')
            except ValueError:
                message_id = ''
            self._log(message, recipients, 'sent', message_id=message_id)
            logger.info('Email imetumwa kwa %s: %s',
                        ', '.join(recipients), (message.subject or '')[:60])
            return True

        detail = resp.text[:300]
        logger.error('Brevo %s: %s', resp.status_code, detail)
        self._log(message, recipients, 'error', error=f'Brevo {resp.status_code}: {detail}')
        if not self.fail_silently:
            raise RuntimeError(f'Brevo imekataa ({resp.status_code}): {detail}')
        return False

    # ── Kumbukumbu ────────────────────────────────────────────

    @staticmethod
    def _log(message, recipients, status, message_id='', error=''):
        """Hifadhi barua kwenye EmailLog. Kamwe isivunje utumaji."""
        try:
            from apps.models import Client, EmailLog, ManagedWebsite

            headers = getattr(message, 'extra_headers', {}) or {}
            category = headers.get('X-JT-Category', '') or _guess_category(message.subject)
            site_pk = headers.get('X-JT-Website') or None

            for addr in recipients:
                client = Client.objects.filter(email__iexact=addr).first()
                website = None
                if site_pk:
                    website = ManagedWebsite.objects.filter(pk=site_pk).first()
                EmailLog.objects.create(
                    to_email=addr,
                    subject=(message.subject or '')[:255],
                    category=category[:40],
                    message_id=str(message_id)[:255],
                    status=status,
                    error=error[:2000],
                    client=client,
                    website=website or (client.websites.first() if client and hasattr(client, 'websites') else None),
                )
        except Exception:
            logger.exception('EmailLog haikuhifadhiwa (barua yenyewe haijaathirika)')


# ── Taarifa kwa mmiliki kwa kila email ya mteja ─────────────────────
#
# Mmiliki anataka kujua kila email inayomfikia mteja: "Asha (asha@x) ametumiwa: Hosting reminder ...".
# Backend hii inazunguka backend halisi (EMAIL_REAL_BACKEND: Brevo / SMTP / console). Kila barua
# iliyotumwa kwa mteja inafuatwa na taarifa fupi kwenda OWNER_NOTICE_EMAIL. Taarifa haina maudhui ya
# barua (kwa mfano kiungo cha kubadilisha password) — ni nani, kichwa, aina na muda tu.
#
# Haitumi taarifa kwa: barua za ndani (wapokeaji wote ni anwani za JamiiTek), barua ambazo mmiliki
# tayari ana nakala (cc/bcc), na taarifa zenyewe (X-JT-Owner-Notice). OWNER_NOTICE_EMAIL tupu = imezimwa.

from email.utils import parseaddr


def _owner_addresses():
    keys = ('OWNER_NOTICE_EMAIL', 'EMAIL_HOST_USER', 'ALERT_EMAIL', 'PAYMENTS_OWNER_EMAIL',
            'BLOG_REVIEW_EMAIL', 'ADMIN_EMAIL', 'SUPPORT_EMAIL')
    out = {'info@jamiitek.com'}
    for k in keys:
        v = getattr(settings, k, '') or ''
        if v:
            out.add(parseaddr(str(v))[1].lower())
    import os
    alert = os.getenv('ALERT_EMAIL', '').strip()
    if alert:
        out.add(alert.lower())
    return out


_KIND_NAMES = {
    'expiry_warning': 'Hosting / service expiry reminder', 'payment_reminder': 'Hosting reminder',
    'suspension': 'Service suspended', 'restored': 'Service restored', 'renewal': 'Renewal',
    'receipt': 'Payment receipt', 'payment': 'Payment', 'welcome': 'Welcome', 'contact': 'Contact form reply',
    'newsletter': 'Newsletter welcome', 'domain': 'Domain', 'bot_down': 'JamiiBot disconnected',
    'bot_paused': 'JamiiBot stopped replying', 'handoff': 'JamiiBot: visitor wants a person',
    'security': 'Account security', 'builder_unpaid': 'Web Builder payment reminder', 'support': 'Support',
    'registration': 'Registration', 'notice': 'Notice',
}


_SENSITIVE_WORDS = ('password', 'reset', 'verification code', 'verify your', 'login code', 'sign-in code',
                    'one-time', 'otp', '2fa', 'two-factor', 'neno la siri', 'nenosiri')


def _is_sensitive(message, kind):
    """Barua za usalama: mmiliki anapata taarifa fupi tu, si nakala yenye link/code ya siri."""
    if kind in ('security',):
        return True
    low = (message.subject or '').lower()
    return any(w in low for w in _SENSITIVE_WORDS)


def _who(addr):
    """Jina la mteja kutoka kwenye kumbukumbu, kama lipo."""
    try:
        from apps.models import Client
        c = Client.objects.filter(email__iexact=addr).only('name').first()
        if c and c.name:
            return c.name
        from apps.chatbot.models import ChatbotClient
        b = ChatbotClient.objects.filter(email__iexact=addr).only('full_name').first()
        if b and b.full_name:
            return b.full_name
        from django.contrib.auth.models import User
        u = User.objects.filter(email__iexact=addr).first()
        if u and (u.get_full_name() or '').strip():
            return u.get_full_name()
    except Exception:
        pass
    return ''


class OwnerNoticeBackend(BaseEmailBackend):
    """Inatuma kupitia EMAIL_REAL_BACKEND, kisha inamjulisha mmiliki kila barua iliyomfikia mteja."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        from django.core.mail import get_connection
        real = getattr(settings, 'EMAIL_REAL_BACKEND', '') or 'django.core.mail.backends.console.EmailBackend'
        self.inner = get_connection(real, fail_silently=fail_silently, **kwargs)

    def open(self):
        return self.inner.open()

    def close(self):
        return self.inner.close()

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages or []:
            n = self.inner.send_messages([message]) or 0
            sent += n
            if n:
                _count(n)
                try:
                    self._notice(message)
                except Exception:
                    logger.exception('Taarifa ya mmiliki haikutumwa (barua ya mteja imeshatoka)')
        return sent

    def _notice(self, message):
        owner = (getattr(settings, 'OWNER_NOTICE_EMAIL', '') or '').strip()
        headers = getattr(message, 'extra_headers', {}) or {}
        if not owner or headers.get('X-JT-Owner-Notice'):
            return
        mine = _owner_addresses()
        copied = {parseaddr(a)[1].lower() for a in list(message.cc or []) + list(message.bcc or [])}
        if copied & mine:
            return                                    # mmiliki tayari ana nakala kamili
        customers = [parseaddr(a)[1] for a in list(message.to or [])]
        customers = [a for a in customers if a and a.lower() not in mine]
        if not customers:
            return                                    # barua ya ndani (kwa JamiiTek yenyewe)

        from django.utils import timezone
        from apps.utils.customer_email import render_customer_email
        kind = headers.get('X-JT-Category', '') or _guess_category(message.subject)
        kind_name = _KIND_NAMES.get(kind, kind.replace('_', ' ').capitalize() if kind and kind != 'other' else 'Email')
        people = [f'{_who(a)} <{a}>' if _who(a) else a for a in customers]
        first = _who(customers[0]) or customers[0]
        subject = f'📤 {first} was sent: {(message.subject or "")[:90]}'
        when = timezone.localtime().strftime('%d %b %Y, %H:%M')

        # Kikomo cha siku: email za leo zikifika OWNER_NOTICE_DAILY_LIMIT, taarifa za moja moja zinasimama
        # na zinaingia kwenye muhtasari wa siku (amri owner_notice_summary). Taarifa moja ya kujulisha
        # kwamba kikomo kimefikiwa inatumwa mara ya kwanza tu.
        if _over_limit():
            first_time = _hold({'to': ', '.join(people), 'about': kind_name,
                                'subject': (message.subject or '')[:200], 'time': when})
            if first_time:
                self._send_owner(owner, '📊 Customer email notices paused for today — summary coming',
                                 f'Hello,\n\nToday the system has already sent {_limit()} emails. To save the daily '
                                 'email allowance, the individual "was sent" notices stop here for today.\n\n'
                                 'You will get one summary of every customer email sent after this point, '
                                 'shortly after midnight.',
                                 label='Daily limit reached', chip=('⏸ Paused', 'warning'))
                _count(1)
            return
        # Nakala KAMILI (email ileile aliyoipata mteja + viambatisho), isipokuwa barua za usalama
        # (password reset, codes) — hizo zinabaki taarifa fupi ili link za siri zisisafiri.
        if getattr(settings, 'OWNER_COPY_FULL', True) and not _is_sensitive(message, kind):
            self._send_copy(owner, message, people, kind_name, when)
            _count(1, notice=True)
            return
        self._send_owner(owner, subject, 'Hello,\n\nA customer email has just been sent from the system.',
                         rows=[('To', ', '.join(people)), ('About', kind_name),
                               ('Subject', message.subject or '—'), ('Sent', f'{when} (EAT)')],
                         label='Sent to a customer', chip=('📤 Sent', 'info'))
        _count(1, notice=True)

    def _send_copy(self, owner, message, people, kind_name, when):
        """Tuma kwa mmiliki nakala ya barua halisi, ikiwa na kibandiko juu: kwa nani, nini, lini."""
        from django.core.mail import EmailMultiAlternatives
        from django.utils.html import escape
        to_line = ', '.join(people)
        subject = f'📋 Copy · {(message.subject or "")[:150]}'
        text_head = f'[Copy of the email sent to {to_line} — {kind_name} — {when} EAT]\n\n'
        html = next((c for c, mt in getattr(message, 'alternatives', []) or [] if mt == 'text/html'), '')
        if not html and getattr(message, 'content_subtype', '') == 'html':
            html = message.body or ''
        copy = EmailMultiAlternatives(
            subject=subject[:200], body=text_head + (message.body if not html or message.body != html else ''),
            to=[owner], from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            headers={'X-JT-Owner-Notice': '1', 'X-JT-Category': 'owner_copy'})
        if html:
            banner = ('<div style="font:600 13px/1.5 Inter,Arial,sans-serif;background:#ecfeff;color:#155e75;'
                      'border:1px solid #a5f3fc;border-radius:12px;padding:10px 14px;margin:12px auto;max-width:600px">'
                      f'📋 <b>Copy for you</b> — sent to {escape(to_line)} · {escape(kind_name)} · {escape(when)} EAT'
                      '</div>')
            low = html.lower()
            i = low.find('<body')
            j = low.find('>', i) + 1 if i >= 0 else 0
            copy.attach_alternative(html[:j] + banner + html[j:], 'text/html')
        for att in getattr(message, 'attachments', []) or []:
            copy.attach(*att) if isinstance(att, tuple) else copy.attach(att)
        return self.inner.send_messages([copy])

    def _send_owner(self, owner, subject, body, **kw):
        from django.core.mail import EmailMultiAlternatives
        from apps.utils.customer_email import render_customer_email
        text, html = render_customer_email(subject, body, **kw)
        note = EmailMultiAlternatives(subject=subject[:200], body=text, to=[owner],
                                      from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                                      headers={'X-JT-Owner-Notice': '1', 'X-JT-Category': 'owner_notice'})
        note.attach_alternative(html, 'text/html')
        return self.inner.send_messages([note])


# ── Hesabu ya siku (OwnerNoticeDay) ────────────────────────────────

def _limit():
    return int(getattr(settings, 'OWNER_NOTICE_DAILY_LIMIT', 150) or 0)


def _today_row():
    from django.utils import timezone
    from apps.models import OwnerNoticeDay
    row, _ = OwnerNoticeDay.objects.get_or_create(date=timezone.localdate())
    return row


def _count(n, notice=False):
    """Hesabu email zilizotumwa leo. Kosa hapa halivunji utumaji."""
    try:
        from django.db.models import F
        from apps.models import OwnerNoticeDay
        row = _today_row()
        upd = {'sent_total': F('sent_total') + n}
        if notice:
            upd['notices'] = F('notices') + 1
        OwnerNoticeDay.objects.filter(pk=row.pk).update(**upd)
    except Exception:
        logger.exception('Hesabu ya email za leo haikusasishwa')


def _over_limit():
    limit = _limit()
    if not limit:
        return False
    try:
        return _today_row().sent_total >= limit
    except Exception:
        return False


def _hold(item):
    """Weka email kwenye muhtasari wa leo. Inarudisha True ikiwa ni ya kwanza (taarifa ya kikomo itumwe)."""
    from django.db import transaction
    from apps.models import OwnerNoticeDay
    with transaction.atomic():
        row = OwnerNoticeDay.objects.select_for_update().get(pk=_today_row().pk)
        row.held = (list(row.held or []) + [item])[-1000:]
        first = not row.limit_notice_sent
        row.limit_notice_sent = True
        row.save(update_fields=['held', 'limit_notice_sent'])
    return first
