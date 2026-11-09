"""
Kumbukumbu ya matukio ya mfumo, na email kwa mmiliki.

Kila tukio la msingi linarekodiwa (ActivityEvent): nani (mteja, wewe/staff, au mfumo), alifanya nini, saa
ngapi. Kwa kila aina ya tukio mmiliki anachagua kwenye Admin -> Activity settings:

    instant   email ya papo hapo kwa OWNER_NOTICE_EMAIL
    digest    linaingia kwenye muhtasari wa siku (amri activity_digest, saa ACTIVITY_DIGEST_HOUR)
    off       linahifadhiwa tu (linaonekana Admin -> Activity)

    record('payment_completed', 'Asha Mussa paid TZS 150,000', rows=[...], amount=150000)

Nani alifanya: `actor` ikipitishwa (User / 'system'), vinginevyo mtumiaji wa ombi la sasa
(CurrentUserMiddleware): staff -> 'staff', mtumiaji mwingine -> 'customer', hakuna ombi -> 'system'.

record() kamwe haivunji kitendo kilichoirekodi: kosa lolote linaandikwa kwenye logs tu.
"""
import logging
import threading

from django.conf import settings

logger = logging.getLogger('jamiitek.activity')

# action: (mode ya kawaida, maelezo kwa Admin)
DEFAULT_RULES = {
    # Wateja
    'account_created':    ('instant', 'New account (customer signed up)'),
    'payment_completed':  ('instant', 'Payment completed'),
    'payment_submitted':  ('instant', 'JamiiBot payment submitted for checking'),
    'build_request_paid': ('instant', '"Build it for me" paid'),
    'payment_proof':      ('instant', 'Customer sent proof of payment for an invoice'),
    'invoice_paid':       ('instant', 'Invoice payment recorded (receipt sent)'),
    'website_published':  ('instant', 'Web Builder website published'),
    'bot_registered':     ('instant', 'New JamiiBot registered'),
    'support_request':    ('digest',  'Support request (you already get its email)'),
    'customer_login':     ('digest',  'Customer signed in'),
    # Wewe / staff
    'admin_delete':       ('instant', 'Something deleted in Admin'),
    'admin_change':       ('digest',  'Something added or changed in Admin'),
    'website_suspended':  ('instant', 'Website suspended'),
    'website_restored':   ('instant', 'Website restored'),
    'staff_login':        ('digest',  'Staff signed in'),
    # Mfumo
    'payment_failed':     ('instant', 'Payment failed or reversed'),
    'bot_disconnected':   ('instant', 'JamiiBot disconnected from WhatsApp'),
    'domain_live':        ('instant', 'Custom domain went live'),
    'renewal_invoice':    ('digest',  'Renewal invoice created and sent (hosting / domain / email)'),
}

ACTOR_LABELS = {'customer': '👤 Customer', 'staff': '🛠 You / staff', 'system': '🤖 System'}

_local = threading.local()


