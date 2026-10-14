"""
Website Studio — kujenga website hatua kwa hatua.

TATIZO

Dashboard ilikuwa na kila kitu ukurasa mmoja: templates, rangi, navbar,
pages, mawasiliano. Mteja mpya hakujua aanzie wapi, na kila chaguo
lilihitaji kuhifadhi kisha kufungua site kwenye tab nyingine kuona matokeo.

SULUHISHO

Hatua 6 kwenye ukurasa MMOJA, na hakikisho la moja kwa moja pembeni (juu
kwenye simu). Hakuna kupakia ukurasa upya:

  - design zote zinatumwa pamoja na ukurasa (layout_bundle), na JavaScript
    inazibadilisha ndani ya iframe ya preview papo hapo mteja akibonyeza
  - chaguo zinahifadhiwa nyuma kwa fetch(); kuhamia hatua nyingine ni JS tu

Hatua:

  1. Biashara  — jina, tagline (✨ AI), logo, mawasiliano
  2. Mtindo    — rangi tayari au yako mwenyewe, nav nyeusi/nyeupe, font
  3. Header    — Chagua (14) + menyu ya simu (6) · ✨ AI · 💻 Code
  4. Footer    — Chagua (16) · ✨ AI · 💻 Code
  5. Kurasa    — kila ukurasa: drag & drop · 💻 Code · ✨ AI; kufuta; ZIP;
                 maudhui; templates tayari
  6. Publish   — kwenda hewani, vidokezo vya AI Coach, domain yako mwenyewe

Dashboard ina vitu vitano tu (hali, Studio, inquiries, ZIP, JamiiBot) —
kila kitu kingine cha kujenga website kiko hapa.

Hatua zilizokamilika zinahifadhiwa kwenye theme_settings['studio_done'].
Studio haitumii three.js wala background ya WebGL — inafunguka haraka.
"""
import html as html_lib
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .layouts import (FONTS, PALETTES, HEADER_COMMON_CSS, SIDE_COMMON_CSS, FOOTER_COMMON_CSS,
                      MOBILE_MENUS, font_for)
from .nav_presets import FOOTERS, HEADERS, get_preset_catalog, _placeholders, _fill
from .branding import add_badge_to_response
from .views import _my_site, ensure_pages

STEPS = [
    ('business', 'Business', 'Name, logo & contact'),
    ('style', 'Colors & Font', 'Your brand look'),
    ('header', 'Header & Menu', 'Top bar or sidebar'),
    ('footer', 'Footer', 'Bottom of every page'),
    ('pages', 'Pages & Content', 'Build each page'),
    ('publish', 'Go Live', 'Publish your site'),
]
STEP_KEYS = [k for k, _, _ in STEPS]
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _done(site):
    return set((site.theme_settings or {}).get('studio_done', []))


def _mark_done(site, step):
    ts = dict(site.theme_settings or {})
    done = set(ts.get('studio_done', []))
    done.add(step)
    ts['studio_done'] = sorted(done)
    site.theme_settings = ts


# Hatua zinazotakiwa kuhifadhiwa kabla ya kupublish. Site ya ZIP tupu (kurasa
# zote ni raw_document) haitumii rangi/header/footer zetu, kwa hiyo inahitaji
# biashara na kurasa tu.
REQUIRED_STEPS = ['business', 'style', 'header', 'footer', 'pages']


def required_steps(site):
    pages = site.pages.all()
    if pages.exists() and not pages.filter(raw_document='').exists():
        return ['business', 'pages']
    return REQUIRED_STEPS


def publish_blockers(site):
    """Hatua ambazo bado hazijahifadhiwa: [(key, jina), ...]. Tupu = inaweza kupublish."""
    done, titles = _done(site), {k: t for k, t, _ in STEPS}
    return [(k, titles[k]) for k in required_steps(site) if k not in done]


def studio_progress(site):
    """Kwa dashboard: (hatua zilizokamilika, jumla, hatua inayofuata)."""
    done = _done(site)
    nxt = next((k for k in STEP_KEYS if k not in done), 'publish')
    return len(done & set(STEP_KEYS)), len(STEP_KEYS), nxt


