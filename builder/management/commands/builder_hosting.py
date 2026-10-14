"""
python manage.py builder_hosting [--dry-run]   (inaendeshwa kila siku — apps/daily_tasks.py)

Hosting ya mwaka ya website za Builder zilizolipiwa (builder/billing.py):
  • Email ya ukumbusho siku 30, 7, 1 kabla ya kuisha, na siku inayoisha. Kila
    ukumbusho unatumwa MARA MOJA kwa kila tarehe ya mwisho (theme_settings['renew_sent']).
  • Website ya "Remove logo" (si template iliyonunuliwa) ambayo haijalipiwa siku
    GRACE_DAYS baada ya kuisha → inarudi kuwa ya bure: logo inarudi na domain yake
    inaacha kufanya kazi. Template iliyonunuliwa inasimama yenyewe (billing.is_paused).
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from builder import billing
from builder.models import ClientWebsite

REMIND_AT = (30, 7, 1, 0)

SUBJECT = 'Your website {site}: hosting ends {when}'
BODY = """Hello {name},

The hosting for your website {site} ends on {date}.

Pay TSh {price} for next year to keep your website online, with no JamiiTek logo
and your own name. You can pay with M-Pesa, Tigo Pesa, Airtel Money or card:

{link}

{after}

Thank you,
JamiiTek
"""


class Command(BaseCommand):
    help = 'Hosting reminders for paid Builder websites, and end of unpaid "Remove logo".'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **opts):
        price = billing.pricing().yearly_hosting_price
        if not price:
            self.stdout.write('Next year hosting price ni 0 — hakuna cha kufanya.')
            return
        today = timezone.localdate()
        sent = ended = 0
        for site in ClientWebsite.objects.filter(is_premium=True, hosting_until__isnull=False).select_related('owner'):
            left = (site.hosting_until - today).days

            # 1. Ukumbusho
            if left in REMIND_AT and site.owner.email:
                ts = dict(site.theme_settings or {})
                done = ts.get('renew_sent') or {}
                key = site.hosting_until.isoformat()
                if left not in done.get(key, []):
                    when = 'today' if left == 0 else ('tomorrow' if left == 1 else f'in {left} days')
                    after = (f'If you do not pay within {billing.GRACE_DAYS} days after that, your website will be paused.'
                             if site.paid_template_id else
                             f'If you do not pay within {billing.GRACE_DAYS} days after that, the JamiiTek logo comes back '
                             f'and your own name stops working.')
                    self.stdout.write(f'{"(dry-run) " if dry_run else ""}→ {site.owner.email}: {site.subdomain} ({when})')
                    if not dry_run:
                        send_mail(SUBJECT.format(site=f'{site.subdomain}.jamiitek.com', when=when),
                                  BODY.format(name=site.owner.first_name or site.owner.username,
                                              site=f'{site.subdomain}.jamiitek.com',
                                              date=site.hosting_until.strftime('%-d %B %Y'), price=f'{price:,}',
                                              link=f'https://www.jamiitek.com/builder/site/{site.id}/pay/renew/',
                                              after=after),
                                  settings.DEFAULT_FROM_EMAIL, [site.owner.email])
                        done[key] = sorted(set(done.get(key, [])) | {left})
                        ts['renew_sent'] = done
                        ClientWebsite.objects.filter(pk=site.pk).update(theme_settings=ts)
                    sent += 1

            # 2. "Remove logo" ambayo haijalipiwa → inarudi kuwa ya bure
            if not site.paid_template_id and left < -billing.GRACE_DAYS:
                self.stdout.write(f'{"(dry-run) " if dry_run else ""}✕ {site.subdomain}: premium imeisha')
                if not dry_run:
                    ClientWebsite.objects.filter(pk=site.pk).update(is_premium=False)
                    site.bump_version()
                ended += 1
        self.stdout.write(self.style.SUCCESS(f'Ukumbusho {sent}, premium zilizoisha {ended}.'))
