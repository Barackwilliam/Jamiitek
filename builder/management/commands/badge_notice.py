"""
python manage.py badge_notice [--dry-run]

Tuma taarifa (email) kwa wamiliki wa website za bure zilizokuwepo kabla ya mfumo
wa malipo: kuanzia BuilderPricing.badge_old_sites_from, website zao zitaonyesha
"Made with JamiiTek". Kila mmiliki anapata email MOJA (inakumbukwa kwenye
theme_settings['badge_notice']), hata ukiendesha command mara kadhaa.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from builder.billing import pricing
from builder.models import ClientWebsite

SUBJECT = 'Your JamiiTek website: a small change on {date}'
BODY = """Hello {name},

Thank you for building your website with JamiiTek.

From {date}, free websites will show a small "Made with JamiiTek" sign at the bottom:
{sites}

Do you want your website without the sign? Open your website in the Builder and tap
"Remove logo". You pay one time (TSh {price}) with M-Pesa, Tigo Pesa, Airtel Money or card.
You can also use your own name, like yourbusiness.co.tz.

{link}

Thank you,
JamiiTek
"""


class Command(BaseCommand):
    help = 'Email owners of old free websites before "Made with JamiiTek" starts showing.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show who would get the email, send nothing.')

    def handle(self, *args, dry_run=False, **opts):
        p = pricing()
        if not p.badge_old_sites_from:
            raise CommandError('Weka tarehe kwanza: Admin → Builder pricing → "Old free sites show the logo from".')
        date = p.badge_old_sites_from.strftime('%-d %B %Y')
        sites = (ClientWebsite.objects.filter(legacy_free=True, is_premium=False, is_published=True)
                 .select_related('owner').order_by('owner_id'))
        by_owner = {}
        for s in sites:
            if (s.theme_settings or {}).get('badge_notice'):
                continue
            by_owner.setdefault(s.owner, []).append(s)

        sent = 0
        for owner, owned in by_owner.items():
            if not owner.email:
                self.stdout.write(f'– {owner.username}: hana email, imerukwa')
                continue
            msg = BODY.format(
                name=owner.first_name or owner.username, date=date,
                sites='\n'.join(f'  • {s.subdomain}.jamiitek.com' for s in owned),
                price=f'{p.remove_logo_price:,}' if p.remove_logo_price else '—',
                link='https://www.jamiitek.com/builder/')
            self.stdout.write(f'{"(dry-run) " if dry_run else ""}→ {owner.email}: {len(owned)} website')
            if dry_run:
                continue
            send_mail(SUBJECT.format(date=date), msg, settings.DEFAULT_FROM_EMAIL, [owner.email])
            for s in owned:
                ts = dict(s.theme_settings or {})
                ts['badge_notice'] = date
                ClientWebsite.objects.filter(pk=s.pk).update(theme_settings=ts)
            sent += 1
        self.stdout.write(self.style.SUCCESS(f'Imekamilika: email {sent} zimetumwa.'))
