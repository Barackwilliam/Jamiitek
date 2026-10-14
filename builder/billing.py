"""
Malipo ya Builder — Pesapal pekee (hakuna WhatsApp wala "weka amelipa" kwa mkono).

Mambo mawili yanalipiwa, kila moja mara MOJA:

  1. Template INAYOUZWA (WebsiteTemplate.for_sale). Mteja anaijaribu bure kwenye
     Builder; anapobonyeza Publish analipa bei ya template. Malipo yakithibitishwa:
     website inakwenda hewani, hakuna "Made with JamiiTek", anaweza kuweka domain
     yake (is_premium), na hosting ya mwaka 1.
  2. "Remove JamiiTek logo" — kwa website ya template ya BURE. Bei moja iliyowekwa
     na mmiliki (BuilderPricing.remove_logo_price).

Website za bure zinaonyesha kibandiko kidogo "Made with JamiiTek" (with_badge).
Website zilizokuwepo kabla ya mfumo huu (legacy_free) haziguswi hadi tarehe ya
BuilderPricing.badge_old_sites_from — baada ya kupewa taarifa.

Malipo: apps.pesapal_views._start → Pesapal → callback/IPN → apps.pesapal_fulfill
→ fulfill() hapa chini (mara moja tu, ndani ya lock).
"""
from datetime import timedelta
from functools import wraps

from django.utils import timezone
from django.utils.html import escape

HOSTING_DAYS = 365


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


def show_badge(site):
    if site.is_premium:
        return False
    if site.legacy_free:
        start = pricing().badge_old_sites_from
        return bool(start and timezone.localdate() >= start)
    return True


def badge_html(site):
    href = ('https://www.jamiitek.com/templates/?utm_source=madewith&amp;utm_medium=badge'
            f'&amp;utm_campaign={escape(site.subdomain)}')
    return (
        '<a href="' + href + '" target="_blank" rel="noopener" id="jt-made-with" '
        'style="all:initial;position:fixed;left:12px;bottom:12px;z-index:2147480000;display:inline-flex;'
        'align-items:center;gap:6px;padding:7px 11px;border-radius:999px;background:rgba(10,12,20,.9);'
        'color:#fff;font:600 12px/1 system-ui,-apple-system,sans-serif;cursor:pointer;'
        'box-shadow:0 6px 18px rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.15)">'
        '<span style="all:initial;width:8px;height:8px;border-radius:50%;background:#25d366"></span>'
        '<span style="all:initial;color:#fff;font:600 12px/1 system-ui,-apple-system,sans-serif">'
        'Made with <b style="all:initial;color:#fff;font:800 12px/1 system-ui,-apple-system,sans-serif">'
        'JamiiTek</b></span></a>'
    )


def with_badge(view):
    """Weka "Made with JamiiTek" kwenye kurasa za website za bure zilizochapishwa."""
    @wraps(view)
    def inner(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        site = getattr(request, 'client_site', None)
        if (site is None or not site.is_published or response.status_code != 200
                or response.streaming or 'text/html' not in response.get('Content-Type', '')):
            return response
        if not show_badge(site):
            return response
        body = response.content.decode(response.charset or 'utf-8', errors='replace')
        i = body.lower().rfind('</body>')
        snippet = badge_html(site)
        body = body[:i] + snippet + body[i:] if i >= 0 else body + snippet
        response.content = body.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
    return inner


# ── Malipo ────────────────────────────────────────────────

def start(request, site, kind):
    """Anzisha malipo ya Pesapal. kind = 'template' au 'logo'. Inarudisha HttpResponse."""
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
    return True
