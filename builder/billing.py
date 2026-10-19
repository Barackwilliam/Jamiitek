"""
Malipo ya Builder — Pesapal pekee (hakuna WhatsApp wala "weka amelipa" kwa mkono).

Mambo mawili yanalipiwa, kila moja mara MOJA:

  1. Template INAYOUZWA (WebsiteTemplate.for_sale). Mteja anaijaribu bure kwenye
     Builder; anapobonyeza Publish analipa bei ya template. Malipo yakithibitishwa:
     website inakwenda hewani, hakuna "Developed by JamiiTek", anaweza kuweka domain
     yake (is_premium), na hosting ya mwaka 1.
  2. "Remove JamiiTek logo" — kwa website ya template ya BURE. Bei moja iliyowekwa
     na mmiliki (BuilderPricing.remove_logo_price).

  3. Hosting ya mwaka unaofuata (BuilderPricing.yearly_hosting_price) — email za
     ukumbusho siku 30/7/1/0 kabla (manage.py builder_hosting, kila siku). Baada ya
     siku GRACE_DAYS bila kulipa: website ya template iliyonunuliwa inasimama
     (is_paused), na ya "Remove logo" inarudi kuwa ya bure (logo inarudi).

Website za bure zinaonyesha "Developed by JamiiTek" chini (builder/branding.py, kupitia
SubdomainMiddleware); website iliyolipiwa (is_premium) haionyeshi alama hiyo.

Malipo: apps.pesapal_views._start → Pesapal → callback/IPN → apps.pesapal_fulfill
→ fulfill() hapa chini (mara moja tu, ndani ya lock).
"""
from datetime import timedelta

from django.utils import timezone

HOSTING_DAYS = 365
GRACE_DAYS = 7


def pricing():
    from .models import BuilderPricing
    return BuilderPricing.get()


def source_template(site):
    """Template ya marketplace ambayo website hii ilitoka nayo (au None)."""
    from apps.models import WebsiteTemplate
    src = (site.theme_settings or {}).get('source_template') or {}
    pk = src.get('id')
    if not isinstance(pk, int):
        return None
    return WebsiteTemplate.objects.defer('preview_html', 'long_description').filter(pk=pk).first()


def needs_payment(site):
    """Template inayouzwa ambayo bado haijalipiwa kwa website hii — au None."""
    tpl = source_template(site)
    if tpl and tpl.for_sale and site.paid_template_id != tpl.pk:
        return tpl
    return None


def logo_price(site):
    """Bei ya kuondoa logo kwa website hii, au 0 kama haihusiki."""
    if site.is_premium or needs_payment(site):
        return 0
    return pricing().remove_logo_price


def renew_price(site):
    """Ada ya mwaka unaofuata kwa website hii, au 0 kama haihusiki."""
    if not site.hosting_until:
        return 0
    return pricing().yearly_hosting_price


def days_left(site):
    """Siku zilizobaki za hosting iliyolipiwa (hasi = imeisha), au None."""
    if not site.hosting_until or not renew_price(site):
        return None
    return (site.hosting_until - timezone.localdate()).days


def is_paused(site):
    """Template iliyonunuliwa, hosting imeisha zaidi ya GRACE_DAYS na haijalipiwa."""
    left = days_left(site)
    return bool(site.paid_template_id and left is not None and left < -GRACE_DAYS)


def show_badge(site):
    """Website za bure zina "Developed by JamiiTek" (builder/branding.py); zilizolipiwa hazina."""
    return not site.is_premium


# ── Malipo ────────────────────────────────────────────────

def start(request, site, kind):
    """Anzisha malipo ya Pesapal. kind = 'template', 'logo' au 'renew'. Inarudisha HttpResponse."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from apps.pesapal_models import PesapalTransaction
    from apps.pesapal_views import _start

    if kind == 'template':
        tpl = needs_payment(site)
        if not tpl:
            return redirect('builder:site_dashboard', site_id=site.id)
        purpose, amount, plan_id = 'builder_template', tpl.price, tpl.pk
        description = f'Website template: {tpl.name}'
    elif kind == 'renew':
        amount = renew_price(site)
        if not amount:
            return redirect('builder:site_dashboard', site_id=site.id)
        purpose, plan_id = 'builder_renew', None
        description = f'Website hosting, 1 year: {site.subdomain}.jamiitek.com'
    else:
        amount = logo_price(site)
        if not amount:
            return redirect('builder:site_dashboard', site_id=site.id)
        purpose, plan_id = 'builder_logo', None
        description = f'Remove JamiiTek logo: {site.subdomain}.jamiitek.com'
    if amount <= 0:
        messages.error(request, 'This item has no price yet. Please contact JamiiTek.')
        return redirect('builder:site_dashboard', site_id=site.id)

    user = request.user
    tx = PesapalTransaction(
        purpose=purpose, target_id=str(site.pk), plan_id=plan_id, amount=amount, currency='TZS',
        description=description[:200], email=user.email or '',
        phone=(site.contact_phone or site.whatsapp_number or '')[:30],
        first_name=(user.first_name or user.username)[:80], last_name=(user.last_name or '')[:80],
    )
    return _start(tx, request)


def fulfill(tx):
    """Inaitwa na apps.pesapal_fulfill (ndani ya lock, mara moja). False = website haipo."""
    from .models import ClientWebsite

    site = ClientWebsite.objects.select_for_update().filter(pk=tx.target_id).first()
    if site is None:
        return False
    today = timezone.localdate()
    base = site.hosting_until if site.hosting_until and site.hosting_until > today else today
    site.hosting_until = base + timedelta(days=HOSTING_DAYS)
    site.is_premium = True
    fields = ['is_premium', 'hosting_until']
    if tx.purpose == 'builder_template':
        site.paid_template_id = tx.plan_id
        site.is_published = True          # amelipa ili iende hewani — inakwenda mara moja
        fields += ['paid_template_id', 'is_published']
    site.save(update_fields=fields)
    site.bump_version()
    if tx.purpose == 'builder_template':
        from apps import template_funnel
        template_funnel.count(tx.plan_id, 'paid')      # hatua ya 4 ya mauzo
    return True