class CurrentUserMiddleware:
    """Inakumbuka mtumiaji wa ombi la sasa, ili signals zijue nani alifanya kitendo."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None


def current_request():
    return getattr(_local, 'request', None)


def _actor(actor):
    """(kind, name, email) ya aliyefanya kitendo."""
    if actor == 'system':
        return 'system', 'System', ''
    if isinstance(actor, tuple):                 # ('customer', 'Asha Mussa', 'asha@x') — bila akaunti
        return actor
    user = actor
    if user is None:
        req = current_request()
        user = getattr(req, 'user', None) if req is not None else None
    if user is None or not getattr(user, 'is_authenticated', False):
        return ('customer', 'Visitor', '') if current_request() is not None else ('system', 'System', '')
    name = (user.get_full_name() or user.get_username() or '').strip()
    kind = 'staff' if (user.is_staff or user.is_superuser) else 'customer'
    return kind, name, user.email or ''


def rule_mode(action):
    from apps.models import ActivityRule
    try:
        rule = ActivityRule.objects.filter(action=action).only('mode').first()
        if rule:
            return rule.mode
    except Exception:
        pass
    return DEFAULT_RULES.get(action, ('digest', ''))[0]


def ensure_rules():
    """Weka kila aina ya tukio kwenye Admin -> Activity settings (bila kubadilisha uliyochagua)."""
    from apps.models import ActivityRule
    for action, (mode, label) in DEFAULT_RULES.items():
        ActivityRule.objects.get_or_create(action=action, defaults={'mode': mode, 'label': label})


def record(action, title, rows=None, link='', level='info', actor=None, amount=None):
    """Rekodi tukio. Kamwe halirushi kosa."""
    try:
        from apps.models import ActivityEvent
        kind, name, email = _actor(actor)
        mode = rule_mode(action)
        event = ActivityEvent.objects.create(
            action=action[:60], actor_kind=kind, actor_name=name[:150], actor_email=email[:254],
            title=str(title)[:255], rows=[[str(k), str(v)] for k, v in (rows or [])],
            link=(link or '')[:500], level=level, amount=amount, mode=mode)
        if mode == 'instant':
            _send_later(event.pk)
        return event
    except Exception:
        logger.exception('Tukio halikurekodiwa: %s', action)
        return None


def _send_later(pk):
    """Email ya papo hapo baada ya transaction kukamilika, kwenye thread (Brevo isisubiriwe na ukurasa)."""
    from django.db import transaction

    def go():
        if getattr(settings, 'ACTIVITY_EMAIL_SYNC', False):
            send_instant(pk)
            return

        def run():
            from django.db import connection
            try:
                send_instant(pk)
            finally:
                connection.close()
        threading.Thread(target=run, daemon=True).start()
    transaction.on_commit(go)


def _site():
    return (getattr(settings, 'SITE_BASE_URL', '') or 'https://www.jamiitek.com').rstrip('/')


def send_instant(pk):
    from django.core.mail import EmailMultiAlternatives
    from django.utils import timezone
    from apps.models import ActivityEvent
    from apps.utils.customer_email import render_customer_email
    owner = (getattr(settings, 'OWNER_NOTICE_EMAIL', '') or '').strip()
    event = ActivityEvent.objects.filter(pk=pk, emailed_at__isnull=True).first()
    if not owner or not event:
        return False
    rows = [tuple(r) for r in (event.rows or [])]
    who = event.actor_name + (f' · {event.actor_email}' if event.actor_email else '')
    rows = ([('Done by', who)] if event.actor_kind != 'system' and who else []) + rows
    rows.append(('When', timezone.localtime(event.created_at).strftime('%d %b %Y, %H:%M')))
    link = event.link if event.link.startswith('http') else (_site() + event.link if event.link else '')
    chip_kind = {'danger': 'danger', 'warning': 'warning', 'success': 'success'}.get(event.level, 'info')
    text, html = render_customer_email(
        event.title, 'Hello,', rows=rows,
        label=f'{ACTOR_LABELS.get(event.actor_kind, "")} · {DEFAULT_RULES.get(event.action, ("", event.action))[1]}',
        chip=(ACTOR_LABELS.get(event.actor_kind, ''), chip_kind),
        button=('Open in Admin', link) if link else None,
    )
    msg = EmailMultiAlternatives(subject=event.title[:200], body=text, to=[owner],
                                 from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                                 headers={'X-JT-Owner-Notice': '1', 'X-JT-Category': 'activity'})
    msg.attach_alternative(html, 'text/html')
    if msg.send(fail_silently=True):
        ActivityEvent.objects.filter(pk=pk).update(emailed_at=timezone.now())
        return True
    return False


# ── Signals: matukio yanayogunduliwa yenyewe ────────────────────────

_OLD = '_jt_activity_old'


def connect():
    from django.contrib.admin.models import LogEntry
    from django.contrib.auth import get_user_model
    from django.contrib.auth.signals import user_logged_in
    from django.db.models.signals import post_save, pre_save

    User = get_user_model()

    def on_login(sender, request, user, **kw):
        staff = user.is_staff or user.is_superuser
        ua = (request.META.get('HTTP_USER_AGENT', '') if request else '')[:120]
        record('staff_login' if staff else 'customer_login',
               f'{user.get_full_name() or user.get_username()} signed in', actor=user,
               rows=[('Device', ua)] if ua else None)

    def on_user(sender, instance, created, raw=False, **kw):
        if created and not raw and not (instance.is_staff or instance.is_superuser):
            record('account_created', f'New account: {instance.get_full_name() or instance.get_username()}',
                   actor=instance, rows=[('Email', instance.email or '—'), ('Username', instance.get_username())],
                   link=f'/admin/auth/user/{instance.pk}/change/', level='success')

    def on_logentry(sender, instance, created, raw=False, **kw):
        if not created or raw:
            return
        what = f'{instance.content_type.name if instance.content_type else "item"}: {instance.object_repr}'[:200]
        if instance.is_deletion():
            record('admin_delete', f'Deleted in Admin — {what}', actor=instance.user, level='warning')
        else:
            verb = 'Added' if instance.is_addition() else 'Changed'
            record('admin_change', f'{verb} in Admin — {what}', actor=instance.user,
                   link=instance.get_admin_url() or '')

    user_logged_in.connect(on_login, dispatch_uid='activity_login', weak=False)
    post_save.connect(on_user, sender=User, dispatch_uid='activity_user', weak=False)
    post_save.connect(on_logentry, sender=LogEntry, dispatch_uid='activity_logentry', weak=False)

    # Mabadiliko ya hali: tunakumbuka thamani ya zamani kabla ya kuhifadhi
    def remember(field):
        def pre(sender, instance, raw=False, **kw):
            old = None
            if instance.pk and not raw:
                old = sender.objects.filter(pk=instance.pk).values_list(field, flat=True).first()
            setattr(instance, _OLD + field, old)
        return pre

    from apps.chatbot.models import ChatbotClient, SubscriptionPayment
    from apps.models import ManagedWebsite, PesapalTransaction
    from builder.models import ClientWebsite

    def on_pesapal(sender, instance, created, raw=False, **kw):
        old = getattr(instance, _OLD + 'status', None)
        if raw or instance.status == old:
            return
        who = ' '.join(p for p in (instance.first_name, instance.last_name) if p) or instance.email or instance.phone
        rows = [('Customer', f'{who} · {instance.email or instance.phone}'), ('For', instance.get_purpose_display()),
                ('Amount', f'{instance.currency} {instance.amount:,.0f}')]
        if instance.payment_method:
            rows.append(('Method', instance.payment_method))
        link = f'/admin/apps/pesapaltransaction/{instance.pk}/change/'
        if instance.status == 'completed':
            record('payment_completed', f'💰 {who} paid {instance.currency} {instance.amount:,.0f}', rows=rows,
                   link=link, level='success', actor='system', amount=instance.amount)
        elif instance.status in ('failed', 'reversed', 'invalid') and old is not None:
            record('payment_failed', f'Payment {instance.status} at Pesapal — {who}', rows=rows,
                   link=link, level='danger', actor='system')

    pre_save.connect(remember('status'), sender=PesapalTransaction, dispatch_uid='activity_pp_pre', weak=False)
    post_save.connect(on_pesapal, sender=PesapalTransaction, dispatch_uid='activity_pp', weak=False)

    def on_bot_payment(sender, instance, created, raw=False, **kw):
        if created and not raw:
            bot = instance.subscription.bot
            record('payment_submitted', f'JamiiBot payment to check: {bot.business_name} — TZS {instance.amount:,}',
                   rows=[('Bot', bot.bot_name), ('Reference', instance.transaction_ref),
                         ('Method', instance.payment_method), ('Months', instance.months_covered)],
                   link=f'/admin/chatbot/subscriptionpayment/{instance.pk}/change/', level='warning',
                   amount=instance.amount)

    post_save.connect(on_bot_payment, sender=SubscriptionPayment, dispatch_uid='activity_botpay', weak=False)

    def on_bot_client(sender, instance, created, raw=False, **kw):
        if created and not raw:
            record('bot_registered', f'New JamiiBot: {instance.business_name}', actor=instance.user,
                   rows=[('Owner', instance.full_name), ('Email', instance.email)],
                   link=f'/admin/chatbot/chatbotclient/{instance.pk}/change/', level='success')

    post_save.connect(on_bot_client, sender=ChatbotClient, dispatch_uid='activity_botclient', weak=False)

    def on_site(sender, instance, created, raw=False, **kw):
        old = getattr(instance, _OLD + 'is_published', None)
        if raw or not instance.is_published or old is not False:
            return
        owner = instance.owner
        record('website_published', f'Website published: {instance.site_name}',
               actor=owner, rows=[('Address', f'{instance.subdomain}.jamiitek.com'),
                                  ('Owner', f'{owner.get_full_name() or owner.username} · {owner.email}')],
               link='/manage/builder/', level='success')

    pre_save.connect(remember('is_published'), sender=ClientWebsite, dispatch_uid='activity_site_pre', weak=False)
    post_save.connect(on_site, sender=ClientWebsite, dispatch_uid='activity_site', weak=False)

    def on_managed(sender, instance, created, raw=False, **kw):
        old = getattr(instance, _OLD + 'status', None)
        if raw or old is None or instance.status == old:
            return
        rows = [('Website', instance.name), ('Client', getattr(instance.client, 'name', '—'))]
        reason = getattr(instance, 'suspension_reason', '') or ''
        if instance.status == 'suspended':
            if reason:
                rows.append(('Reason', reason[:200]))
            record('website_suspended', f'⛔ Website suspended: {instance.name}', rows=rows,
                   link=f'/manage/websites/{instance.pk}/', level='danger')
        elif old == 'suspended' and instance.status == 'active':
            record('website_restored', f'✓ Website restored: {instance.name}', rows=rows,
                   link=f'/manage/websites/{instance.pk}/', level='success')

    pre_save.connect(remember('status'), sender=ManagedWebsite, dispatch_uid='activity_mw_pre', weak=False)
    post_save.connect(on_managed, sender=ManagedWebsite, dispatch_uid='activity_mw', weak=False)