def _save_step(request, site, step):
    """Hifadhi fomu ya hatua. Inarudisha ujumbe wa kosa au None."""
    p = request.POST
    fields = []
    if step == 'business':
        name = (p.get('site_name') or '').strip()
        if not name:
            return 'Enter your business name.'
        site.site_name = name[:120]
        for f, n in (('tagline', 200), ('contact_phone', 30), ('whatsapp_number', 30),
                     ('contact_email', 254), ('contact_address', 200), ('logo_url', 200)):
            setattr(site, f, (p.get(f) or '').strip()[:n])
        fields = ['site_name', 'tagline', 'contact_phone', 'whatsapp_number',
                  'contact_email', 'contact_address', 'logo_url']
    elif step == 'style':
        accent = (p.get('accent_color') or '').strip()
        if HEX_RE.match(accent):
            site.accent_color = accent
        site.dark_nav = p.get('dark_nav') == 'on'
        font = p.get('font', 'system')
        ts = dict(site.theme_settings or {})
        ts['font'] = font if font in FONTS else 'system'
        site.theme_settings = ts
        fields = ['accent_color', 'dark_nav']
    elif step == 'header':
        if p.get('mode') == 'custom':
            html = (p.get('html') or '').strip()
            if not html:
                return 'Write or generate your header code first — or pick a ready design.'
            site.custom_nav_html = html[:40000]
            site.nav_preset = ''
        else:
            key = p.get('preset', '')
            if key not in HEADERS:
                return 'Pick a header design.'
            site.nav_preset, site.custom_nav_html = key, ''
        # Mtindo wa menyu ya simu: '' = wa kawaida wa header iliyochaguliwa
        mobile = p.get('mobile_menu', '')
        ts = dict(site.theme_settings or {})
        ts['mobile_menu'] = mobile if mobile in MOBILE_MENUS else ''
        site.theme_settings = ts
        fields = ['nav_preset', 'custom_nav_html']
    elif step == 'footer':
        if p.get('mode') == 'custom':
            html = (p.get('html') or '').strip()
            if not html:
                return 'Write or generate your footer code first — or pick a ready design.'
            site.custom_footer_html = html[:40000]
        else:
            key = p.get('preset', '')
            if key not in FOOTERS:
                return 'Pick a footer design.'
            site.footer_preset, site.custom_footer_html = key, ''
        fields = ['footer_preset', 'custom_footer_html']
    elif step == 'publish':
        missing = publish_blockers(site)
        if missing:
            return 'Save every step before publishing — still missing: ' + ', '.join(t for _, t in missing) + '.'
        site.is_published = True
        fields = ['is_published']

    _mark_done(site, step)
    site.save(update_fields=fields + ['theme_settings'])
    site.bump_version()
    return None


def _add_page(site, title):
    """Ukurasa mpya kutoka Studio (kama views.page_create, bila kuondoka Studio)."""
    from django.utils.text import slugify
    from .models import SitePage
    base = slugify(title)[:70] or 'page'
    slug, n = base, 2
    while site.pages.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return SitePage.objects.create(
        website=site, slug=slug, title=title[:200], sort_order=site.pages.count(),
        html_cache=(f'<section style="padding:60px 20px;max-width:900px;margin:0 auto;">'
                    f'<h1>{html_lib.escape(title)}</h1><p>Start editing this page.</p></section>'),
    )


