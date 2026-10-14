"""
Public site rendering — views hizi zinatumika TU wakati request imekuja
kupitia subdomain ya mteja (SubdomainMiddleware ime-set request.client_site
na request.urlconf = 'builder.public_urls').
"""
from builder.images import image_url
from django.http import Http404, HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .rendering import (render_page_html, render_raw_document, render_shortcodes,
                        render_inquiry_form)


def _get_site(request):
    site = getattr(request, 'client_site', None)
    if site is None:
        raise Http404
    return site


def _strip_html(text, limit=160):
    """Meta description safi kutoka HTML/text."""
    import re
    clean = re.sub(r'<[^>]+>', ' ', str(text or ''))
    clean = re.sub(r'\[\[[^\]]+\]\]', ' ', clean)   # ondoa shortcodes
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean[:limit - 1] + '…') if len(clean) > limit else clean


def _base_url(site):
    if site.is_premium and site.custom_domain:
        return f'https://{site.custom_domain}'
    return site.public_url


def _ctx(site, extra=None):
    ctx = {
        'site': site,
        'nav_pages': site.pages.filter(show_in_nav=True).only(
            'slug', 'title', 'sort_order'
        ),
        # ── SEO defaults (views zina-override kwa page husika) ──
        'meta_title': site.site_name,
        'meta_description': _strip_html(site.tagline or site.site_name),
        'meta_image': image_url(site.logo_url, 1200),
        'meta_url': _base_url(site),
        'base_url': _base_url(site),
    }
    # Custom navbar/footer (au preset) — page_slug kwa 'on' highlighting
    from .nav_presets import render_nav, render_footer
    _pslug = (extra or {}).get('page').slug if extra and extra.get('page') else None
    nav_html, nav_css = render_nav(site, _pslug)
    foot_html, foot_css = render_footer(site, _pslug)
    ctx['custom_nav_html'] = nav_html
    ctx['custom_nav_css'] = nav_css
    ctx['custom_footer_html'] = foot_html
    ctx['custom_footer_css'] = foot_css
    from .layouts import font_for
    ctx['font_href'], ctx['font_body'], ctx['font_head'] = font_for(site)

    if extra:
        ctx.update(extra)
    return ctx


def _check_published(request, site):
    """Site ambayo haijapublishiwa: "coming soon" kwa kila mtu isipokuwa staff."""
    # Subdomain inaonyesha website iliyopublishiwa TU — hata kwa mmiliki.
    # Mmiliki anaangalia draft kwenye preview ya Studio; hapa anaelezwa hilo.
    if site.is_published:
        # Template iliyonunuliwa, hosting imeisha na haijalipiwa: website imesimama
        from .billing import is_paused
        if is_paused(site) and not (request.user.is_authenticated and request.user.is_staff):
            is_owner = request.user.is_authenticated and request.user == site.owner
            return render(request, 'builder/public/paused.html', {'site': site, 'is_owner': is_owner}, status=503)
        return None
    if request.user.is_authenticated and request.user.is_staff:
        return None
    is_owner = request.user.is_authenticated and request.user == site.owner
    return render(request, 'builder/public/coming_soon.html',
                  {'site': site, 'is_owner': is_owner}, status=200)


def home(request):
    site = _get_site(request)
    blocked = _check_published(request, site)
    if blocked:
        return blocked
    page = site.pages.filter(slug='home').first() or site.pages.first()
    if page is None:
        raise Http404
    if page.raw_document:
        return HttpResponse(render_raw_document(site, page))
    return render(request, 'builder/public/page.html', _ctx(site, {
        'page': page,
        'page_html': render_page_html(site, page),
    }))


def page_view(request, slug):
    site = _get_site(request)
    blocked = _check_published(request, site)
    if blocked:
        return blocked
    page = get_object_or_404(site.pages, slug=slug)
    if page.raw_document:
        return HttpResponse(render_raw_document(site, page))
    return render(request, 'builder/public/page.html', _ctx(site, {
        'page': page,
        'page_html': render_page_html(site, page),
        'meta_title': f'{page.title} · {site.site_name}',
        'meta_description': _strip_html(page.html_cache) or _strip_html(site.tagline or site.site_name),
        'meta_url': f'{_base_url(site)}/p/{page.slug}/',
    }))


def collection_list(request, col_slug):
    site = _get_site(request)
    blocked = _check_published(request, site)
    if blocked:
        return blocked
    collection = get_object_or_404(site.collections, slug=col_slug)
    body = render_shortcodes(site, f'[[collection:{col_slug}]]')
    return render(request, 'builder/public/collection.html', _ctx(site, {
        'collection': collection,
        'body': body,
        'meta_title': f'{collection.name} · {site.site_name}',
        'meta_url': f'{_base_url(site)}/c/{collection.slug}/',
    }))


