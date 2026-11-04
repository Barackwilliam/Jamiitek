"""
Muhtasari wa email za wateja kwa mmiliki.

Email za siku zikifika OWNER_NOTICE_DAILY_LIMIT (150), taarifa za moja moja ("X was sent: ...") zinasimama
na kila email ya mteja inayofuata inahifadhiwa kwenye OwnerNoticeDay.held. Amri hii (inaendeshwa kila dakika
30 na apps/daily_tasks.py) inatuma muhtasari MMOJA wa siku zilizokwisha, kisha inaweka alama isirudie.

    python manage.py owner_notice_summary
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Tuma muhtasari wa email za wateja zilizozidi kikomo cha taarifa za siku"

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        from apps.models import OwnerNoticeDay
        from apps.utils.customer_email import render_customer_email
        from django.core.mail import EmailMultiAlternatives

        owner = (getattr(settings, 'OWNER_NOTICE_EMAIL', '') or '').strip()
        sent = 0
        days = OwnerNoticeDay.objects.filter(date__lt=timezone.localdate(), summary_sent_at__isnull=True)
        for day in days.order_by('date'):
            items = list(day.held or [])
            if not items or not owner:
                OwnerNoticeDay.objects.filter(pk=day.pk).update(summary_sent_at=timezone.now())
                continue
            count = len(items)
            lines = '\n'.join(f"• {i.get('time', '')} — {i.get('to', '')}: {i.get('about', '')} "
                              f"(“{i.get('subject', '')}”)" for i in items)
            subject = f"📊 Summary: {count} customer email{'' if count == 1 else 's'} on {day.date:%d %b %Y}"
            text, html = render_customer_email(
                subject,
                f"Hello,\n\nOn {day.date:%d %B %Y} the system reached the daily limit of "
                f"{getattr(settings, 'OWNER_NOTICE_DAILY_LIMIT', 150)} emails, so the individual notices were "
                f"paused. These are the customer emails sent after that point:\n\n{lines}",
                rows=[('Customer emails in this summary', count), ('All emails sent that day', day.sent_total),
                      ('Individual notices sent', day.notices)],
                label='Daily summary', chip=(f'📊 {count} email{"" if count == 1 else "s"}', 'info'),
            )
            msg = EmailMultiAlternatives(subject=subject, body=text, to=[owner],
                                         from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                                         headers={'X-JT-Owner-Notice': '1', 'X-JT-Category': 'owner_notice'})
            msg.attach_alternative(html, 'text/html')
            if msg.send(fail_silently=True):
                OwnerNoticeDay.objects.filter(pk=day.pk).update(summary_sent_at=timezone.now())
                sent += 1
        if not opts.get('quiet'):
            self.stdout.write(f'Muhtasari uliotumwa: {sent}')
