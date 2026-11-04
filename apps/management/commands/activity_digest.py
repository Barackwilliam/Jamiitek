"""
Muhtasari wa matukio ya siku kwa mmiliki (apps/activity.py).

Inaendeshwa kila dakika 30 na apps/daily_tasks.py; inatuma mara MOJA kwa siku, saa ACTIVITY_DIGEST_HOUR
(20:00 kwa kawaida) au baadaye. Matukio yenye mode 'off' hayamo.

    python manage.py activity_digest            # kama muda umefika na haijatumwa leo
    python manage.py activity_digest --force    # sasa hivi (majaribio)
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

GROUPS = (('customer', '👤 Customers', '#0369a1'), ('staff', '🛠 You & staff', '#6d28d9'), ('system', '🤖 System', '#334155'))
PER_GROUP = 8


def _money(v):
    v = float(v or 0)
    return f'TZS {v / 1000:,.0f}K' if v >= 10000 else f'TZS {v:,.0f}'


class Command(BaseCommand):
    help = "Tuma muhtasari wa matukio ya leo kwa mmiliki"

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **opts):
        from django.core.mail import EmailMultiAlternatives
        from django.db.models import Sum
        from django.template.loader import render_to_string
        from django.utils.html import strip_tags
        from apps.activity import ensure_rules
        from apps.models import ActivityDigest, ActivityEvent, OwnerNoticeDay

        now = timezone.localtime()
        day = now.date()
        owner = (getattr(settings, 'OWNER_NOTICE_EMAIL', '') or '').strip()
        hour = int(getattr(settings, 'ACTIVITY_DIGEST_HOUR', 20))
        if not owner or (not opts['force'] and now.hour < hour):
            return
        log, _ = ActivityDigest.objects.get_or_create(date=day)
        if log.sent_at and not opts['force']:
            return
        ensure_rules()

        events = ActivityEvent.objects.filter(created_at__date=day).exclude(mode='off')
        groups = []
        for kind, label, color in GROUPS:
            qs = events.filter(actor_kind=kind)
            count = qs.count()
            items = [{'title': e.title, 'time': timezone.localtime(e.created_at).strftime('%H:%M')}
                     for e in qs.order_by('-created_at')[:PER_GROUP]]
            groups.append({'label': label, 'color': color, 'count': count, 'items': items,
                           'more': max(count - PER_GROUP, 0)})

        # Takwimu ambazo hazihitaji tukio kwa kila kitu (zingejaza kumbukumbu)
        try:
            from apps.chatbot.models import Message
            replies = Message.objects.filter(role='assistant', created_at__date=day).count()
        except Exception:
            replies = 0
        emails = OwnerNoticeDay.objects.filter(date=day).values_list('sent_total', flat=True).first() or 0
        paid = events.filter(action='payment_completed').aggregate(s=Sum('amount'))['s'] or 0
        stats = [
            {'value': _money(paid), 'label': 'Payments', 'color': '#16a34a'},
            {'value': events.filter(action='account_created').count(), 'label': 'New accounts', 'color': '#0891b2'},
            {'value': replies, 'label': 'Bot replies', 'color': '#6d28d9'},
            {'value': events.filter(level='danger').count(), 'label': 'Problems', 'color': '#dc2626'},
        ]
        if emails:
            groups[2]['items'].insert(0, {'title': f'{emails} emails sent by the system today', 'time': 'all day'})

        total = events.count()
        base = (getattr(settings, 'SITE_BASE_URL', '') or 'https://www.jamiitek.com').rstrip('/')
        subject = f'📅 Today on JamiiTek — {total} action{"" if total == 1 else "s"} ({day:%d %b})'
        html = render_to_string('emails/activity_digest.html', {
            'subject': subject, 'day': day, 'total': total, 'stats': stats, 'groups': groups,
            'activity_url': f'{base}/admin/apps/activityevent/'})
        msg = EmailMultiAlternatives(subject=subject, body=strip_tags(html), to=[owner],
                                     from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                                     headers={'X-JT-Owner-Notice': '1', 'X-JT-Category': 'activity'})
        msg.attach_alternative(html, 'text/html')
        if msg.send(fail_silently=True):
            ActivityDigest.objects.filter(pk=log.pk).update(sent_at=timezone.now(), events=total)
        if not opts['quiet']:
            self.stdout.write(f'Muhtasari: matukio {total}')
