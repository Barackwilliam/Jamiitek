"""Kagua domain za wateja ambazo bado hazijawa Live.

Inaendeshwa na DailyTasksMiddleware (apps/daily_tasks.py). Domain zilizo
Live zinakaguliwa mara chache zaidi — mara moja kwa siku inatosha
kugundua kama mteja amebadilisha DNS yake.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from builder import domains
from builder.models import ClientWebsite


class Command(BaseCommand):
    help = 'Kagua hali ya custom domains za wateja wa builder'

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        now = timezone.now()
        qs = (ClientWebsite.objects.exclude(custom_domain__isnull=True).exclude(custom_domain='')
              .filter(
                  # Zisizo Live: kila dakika 15. Zilizo Live: mara moja kwa siku.
                  Q(domain_checked_at__isnull=True) |
                  (~Q(domain_status='active') & Q(domain_checked_at__lt=now - timedelta(minutes=15))) |
                  (Q(domain_status='active') & Q(domain_checked_at__lt=now - timedelta(hours=24)))
              ))[:20]          # kikomo — kila ukaguzi unaweza kuchukua sekunde 10

        changed = 0
        for site in qs:
            before = site.domain_status
            status, _msg = domains.check(site)
            if status != before:
                changed += 1
                if status == 'active':
                    _notify_live(site)
        if not opts['quiet']:
            self.stdout.write(f'Domains zimekaguliwa · {changed} zimebadilika hali')


def _notify_live(site):
    """Mjulishe mteja (mwenye website) kwamba domain yake imekuwa live — habari njema inastahili taarifa.

    Awali taarifa hii ilienda kwa JamiiTek peke yake (notify), na mteja hakujua. Sasa anapata email yeye
    mwenyewe; JamiiTek inaendelea kupata taarifa fupi kama kumbukumbu.
    """
    owner = getattr(site, 'owner', None)
    to = (getattr(owner, 'email', '') or '').strip()
    if to:
        try:
            from django.conf import settings
            from django.core.mail import send_mail
            name = (getattr(owner, 'first_name', '') or getattr(owner, 'username', '') or '').strip()
            send_mail(
                f'🌐 {site.custom_domain} is now live',
                (f'Hi {name},\n\n' if name else 'Hi,\n\n')
                + f'Good news: your website {site.site_name} now opens at https://{site.custom_domain}\n\n'
                + '— JamiiTek Team',
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'JamiiTek <info@jamiitek.com>'), [to],
                fail_silently=True,
            )
        except Exception:
            pass
    try:
        from apps.notify import notify
        notify(f'🌐 {site.custom_domain} sasa iko LIVE — website ya {site.site_name}'
               + (f' (mteja amejulishwa: {to}).' if to else ' (mteja hana email — mjulishe mwenyewe).'))
    except Exception:
        pass