def item_detail(request, col_slug, item_slug):
    site = _get_site(request)
    blocked = _check_published(request, site)
    if blocked:
        return blocked
    collection = get_object_or_404(site.collections, slug=col_slug)
    item = get_object_or_404(
        collection.items, slug=item_slug, is_visible=True
    )
    # Panga fields kwa mpangilio wa schema, kwa display safi
    display_fields = []
    for f in collection.fields:
        value = item.data.get(f['key'])
        if value:
            display_fields.append({
                'label': f.get('label', f['key']),
                'type': f.get('type', 'text'),
                'value': value,
            })
    wa = (site.whatsapp_number or site.contact_phone or '').replace('+', '').replace(' ', '')
    wa_link = ''
    if wa:
        msg = f'Hello, I would like to enquire about: {item.title}'
        wa_link = f'https://wa.me/{wa}?text={msg.replace(" ", "%20")}'
    item_desc = ''
    if isinstance(item.data, dict):
        item_desc = item.data.get('description', '')
    return render(request, 'builder/public/item_detail.html', _ctx(site, {
        'collection': collection,
        'item': item,
        'display_fields': display_fields,
        'wa_link': wa_link,
        'booking_form': render_inquiry_form(site, item),
        'meta_title': f'{item.title} · {site.site_name}',
        'meta_description': _strip_html(item_desc) or _strip_html(site.tagline or site.site_name),
        'meta_image': image_url(item.image_url or site.logo_url, 1200),
        'meta_url': f'{_base_url(site)}/c/{collection.slug}/{item.slug}/',
    }))


@csrf_exempt
@require_POST
def submit_inquiry(request):
    """Public booking/inquiry POST kutoka website ya mteja."""
    site = _get_site(request)
    # Honeypot — bots hujaza field iliyofichwa
    if request.POST.get('website_url'):
        return JsonResponse({'status': 'ok'})

    name = (request.POST.get('name') or '').strip()[:120]
    phone = (request.POST.get('phone') or '').strip()[:40]
    if not name or not phone:
        return HttpResponseBadRequest('name and phone required')

    from .models import SiteInquiry, SiteItem
    item = None
    item_id = request.POST.get('item_id')
    if item_id:
        item = SiteItem.objects.filter(
            id=item_id, collection__website=site).first()

    # Kinga ya spam: max inquiries 30 kwa saa kwa site
    from django.utils import timezone
    from datetime import timedelta
    recent = SiteInquiry.objects.filter(
        website=site, created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recent >= 30:
        return JsonResponse({'status': 'ok'})  # kimya — usiwape bots taarifa

    # Tarehe iliyotumwa ilihifadhiwa KAMA ILIVYO kwenye DateField. Muundo
    # usiotarajiwa (kivinjari cha zamani, bot) ulileta Server Error — na
    # swali la mgeni likapotea. Sasa isiyosomeka inaachwa tupu tu.
    from django.utils.dateparse import parse_date
    try:
        preferred = parse_date((request.POST.get('preferred_date') or '').strip())
    except ValueError:            # muundo sahihi lakini tarehe haipo (2026-02-31)
        preferred = None
    people = request.POST.get('people_count') or None
    try:
        people = int(people) if people else None
    except ValueError:
        people = None

    inquiry = SiteInquiry.objects.create(
        website=site, item=item, name=name, phone=phone,
        email=(request.POST.get('email') or '').strip()[:120],
        message=(request.POST.get('message') or '').strip()[:3000],
        preferred_date=preferred, people_count=people,
    )

    # Mjulishe mmiliki — kwenye thread ya nyuma, mgeni hasubiri
    from .inquiry_notify import notify_owner
    notify_owner(inquiry)

    # Browser navigation ya kawaida (JS imezimwa/imefeli) → page ya asante,
    # AJAX fetch (Accept: */*) → JSON kama kawaida
    if 'text/html' in (request.headers.get('Accept') or ''):
        return render(request, 'builder/public/inquiry_thanks.html',
                      {'site': site, 'name': name})
    return JsonResponse({'status': 'ok'})


def sitemap_xml(request):
    """Sitemap ya website ya mteja — pages + collections + items."""
    from django.http import HttpResponse
    site = _get_site(request)
    if not site.is_published:
        return HttpResponse(status=404)

    base = _base_url(site)
    urls = [f'{base}/']
    for p in site.pages.exclude(slug='home').only('slug'):
        urls.append(f'{base}/p/{p.slug}/')
    for c in site.collections.only('slug'):
        urls.append(f'{base}/c/{c.slug}/')
        for it in c.items.filter(is_visible=True).only('slug'):
            urls.append(f'{base}/c/{c.slug}/{it.slug}/')

    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f'  <url><loc>{u}</loc></url>')
    xml.append('</urlset>')
    return HttpResponse('\n'.join(xml), content_type='application/xml')


def robots_txt(request):
    """Robots ya website ya mteja — draft sites zinazuiliwa kabisa."""
    from django.http import HttpResponse
    site = _get_site(request)
    if site.is_published:
        body = (f'User-agent: *\nAllow: /\n\n'
                f'Sitemap: {_base_url(site)}/sitemap.xml\n')
    else:
        body = 'User-agent: *\nDisallow: /\n'
    return HttpResponse(body, content_type='text/plain')