def layout_bundle(site):
    """
    Design zote zikiwa zimejazwa taarifa za site — Studio inazibadilisha ndani
    ya preview kwa JavaScript, bila kwenda server kila mteja anapobonyeza.
    """
    ph = _placeholders(site, 'home')
    return {
        'headerCommon': HEADER_COMMON_CSS,
        'sideCommon': SIDE_COMMON_CSS,
        'footerCommon': FOOTER_COMMON_CSS,
        # {{mm}} = mtindo wa kawaida wa menyu ya simu wa header; JS inaubadilisha
        # mteja akichagua mwingine
        'headers': {k: {'html': _fill(h['html'], {**ph, '{{mm}}': 'hx-m-' + h['mobile']}),
                        'css': h['css'], 'side': h['kind'] == 'side', 'mobile': h['mobile']}
                    for k, h in HEADERS.items()},
        'footers': {k: {'html': _fill(f['html'], ph), 'css': f['css']} for k, f in FOOTERS.items()},
        # Kwa code ya mteja mwenyewe: placeholders zinajazwa upande wa browser
        'placeholders': ph,
        'fonts': {k: dict(zip(('href', 'body', 'head'), font_for(site, k))) for k in FONTS},
    }


def _wants_json(request):
    return request.headers.get('X-Requested-With') == 'fetch'


@login_required
def studio(request, site_id, step=None):
    """
    Studio yote ni ukurasa MMOJA: hatua zinabadilishwa kwa JavaScript na
    kuhifadhiwa kwa fetch(). URL /studio/<step>/ inafungua hatua husika
    moja kwa moja (links, refresh, kitufe cha nyuma cha browser).
    """
    site = _my_site(request, site_id)
    step = step or studio_progress(site)[2]
    if step not in STEP_KEYS:
        raise Http404
    # Site isiyo na kurasa ilionyesha preview nyeupe tupu — unda za aina yake
    ensure_pages(request, site)

    if request.method == 'POST':
        if step == 'pages' and request.POST.get('action') == 'add_page':
            title = (request.POST.get('title') or '').strip()
            if not title:
                return JsonResponse({'ok': False, 'error': 'Enter a page name.'}, status=400)
            page = _add_page(site, title)
            return JsonResponse({'ok': True, 'page': {
                'id': page.id, 'slug': page.slug, 'title': page.title,
                'edit': reverse('builder:page_editor', args=[site.id, page.id]),
                'delete': reverse('builder:page_delete', args=[site.id, page.id])}})

        if step == 'publish' and not site.is_published:
            from .billing import needs_payment
            tpl = needs_payment(site)
            if tpl:
                pay = reverse('builder:checkout', args=[site.id, 'template'])
                if _wants_json(request):
                    return JsonResponse({'ok': False, 'pay_url': pay,
                                         'error': f'This design costs TSh {tpl.price:,}. Pay once to put it online.'}, status=402)
                return redirect(pay)
        error = _save_step(request, site, step)
        if _wants_json(request):
            if error:
                return JsonResponse({'ok': False, 'error': error}, status=400)
            data = {'ok': True, 'done': sorted(_done(site)), 'published': site.is_published}
            if step == 'business':
                # Jina/logo/mawasiliano yamebadilika — design zijazwe upya
                data['layout'] = layout_bundle(site)
            return JsonResponse(data)
        # Browser bila JavaScript: tabia ya zamani ya fomu
        if error:
            messages.error(request, error)
            return redirect('builder:studio_step', site_id=site.id, step=step)
        nxt = STEP_KEYS[min(STEP_KEYS.index(step) + 1, len(STEP_KEYS) - 1)]
        return redirect('builder:studio_step', site_id=site.id, step=nxt)

    done = _done(site)
    catalog = get_preset_catalog()
    ts = site.theme_settings or {}
    from .insights import get_insights
    from .site_templates import all_templates
    from .billing import logo_price, needs_payment
    return render(request, 'builder/studio.html', {
        'site': site,
        'step': step,
        'pay_template': needs_payment(site),
        'logo_price': logo_price(site),
        'steps': [{'key': k, 'title': t, 'sub': s, 'num': i + 1, 'done': k in done}
                  for i, (k, t, s) in enumerate(STEPS)],
        'steps_json': [{'key': k, 'title': t} for k, t, _ in STEPS],
        'parts': ['header', 'footer'],
        'done_json': sorted(done),
        'headers_side': [h for h in catalog['nav'] if h['kind'] == 'side'],
        'headers_top': [h for h in catalog['nav'] if h['kind'] == 'top'],
        'footers': catalog['footer'],
        'mobile_menus': [{'key': k, 'name': n, 'desc': d} for k, (n, d) in MOBILE_MENUS.items()],
        'palettes': PALETTES,
        'fonts': [(k, v[0]) for k, v in FONTS.items()],
        'current_font': ts.get('font', 'system'),
        'pages': site.pages.all(),
        'collections': site.collections.all(),
        # Vilivyohamishwa kutoka dashboard: templates, vidokezo vya AI, domain
        'site_templates': [t for t in all_templates() if site.website_type in t['types']],
        'insights': get_insights(site)[:4],
        'required_json': required_steps(site),
        'preview_url': reverse('builder:studio_preview', args=[site.id]),
        'layout': layout_bundle(site),
        'initial_state': {
            'accent': site.accent_color, 'dark': site.dark_nav, 'font': ts.get('font', 'system'),
            'header': site.nav_preset if site.nav_preset in HEADERS else '',
            'footer': site.footer_preset if site.footer_preset in FOOTERS else '',
            'headerCode': site.custom_nav_html, 'footerCode': site.custom_footer_html,
            'mobile': ts.get('mobile_menu', '') if ts.get('mobile_menu') in MOBILE_MENUS else '',
        },
    })


