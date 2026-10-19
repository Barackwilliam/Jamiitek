"""
python manage.py builder_unpaid [--dry-run]   (inaendeshwa kila siku — apps/daily_tasks.py)

Mtu ameanzisha website kwa template INAYOUZWA kwenye Builder lakini hajalipa (haijaenda
hewani). Ana nia kubwa — ameshaweka jina lake — kwa hiyo tunamkumbusha kwa email:

  1. siku 1 baada ya kuanza   — "website yako iko tayari kwenda hewani"
  2. siku 3 baada ya kuanza   — ukumbusho wa mwisho, kisha kimya

Kila email inatumwa mara moja (theme_settings['pay_reminders']). Website za zaidi ya siku
MAX_AGE_DAYS hazitumiwi kitu (hata siku ya kwanza amri hii inapowekwa). Kila email ina
kiungo cha kusitisha ukumbusho (theme_settings['pay_reminders_off']).
"""
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from builder import billing
from builder.models import ClientWebsite

BASE = 'https://www.jamiitek.com'
STEPS = ((1, 1), (2, 3))          # (ukumbusho, siku tangu kuanza)
MAX_AGE_DAYS = 10
STOP_SALT = 'builder-unpaid-stop'

SUBJECTS = {
    1: 'Your website {site} is ready to go online',
    2: 'Last reminder: {site} is still waiting to go online',
}
FOOTER = """Thank you,
JamiiTek

—
You get this email because you started a website on JamiiTek.
Stop these reminders: {stop_link}
"""


def stop_token(site):
    return signing.dumps({'s': site.pk}, salt=STOP_SALT)


def site_from_stop_token(token):
    try:
        return ClientWebsite.objects.filter(pk=signing.loads(token, salt=STOP_SALT)['s']).first()
    except (signing.BadSignature, KeyError, TypeError):
        return None


def due_step(site, now):
    """Ukumbusho unaopaswa kutumwa sasa (1 au 2), au None. Ukichelewa, wa mwisho tu unatumwa."""
    age = now - site.created_at
    if age > timedelta(days=MAX_AGE_DAYS):
        return None
    sent = set((site.theme_settings or {}).get('pay_reminders') or [])
    due = None
    for step, days in STEPS:
        if age >= timedelta(days=days) and step not in sent:
            due = step
    return due


class Command(BaseCommand):
    help = 'Email reminders for Builder websites made with a paid template that are not paid yet.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **opts):
        now = timezone.now()
        pricing = billing.pricing()
        sites = (ClientWebsite.objects
                 .filter(is_published=False, created_at__gte=now - timedelta(days=MAX_AGE_DAYS),
                         created_at__lte=now - timedelta(days=STEPS[0][1]))
                 .select_related('owner'))
        sent = 0
        for site in sites:
            ts = dict(site.theme_settings or {})
            owner = site.owner
            if ts.get('pay_reminders_off') or not owner.is_active or not owner.email:
                continue
            tpl = billing.needs_payment(site)
            step = due_step(site, now) if tpl else None
            if not step:
                continue
            name = site.site_name or f'{site.subdomain}.jamiitek.com'
            self.stdout.write(f'{"(dry-run) " if dry_run else ""}→ {owner.email}: {site.subdomain} (#{step})')
            if not dry_run:
                build_url = (reverse('build_for_me', args=[tpl.slug]) if pricing.build_fee and tpl.slug
                             else f"{reverse('select_website')}?template={tpl.pk}")
                hosting = (f', with the first year of hosting included. From year 2 hosting is '
                           f'TSh {pricing.yearly_hosting_price:,} per year' if pricing.yearly_hosting_price
                           else ', hosting included')
                paras = [
                    f'Hello {owner.first_name or owner.username},',
                    (f'Your website {name} with the {tpl.name} design is saved and ready.' if step == 1 else
                     f'Your website {name} with the {tpl.name} design is still saved, but it is not online yet.'),
                    f'Put it online for TSh {tpl.price:,} (one time){hosting}. '
                    f'You can pay with M-Pesa, Tigo Pesa, Airtel Money or card:\n'
                    + BASE + reverse('builder:checkout', args=[site.id, 'template']),
                    'Or keep editing first — everything you did is saved:\n'
                    + BASE + reverse('builder:site_dashboard', args=[site.id]),
                    f'No time to finish it? Our team can build it for you:\n{BASE}{build_url}',
                ]
                if step == 2:
                    paras.append('This is the last reminder we send about this website.')
                paras.append(FOOTER.format(stop_link=BASE + reverse('builder:unpaid_stop', args=[stop_token(site)])))
                send_mail(
                    SUBJECTS[step].format(site=name),
                    '\n\n'.join(paras),
                    settings.DEFAULT_FROM_EMAIL, [owner.email])
                ts['pay_reminders'] = sorted({s for s, _ in STEPS if s <= step} | set(ts.get('pay_reminders') or []))
                ClientWebsite.objects.filter(pk=site.pk).update(theme_settings=ts)
            sent += 1
        self.stdout.write(self.style.SUCCESS(f'Ukumbusho wa kulipa: {sent}.'))