@login_required
@xframe_options_sameorigin
def studio_preview(request, site_id):
    """
    Hakikisho la site ndani ya Studio, likiwa na chaguo ambazo HAZIJAHIFADHIWA
    bado (?header=&footer=&accent=&dark=&font=&page=). Site inabadilishwa
    kwenye memory tu — database haiguswi.

    Iko kwenye domain ya dashboard (si subdomain ya mteja) kwa sababu
    iframe ya domain nyingine ingezuiwa. @xframe_options_sameorigin inaruhusu
    iframe ya Studio hata pale X_FRAME_OPTIONS ya mfumo ni DENY.
    """
    from . import public_views
    from .rendering import render_page_html, render_raw_document

    site = _my_site(request, site_id)
    g = request.GET
    # "▶ Preview this code" inatuma code ambayo haijahifadhiwa kwa POST
    if request.method == 'POST':
        if 'header_html' in request.POST:
            site.custom_nav_html = request.POST['header_html'][:40000]
        if 'footer_html' in request.POST:
            site.custom_footer_html = request.POST['footer_html'][:40000]
    if g.get('header') in HEADERS:
        site.nav_preset, site.custom_nav_html = g['header'], ''
    if g.get('mobile', '') in MOBILE_MENUS or g.get('mobile') == 'auto':
        site.theme_settings = {**(site.theme_settings or {}),
                               'mobile_menu': '' if g['mobile'] == 'auto' else g['mobile']}
    if g.get('footer') in FOOTERS:
        site.footer_preset, site.custom_footer_html = g['footer'], ''
    if HEX_RE.match(g.get('accent', '')):
        site.accent_color = g['accent']
    if g.get('dark') in ('0', '1'):
        site.dark_nav = g['dark'] == '1'
    if g.get('font') in FONTS:
        site.theme_settings = {**(site.theme_settings or {}), 'font': g['font']}

    slug = g.get('page') or 'home'
    page = site.pages.filter(slug=slug).first() or site.pages.first()
    if page is None:
        # Bila kurasa bado onyesha header/footer — mteja aone design anayochagua
        from .models import SitePage
        page = SitePage(website=site, slug='home', title=site.site_name)
        return add_badge_to_response(render(request, 'builder/public/page.html', public_views._ctx(site, {
            'page': page, 'is_preview': True,
            'page_html': ('<section style="padding:90px 24px;text-align:center">'
                          f'<h1 style="font-size:40px;margin-bottom:12px">{html_lib.escape(site.site_name)}</h1>'
                          '<p style="opacity:.7">Your page content will appear here.</p></section>'),
        })))
    if page.raw_document:
        return add_badge_to_response(HttpResponse(render_raw_document(site, page)))
    return add_badge_to_response(render(request, 'builder/public/page.html', public_views._ctx(site, {
        'page': page,
        'page_html': render_page_html(site, page),
        'is_preview': True,
    })))
