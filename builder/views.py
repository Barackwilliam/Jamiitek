"""
Dashboard ya mteja ("cPanel" ya JamiiTek Builder) — inafanya kazi kwenye
platform kuu (jamiitek.com/builder/...).
"""
import os
import json

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import (
    ClientWebsite, SitePage, SiteCollection, SiteItem, SiteAsset, SiteImport, SiteInquiry,
    AiUsageLog,
    available_website_types, validate_subdomain,
)
from .site_templates import all_templates, apply_template


def _register_subdomain(site):
    """
    IMEZIMWA by default — subdomains zinaishi kwenye database tu na
    middleware inazi-route. Wildcard *.jamiitek.com kwenye Render + CNAME
    moja ya Cloudflare vinatosheleza subdomains ZOTE bila kusajili chochote.

    Washa TU kama dharura (wildcard ikizuiwa) kwa env var:
        BUILDER_AUTO_REGISTER_SUBDOMAINS=1
    (kumbuka: kila domain ya ziada Render ina gharama — haifai kwa wingi)
    """
    import os
    if os.getenv('BUILDER_AUTO_REGISTER_SUBDOMAINS') != '1':
        return
    try:
        from django.conf import settings as dj_settings
        from . import render_api
        if render_api.is_configured():
            base = getattr(dj_settings, 'BUILDER_BASE_DOMAIN', 'jamiitek.com')
            render_api.add_custom_domain(f'{site.subdomain}.{base}')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('subdomain auto-register failed')


def _my_site(request, site_id):
    return get_object_or_404(ClientWebsite, id=site_id, owner=request.user)


def ensure_pages(request, site):
    """
    Unda kurasa za aina ya site ikiwa haina hata moja. Ikishindwa, usirudishe
    500 — rekodi kosa kwenye log na mwonyeshe mteja ujumbe (staff wanaona
    maelezo ya kiufundi, kwa ajili ya kurekebisha).
    """
    if site.pages.exists():
        return True
    try:
        with transaction.atomic():
            site.bootstrap_from_schema()
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('bootstrap_from_schema failed (site %s)', site.id)
        detail = f' ({type(e).__name__}: {str(e)[:300]})' if request.user.is_staff else ''
        messages.error(request, 'We could not create the pages for this website. '
                                'Our team has been notified.' + detail)
        return False


# ── Kuingia na kujisajili (web builder) ─────────────────

class BuilderSignupForm(UserCreationForm):
    """Account ya web builder: username, email (si lazima) na nywila."""
    email = forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')


def _safe_next(request):
    """`next` ya ndani ya jamiitek.com tu — si link ya nje (open redirect)."""
    from django.utils.http import url_has_allowed_host_and_scheme
    nxt = request.POST.get('next') or request.GET.get('next') or ''
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                         require_https=request.is_secure())
    return nxt if ok and nxt.startswith('/') else ''


def _template_for_next(nxt):
    """Kama `next` ni "Customize in Builder" ya template, rudisha template hiyo."""
    import re
    m = re.match(r'^/builder/templates/(\d+)/use/', nxt or '')
    if not m:
        return None
    from apps.models import WebsiteTemplate
    return WebsiteTemplate.objects.filter(pk=m.group(1), is_active=True).first()


def builder_login(request):
    """
    Kuingia kwenye web builder. Zamani LOGIN_URL ilikuwa /accounts/login/ —
    ukurasa usiokuwepo (404), kwa hiyo mteja aliyetoka hakuweza kurudi.
    """
    from django.contrib.auth.forms import AuthenticationForm
    nxt = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(nxt or 'builder:my_sites')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        # Watu wengi wanaandika email badala ya username
        ident = (request.POST.get('username') or '').strip()
        if '@' in ident:
            u = User.objects.filter(email__iexact=ident).first()
            if u:
                data = request.POST.copy()
                data['username'] = u.username
                form = AuthenticationForm(request, data=data)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(nxt or 'builder:my_sites')
    error = None
    if getattr(request, 'login_locked', False):
        from apps.security import lockout_message
        error = lockout_message()
        form.errors.pop('__all__', None)
    return render(request, 'builder/auth.html', {
        'mode': 'login', 'form': form, 'next': nxt, 'from_template': _template_for_next(nxt),
        'error': error,
    })


@require_POST
def builder_logout(request):
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, 'You have signed out.')
    return redirect('builder:login')


def signup(request):
    """
    Usajili wa web builder. Njia mbili:
      - kawaida: account + website ya kwanza kwa hatua moja
      - ukitoka mahali pengine (`next`, mf. template kutoka Marketplace):
        account tu, kisha unarudishwa ulikotoka
    """
    nxt = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(nxt or 'builder:my_sites')

    form = BuilderSignupForm(request.POST or None)
    error = None
    account_only = bool(nxt)

    ai_draft = request.session.get('ai_draft')
    # Funguo zipo daima — template inazitumia kama hoja za filter (hazisamehewi zikikosekana)
    ai_prefill = {'site_name': '', 'website_type': ''}
    if ai_draft and ai_draft.get('plan') and request.GET.get('from') == 'ai':
        plan = ai_draft['plan']
        ai_prefill = {
            'site_name': plan.get('site_name', ''),
            'website_type': plan.get('website_type', 'default'),
        }

    if request.method == 'POST' and form.is_valid():
        if account_only:
            user = form.save()
            login(request, user)
            messages.success(request, 'Welcome to JamiiTek Builder! Your account is ready.')
            return redirect(nxt)
        subdomain = (request.POST.get('subdomain') or '').lower().strip()
        site_name = (request.POST.get('site_name') or '').strip()
        website_type = request.POST.get('website_type') or 'default'
        try:
            validate_subdomain(subdomain)
            if ClientWebsite.objects.filter(subdomain=subdomain).exists():
                raise ValidationError('This subdomain is already taken. Choose another one.')
            if not site_name:
                raise ValidationError('Enter your website name.')
            with transaction.atomic():
                user = form.save()
                site = ClientWebsite.objects.create(
                    owner=user, subdomain=subdomain,
                    site_name=site_name, website_type=website_type,
                )
                site.bootstrap_from_schema()
                apply_template(site, request.POST.get('template_key', 'clean_start'))

                # AI draft ipo? Iweke kwenye site (juu ya template)
                ai_draft = request.session.get('ai_draft')
                if ai_draft and ai_draft.get('plan'):
                    _apply_ai_plan(site, ai_draft['plan'])
                    del request.session['ai_draft']
                    request.session.modified = True
            _register_subdomain(site)
            login(request, user)
            messages.success(request, f'Congratulations! Your website {site.subdomain}.jamiitek.com has been created.')
            # Mteja mpya anaanza Studio — hatua kwa hatua, si dashboard yenye kila kitu
            return redirect('builder:studio', site_id=site.id)
        except ValidationError as e:
            error = ' '.join(e.messages)

    return render(request, 'builder/auth.html', {
        'mode': 'signup', 'form': form, 'error': error, 'next': nxt,
        'account_only': account_only, 'from_template': _template_for_next(nxt),
        'website_types': available_website_types(),
        'ai_prefill': ai_prefill,
        'from_ai': bool(ai_prefill['site_name']),
    })


def from_template(request, pk):
    """
    "✨ Customize in Builder" kutoka Templates Marketplace. Asiye na account
    anajisajili kwanza, kisha anarudi hapa (builder/template_bridge.py).
    """
    from apps.models import WebsiteTemplate
    from .template_bridge import create_site_from_template, put_template_on_home, suggest_subdomain

    tpl = get_object_or_404(WebsiteTemplate, pk=pk, is_active=True)
    here = reverse('builder:from_template', args=[tpl.pk])
    if not request.user.is_authenticated:
        return redirect(f"{reverse('builder:signup')}?next={here}")

    sites = request.user.websites.all()
    error = None
    if request.method == 'POST':
        target = request.POST.get('target', 'new')
        if target != 'new':
            site = sites.filter(pk=target).first()
            if site is None:
                raise Http404
            page = put_template_on_home(site, tpl)
            messages.success(request, f'“{tpl.name}” is now the Home page of {site.site_name}. Make it yours!')
            return redirect('builder:page_editor', site_id=site.id, page_id=page.id)
        subdomain = (request.POST.get('subdomain') or '').lower().strip()
        site_name = (request.POST.get('site_name') or '').strip()
        try:
            validate_subdomain(subdomain)
            if ClientWebsite.objects.filter(subdomain=subdomain).exists():
                raise ValidationError('This address is already taken — try another one.')
            if not site_name:
                raise ValidationError('Enter your business name.')
            site, page = create_site_from_template(request.user, tpl, site_name, subdomain)
            _register_subdomain(site)
            messages.success(request, f'Your website is ready with the “{tpl.name}” design. '
                                      'Click any text or image to change it.')
            return redirect('builder:page_editor', site_id=site.id, page_id=page.id)
        except ValidationError as e:
            error = ' '.join(e.messages)

    return render(request, 'builder/from_template.html', {
        'tpl': tpl, 'sites': sites, 'error': error,
        'suggest': request.POST.get('subdomain') or suggest_subdomain(tpl.name),
        'site_name': request.POST.get('site_name', ''),
    })


@login_required
def my_sites(request):
    sites = request.user.websites.all()
    if sites.count() == 1:
        return redirect('builder:site_dashboard', site_id=sites.first().id)
    return render(request, 'builder/my_sites.html', {'sites': sites})


@login_required
def create_site(request):
    """Website ya ziada kwa mteja aliyekwishakuwa na account."""
    error = None
    if request.method == 'POST':
        subdomain = (request.POST.get('subdomain') or '').lower().strip()
        site_name = (request.POST.get('site_name') or '').strip()
        website_type = request.POST.get('website_type') or 'default'
        try:
            validate_subdomain(subdomain)
            if ClientWebsite.objects.filter(subdomain=subdomain).exists():
                raise ValidationError('This subdomain is already taken.')
            if not site_name:
                raise ValidationError('Enter the website name.')
            # Yote au hakuna: kurasa zikishindwa kuundwa, site isibaki nusu —
            # ingeleta 500 kwenye panel na "subdomain already taken" ukijaribu tena.
            with transaction.atomic():
                site = ClientWebsite.objects.create(
                    owner=request.user, subdomain=subdomain,
                    site_name=site_name, website_type=website_type,
                )
                site.bootstrap_from_schema()
                apply_template(site, request.POST.get('template_key', 'clean_start'))
            _register_subdomain(site)
            return redirect('builder:studio', site_id=site.id)
        except ValidationError as e:
            error = ' '.join(e.messages)
        except Exception as e:
            # Transaction imerudisha nyuma: hakuna site nusu iliyobaki
            import logging
            logging.getLogger(__name__).exception('create_site failed (%s)', subdomain)
            error = 'We could not create your website. Please try again or contact support.'
            if request.user.is_staff:
                error += f' ({type(e).__name__}: {str(e)[:300]})'
    return render(request, 'builder/create_site.html', {
        'error': error, 'website_types': available_website_types(),
        'site_templates': all_templates(),
    })


# ── Dashboard ───────────────────────────────────────────

def get_started(request):
    """Public chooser: order a website, buy one, or build it yourself."""
    return render(request, 'builder/get_started.html')



# ═══════════════════════════════════════════════════════════
# ONE-SHOT AI WEBSITE GENERATOR
# Kutoka sentensi moja ya biashara → website nzima tayari.
# ═══════════════════════════════════════════════════════════

def ai_generator(request):
    """Public page yenye textarea moja: 'Describe your business'."""
    return render(request, 'builder/ai_generator.html', {})


def ai_ticker(request):
    """
    Rudisha websites HALISI zilizochapishwa hivi karibuni kwa ticker.
    Jina la biashara + mji (kutoka contact_address) + muda halisi.
    Kwa faragha: jina + mji tu — hakuna simu/anwani kamili.
    """
    from django.utils import timezone
    import re as _re

    def _city(addr):
        if not addr:
            return ''
        # Miji mikuu ya TZ — tafuta kwenye anwani
        cities = ['Dar es Salaam', 'Dar', 'Arusha', 'Mwanza', 'Dodoma', 'Mbeya',
                  'Morogoro', 'Tanga', 'Zanzibar', 'Iringa', 'Moshi', 'Tabora',
                  'Kigoma', 'Mtwara', 'Musoma', 'Songea', 'Kariakoo', 'Mwenge']
        for c in cities:
            if _re.search(r'\b' + _re.escape(c) + r'\b', addr, _re.I):
                return 'Dar' if c in ('Dar es Salaam', 'Kariakoo', 'Mwenge') else c
        # Vinginevyo, sehemu ya mwisho ya anwani (mara nyingi ni mji)
        parts = [x.strip() for x in addr.split(',') if x.strip()]
        return parts[-1][:20] if parts else ''

    sites = (ClientWebsite.objects
             .filter(is_published=True, is_suspended=False)
             .order_by('-created_at')[:12])
    now = timezone.now()
    items = []
    for s in sites:
        delta = now - s.created_at
        secs = int(delta.total_seconds())
        if secs < 90:
            ago = 'just now'
        elif secs < 3600:
            ago = f'{secs // 60} min ago'
        elif secs < 86400:
            h = secs // 3600
            ago = f'{h} hour{"s" if h > 1 else ""} ago'
        elif secs < 604800:
            d = secs // 86400
            ago = f'{d} day{"s" if d > 1 else ""} ago'
        else:
            ago = s.created_at.strftime('%b %Y')
        items.append({
            'name': s.site_name[:40],
            'city': _city(s.contact_address),
            'ago': ago,
        })
    return JsonResponse({'ok': True, 'items': items, 'count': ClientWebsite.objects.filter(is_published=True).count()})


@require_POST
def ai_generate_website(request):
    """
    Endpoint ya AJAX inayoitwa na ai_generator.html.
    Inarudisha JSON — kama sio-authenticated, ina-store draft kwenye session
    kisha ina-redirect mteja kwa signup. Baada ya signup, apply_ai_draft()
    inaingia otomatiki.
    """
    from . import ai_oneshot
    description = (request.POST.get('description') or '').strip()[:3000]

    # Haihitaji login, kwa hiyo kikomo kwa IP — kila ombi ni gharama ya AI
    from apps.turnstile import get_client_ip
    from apps.chatbot.ratelimit import _hit
    ip = get_client_ip(request) or 'unknown'
    ok_h, _ = _hit(f'builder:aigen:h:{ip}', 10, 3600)
    ok_d, _ = _hit(f'builder:aigen:d:{ip}', 30, 86400)
    if not (ok_h and ok_d):
        return JsonResponse({'ok': False, 'error': 'Too many AI generations from your network. '
                             'Please try again later.'}, status=429)

    try:
        ok, result = ai_oneshot.generate_website_plan(description)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('ai_generate_website crashed')
        return JsonResponse({'ok': False,
            'error': f'Server error while generating ({type(e).__name__}). '
                     'Check /builder/ai/status/ for diagnostics.'}, status=500)
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)

    # Store kwenye session — italetwa kwenye signup au apply mara moja
    request.session['ai_draft'] = {
        'description': description,
        'plan': result,
    }
    request.session.modified = True

    if request.user.is_authenticated:
        return JsonResponse({
            'ok': True,
            'next': reverse('builder:ai_apply'),
            'preview': {
                'site_name': result['site_name'],
                'tagline': result['tagline'],
                'website_type': result['website_type'],
                'items_count': len(result.get('items', [])),
            },
        })
    return JsonResponse({
        'ok': True,
        'next': reverse('builder:signup') + '?from=ai',
        'preview': {
            'site_name': result['site_name'],
            'tagline': result['tagline'],
            'website_type': result['website_type'],
            'items_count': len(result.get('items', [])),
        },
    })


def _apply_ai_plan(site, plan):
    """Weka AI-generated content kwenye ClientWebsite + collections zake."""
    from . import ai_oneshot
    from .ai_designs import render_home

    # 1. Update field za site
    site.tagline = plan.get('tagline', '')[:200] or site.tagline
    site.accent_color = plan.get('palette', {}).get('primary',
                        plan.get('accent_color', site.accent_color))
    site.nav_layout = plan.get('nav_layout', site.nav_layout)
    site.save(update_fields=['tagline', 'accent_color', 'nav_layout'])

    # 2. Ongeza items kwenye primary collection
    primary_slug = ai_oneshot.PRIMARY_COLLECTION.get(site.website_type, 'services')
    col = site.collections.filter(slug=primary_slug).first()
    if col is not None:
        col.items.all().delete()
        for it in plan.get('items', [])[:8]:
            title = str(it.get('title', ''))[:200].strip()
            if not title:
                continue
            data = {
                'description': str(it.get('description', ''))[:2000],
                'price': str(it.get('price', ''))[:80],
            }
            extra = it.get('extra') or {}
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        data[str(k)[:40]] = str(v)[:600]
            SiteItem.objects.create(
                collection=col, title=title, data=data, is_visible=True,
            )

    # 3. Home page — DESIGN TOFAUTI kulingana na style AI iliyochagua
    home = site.pages.filter(slug='home').first()
    if home is not None:
        home.html_cache = render_home(
            plan.get('design_style', 'sunset_bold'),
            plan.get('palette', {}),
            plan,
            col,
        )
        home.save()

    site.bump_version()


@login_required
def ai_apply(request):
    """Chukua draft kutoka session, unda ClientWebsite mpya, weka content."""
    draft = request.session.get('ai_draft')
    if not draft:
        messages.error(request, 'The AI draft has expired — please try again.')
        return redirect('builder:ai_generator')

    plan = draft['plan']
    website_type = plan.get('website_type', 'default')

    # Chagua subdomain automatic kutoka jina la biashara
    import re
    base = re.sub(r'[^a-z0-9]+', '-', plan.get('site_name', 'site').lower()).strip('-')[:40]
    if not base:
        base = 'site'
    subdomain = base
    n = 2
    while ClientWebsite.objects.filter(subdomain=subdomain).exists():
        subdomain = f'{base}-{n}'
        n += 1
        if n > 999:
            subdomain = f'{base}-{request.user.id}'
            break

    try:
        with transaction.atomic():
            site = ClientWebsite.objects.create(
                owner=request.user,
                subdomain=subdomain,
                site_name=plan.get('site_name', 'My Website')[:120],
                website_type=website_type,
            )
            site.bootstrap_from_schema()
            _apply_ai_plan(site, plan)
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
        return redirect('builder:ai_generator')

    del request.session['ai_draft']
    request.session.modified = True

    messages.success(request,
        f'✨ Your website is ready! "{site.site_name}" has been created — '
        'review the content and hit Publish when you are happy.')
    return redirect('builder:site_dashboard', site_id=site.id)


@login_required
def tutorial(request):
    """Mwongozo kamili wa kutumia builder — hatua kwa hatua."""
    return render(request, 'builder/tutorial.html', {
        'website_types': available_website_types(),
        'first_site': request.user.websites.first(),
    })


def _ago(since):
    """'2 days, 3 hours' → '2 days ago'; '0 minutes' → 'Just now'."""
    since = since.split(',')[0]
    return 'Just now' if since.startswith('0') else f'{since} ago'


@login_required
def site_dashboard(request, site_id):
    """
    Dashboard ni ukurasa wa KWANZA mteja anaouona — kwa hiyo ni mfupi:
    hali ya website, Studio, inquiries, kupakia ZIP na JamiiBot. Kila kitu
    kingine (kurasa, maudhui, templates, maelezo, rangi, domain, vidokezo vya
    AI) kiko ndani ya Website Studio.
    """
    from django.utils.timesince import timesince
    site = _my_site(request, site_id)
    # Site isiyo na kurasa inarudisha 404 kwa wageni na preview nyeupe
    ensure_pages(request, site)
    from .studio import studio_progress, publish_blockers, STEPS as STUDIO_STEPS
    st_done, st_total, st_next = studio_progress(site)
    return render(request, 'builder/dashboard.html', {
        'site': site,
        'studio_done': st_done,
        'studio_total': st_total,
        'studio_pct': int(st_done / st_total * 100),
        'studio_next': st_next,
        'studio_next_title': dict((k, t) for k, t, _ in STUDIO_STEPS)[st_next],
        'page_count': site.pages.count(),
        'new_inquiries': site.inquiries.filter(status='new').count(),
        'total_inquiries': site.inquiries.count(),
        'imported_pages': site.pages.exclude(raw_document='').count(),
        'last_change': _ago(timesince(site.updated_at)),
        'blockers': publish_blockers(site),
        **_billing_ctx(request, site),
    })


def _billing_ctx(request, site):
    """Kadi ya malipo kwenye dashboard: lipia template, ondoa logo, au hali ya premium."""
    from django.utils import timezone
    from . import billing
    price = billing.pricing()
    start = price.badge_old_sites_from
    return {
        'pay_template': billing.needs_payment(site),
        'logo_price': billing.logo_price(site),
        'shows_badge': billing.show_badge(site),
        # Taarifa kwa website za zamani: alama itaanza kuonekana tarehe hii
        'badge_from': start if (site.legacy_free and not site.is_premium and start
                                and start > timezone.localdate()) else None,
        'just_paid': request.GET.get('paid') == '1' and site.is_premium,
        # Hosting ya mwaka: kadi inaonekana siku 30 kabla ya kuisha, na baada ya kuisha
        'renew_price': billing.renew_price(site),
        'days_left': billing.days_left(site),
        'paused': billing.is_paused(site),
        'grace_days': billing.GRACE_DAYS,
    }


@login_required
@require_POST
def change_template(request, site_id):
    site = _my_site(request, site_id)
    apply_template(site, request.POST.get('template_key', 'clean_start'))
    messages.success(request, 'New template applied — the design of your default pages has been replaced.')
    return redirect('builder:studio_step', site_id=site.id, step='pages')


@login_required
@require_POST
def site_settings_save(request, site_id):
    site = _my_site(request, site_id)
    for field in ('site_name', 'tagline', 'contact_phone', 'contact_email',
                  'contact_address', 'whatsapp_number', 'logo_url',
                  'nav_style', 'accent_color'):
        if field in request.POST:
            setattr(site, field, request.POST[field].strip())
    # Fomu ya domain ya Studio inatuma custom_domain peke yake — isizime dark nav
    if 'accent_color' in request.POST:
        site.dark_nav = request.POST.get('dark_nav') == 'on'

    domain_changed = False
    old_domain = site.custom_domain
    if site.is_premium and 'custom_domain' in request.POST:
        new_domain = (request.POST['custom_domain'].strip().lower()
                      .replace('https://', '').replace('http://', '')
                      .rstrip('/')) or None
        if new_domain != old_domain:
            site.custom_domain = new_domain
            domain_changed = True

    site.save()
    site.bump_version()
    messages.success(request, 'Website details saved.')

    # ── Auto-registration ya custom domain kwenye Render (bila dashboard) ──
    if domain_changed:
        from . import render_api
        if old_domain:
            render_api.remove_custom_domain(old_domain)
        if site.custom_domain:
            ok, msg = render_api.add_custom_domain(site.custom_domain)
            (messages.success if ok else messages.warning)(request, msg)
            if render_api.check_dns(site.custom_domain):
                messages.success(request,
                    f'DNS check: "{site.custom_domain}" is already pointing to our '
                    'servers — your domain should be live within minutes. ✅')
            else:
                messages.info(request,
                    f'DNS check: "{site.custom_domain}" is not pointing to us yet. '
                    'Add a CNAME record at your registrar: '
                    f'{site.custom_domain} → jamiitek.onrender.com')
    return redirect('builder:studio_step', site_id=site.id, step='publish')


@login_required
@require_POST
def toggle_publish(request, site_id):
    site = _my_site(request, site_id)
    if not site.is_published:
        # Kupublish kunahitaji kila hatua ya Studio iwe imehifadhiwa
        from .studio import publish_blockers
        missing = publish_blockers(site)
        if missing:
            messages.error(request, 'Save every step in the Website Studio before publishing — still missing: '
                           + ', '.join(t for _, t in missing) + '.')
            return redirect('builder:studio_step', site_id=site.id, step=missing[0][0])
        # Template inayouzwa: analipa kwanza (Pesapal), malipo yakithibitishwa inakwenda hewani yenyewe
        from .billing import needs_payment
        if needs_payment(site):
            return redirect('builder:checkout', site_id=site.id, kind='template')
    site.is_published = not site.is_published
    site.save(update_fields=['is_published'])
    state = 'is now live' if site.is_published else 'has been unpublished'
    messages.success(request, f'Your website {state}.')
    return redirect('builder:site_dashboard', site_id=site.id)


@login_required
def checkout(request, site_id, kind):
    """Ukurasa wa malipo (Pesapal): kununua template inayouzwa, au kuondoa logo ya JamiiTek."""
    from . import billing
    site = _my_site(request, site_id)
    if kind not in ('template', 'logo', 'renew'):
        raise Http404
    tpl = billing.needs_payment(site) if kind == 'template' else billing.source_template(site)
    if kind == 'template':
        price = tpl.price if tpl else 0
    else:
        price = billing.logo_price(site) if kind == 'logo' else billing.renew_price(site)
    if not price:
        return redirect('builder:site_dashboard', site_id=site.id)
    if request.method == 'POST':
        return billing.start(request, site, kind)
    return render(request, 'builder/checkout.html', {'site': site, 'kind': kind, 'tpl': tpl, 'price': price,
                                                     'paused': billing.is_paused(site)})


# ── Pages + Editor ──────────────────────────────────────

@login_required
def page_editor(request, site_id, page_id):
    site = _my_site(request, site_id)
    page = get_object_or_404(SitePage, id=page_id, website=site)
    canvas_head = ''
    if page.raw_document:
        from .site_import import canvas_head as _canvas_head
        canvas_head = _canvas_head(page.raw_document)
    from .layouts import font_for
    font_href, font_body, font_head = font_for(site)
    return render(request, 'builder/editor.html', {
        'site': site, 'page': page,
        'pages': site.pages.all(),                 # kuhamia ukurasa mwingine bila kutoka editor
        'collections': site.collections.all(),
        'canvas_head': canvas_head,
        # Canvas inaonyesha website halisi: rangi, fonts na CSS ya site nzima
        'canvas_theme': {
            'accent': site.accent_color, 'font_href': font_href,
            'font_body': font_body, 'font_head': font_head,
            'global_css': site.global_css or '',
        },
        'preview_url': reverse('builder:studio_preview', args=[site.id]) + f'?page={page.slug}',
        'studio_pages_url': reverse('builder:studio_step', args=[site.id, 'pages']),
    })


@login_required
@require_POST
def page_create(request, site_id):
    site = _my_site(request, site_id)
    title = (request.POST.get('title') or '').strip()
    if not title:
        messages.error(request, 'Enter a page name.')
        return redirect('builder:studio_step', site_id=site.id, step='pages')
    from django.utils.text import slugify
    base = slugify(title)[:70] or 'page'
    slug, n = base, 2
    while site.pages.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    page = SitePage.objects.create(
        website=site, slug=slug, title=title,
        sort_order=site.pages.count(),
        html_cache=f'<section style="padding:60px 20px;max-width:900px;margin:0 auto;"><h1>{title}</h1><p>Anza kuhariri page hii.</p></section>',
    )
    return redirect('builder:page_editor', site_id=site.id, page_id=page.id)


@login_required
@require_POST
def page_delete(request, site_id, page_id):
    site = _my_site(request, site_id)
    page = get_object_or_404(SitePage, id=page_id, website=site)
    fetch = request.headers.get('X-Requested-With') == 'fetch'   # Studio: bila kupakia upya
    if page.slug == 'home':
        if fetch:
            return JsonResponse({'ok': False, 'error': 'The home page cannot be deleted.'}, status=400)
        messages.error(request, 'The home page cannot be deleted.')
    else:
        page.delete()
        site.bump_version()
        if fetch:
            return JsonResponse({'ok': True})
        messages.success(request, f'Page "{page.title}" has been deleted.')
    return redirect('builder:studio_step', site_id=site.id, step='pages')


# GrapesJS storage endpoints
@login_required
def page_load(request, site_id, page_id):
    site = _my_site(request, site_id)
    page = get_object_or_404(SitePage, id=page_id, website=site)
    return JsonResponse(page.grapes_data or {})


@login_required
@require_POST
def page_save(request, site_id, page_id):
    site = _my_site(request, site_id)
    page = get_object_or_404(SitePage, id=page_id, website=site)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'bad json'}, status=400)
    page.grapes_data = data.get('project', {})
    page.html_cache = data.get('html', '')
    page.css_cache = data.get('css', '')
    if page.raw_document:
        # Page iliyopakiwa kwa ZIP: body mpya inarudi ndani ya document
        # yake, <head> (CSS, fonts, meta) na scripts zinabaki.
        from .site_import import merge_editor_save
        page.raw_document = merge_editor_save(
            page.raw_document, page.html_cache, page.css_cache)
    page.save()
    return JsonResponse({'status': 'ok'})


# ── Kupakia website nzima kwa ZIP ───────────────────────

IMPORT_TTL_HOURS = 24      # hakikisho lisipothibitishwa, files zinafutwa baada ya hapo


@login_required
def site_import(request, site_id):
    """
    Hatua 1: mteja anapakia ZIP. Assets zinapakiwa Supabase papo hapo,
    kurasa zinakaa kwenye SiteImport mpaka athibitishe kwenye hakikisho.
    Kila URL iliyopakiwa inarekodiwa — hata upakiaji ukishindwa katikati —
    ili `prune_site_imports` izifute mteja asipothibitisha.
    """
    import logging
    import uuid
    from apps import storage
    from . import site_import as si

    site = _my_site(request, site_id)
    ctx = {'site': site, 'limits': {
        'zip_mb': si.MAX_ZIP_BYTES // 1024 // 1024, 'pages': si.MAX_PAGES,
        'files': si.MAX_FILES,
    }}
    if request.method != 'POST':
        return render(request, 'builder/site_import.html', ctx)

    f = request.FILES.get('zip')
    if not f:
        ctx['error'] = 'Choose a .zip file first.'
        return render(request, 'builder/site_import.html', ctx)
    if not storage.is_configured():
        ctx['error'] = 'File storage is not configured on the server yet. Please contact JamiiTek support.'
        return render(request, 'builder/site_import.html', ctx)

    uploaded, images = [], []     # list.append ni salama kwa threads

    def uploader(data, ext, content_type):
        r = storage.upload_bytes(data, f'sites/{site.id}/import', ext, content_type)
        if not r.get('success'):
            raise si.ImportRejected(f'Uploading a file failed: {r.get("error", "unknown error")}')
        uploaded.append(r['url'])
        if content_type.startswith('image/'):
            images.append(r['url'])
        return r['url']

    imp = SiteImport(website=site, token=uuid.uuid4().hex)
    try:
        result = si.prepare(f, uploader)
    except Exception as e:
        if not isinstance(e, si.ImportRejected):
            logging.getLogger(__name__).exception('site import failed (site %s)', site.id)
        ctx['error'] = str(e) if isinstance(e, si.ImportRejected) else \
            'Something went wrong while processing the ZIP. Please try again.'
        if uploaded:              # files zilizokwisha pakiwa zitafutwa na prune
            imp.uploaded = uploaded
            imp.save()
        return render(request, 'builder/site_import.html', ctx)

    # Hata kuhifadhi au kuonyesha hakikisho kukishindwa, mteja apate ujumbe
    # unaoeleweka (si "Internal Server Error"), na files zilizopakiwa zifutwe baadaye.
    try:
        imp.result, imp.uploaded, imp.images = result, uploaded, images
        imp.save()

        existing = set(site.pages.values_list('slug', flat=True))
        imported = {p['slug'] for p in result['pages']}
        for p in result['pages']:
            p['url'] = si.page_url(p['slug'])
            p['replaces'] = p['slug'] in existing
        return render(request, 'builder/site_import_preview.html', {
            'site': site, 'token': imp.token, 'result': result,
            'others': site.pages.exclude(slug__in=imported),
            'docs': [p['document'] for p in result['pages']],
        })
    except Exception:
        logging.getLogger(__name__).exception('site import: saving the preview failed (site %s)', site.id)
        if uploaded and imp.pk is None:
            try:
                SiteImport.objects.create(website=site, token=uuid.uuid4().hex, uploaded=uploaded)
            except Exception:
                pass
        ctx['error'] = ('Your ZIP was read, but we could not save it. Please try again — '
                        'if it keeps failing, send the ZIP to JamiiTek support.')
        return render(request, 'builder/site_import.html', ctx)


@login_required
@require_POST
def site_import_confirm(request, site_id):
    """Hatua 2: andika kurasa kwenye database."""
    from datetime import timedelta
    from django.utils import timezone
    from .site_import import editable_body

    site = _my_site(request, site_id)
    with transaction.atomic():
        # select_for_update: kubonyeza "Import" mara mbili hakuandiki mara mbili
        imp = SiteImport.objects.select_for_update().filter(
            website=site, token=(request.POST.get('token') or '')[:32],
            confirmed_at__isnull=True,
            created_at__gte=timezone.now() - timedelta(hours=IMPORT_TTL_HOURS),
        ).exclude(result={}).first()
        if imp is None:
            messages.error(request, 'This import has expired. Please upload the ZIP again.')
            return redirect('builder:site_import', site_id=site.id)

        pages = imp.result['pages']
        slugs = []
        for order, p in enumerate(pages):
            SitePage.objects.update_or_create(
                website=site, slug=p['slug'],
                defaults={
                    'title': p['title'],
                    'raw_document': p['document'],
                    'html_cache': editable_body(p['document']),
                    'css_cache': '',
                    'grapes_data': {},       # editor ianze na HTML mpya
                    'sort_order': order,
                },
            )
            slugs.append(p['slug'])
        if request.POST.get('remove_others'):
            for page in site.pages.exclude(slug__in=slugs):
                page.delete()
        # Picha zinaingia kwenye maktaba ya picha ya editor pia
        SiteAsset.objects.bulk_create([
            SiteAsset(website=site, url=u, file_name=u.rsplit('/', 1)[-1][:200])
            for u in imp.images
        ])
        # Documents hazihitajiki tena. `uploaded` inabaki: prune inaitumia kujua
        # files za kufuta ZIP mpya ikichukua nafasi ya kurasa hizi.
        imp.confirmed_at = timezone.now()
        imp.result = {'pages': len(pages)}
        imp.save(update_fields=['confirmed_at', 'result'])

    n = len(pages)
    messages.success(request, f'Your website has been imported — {n} page{"s" if n != 1 else ""} '
                              f'are ready. Open your site to check it, then publish.')
    return redirect('builder:site_dashboard', site_id=site.id)


# ── Collections (Packages, Trips, Destinations, Products...) ──

@login_required
def collection_items(request, site_id, collection_id):
    site = _my_site(request, site_id)
    collection = get_object_or_404(SiteCollection, id=collection_id, website=site)
    return render(request, 'builder/items.html', {
        'site': site, 'collection': collection,
        'items': collection.items.all(),
    })


@login_required
def item_form(request, site_id, collection_id, item_id=None):
    site = _my_site(request, site_id)
    collection = get_object_or_404(SiteCollection, id=collection_id, website=site)
    item = None
    if item_id:
        item = get_object_or_404(SiteItem, id=item_id, collection=collection)

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'A name/title is required.')
        else:
            data = {}
            for field in collection.fields:
                key = field['key']
                raw = (request.POST.get(f'f_{key}') or '').strip()
                if field.get('type') == 'list':
                    data[key] = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                else:
                    data[key] = raw
            if item is None:
                item = SiteItem(collection=collection)
            item.title = title
            item.data = data
            item.image_url = (request.POST.get('image_url') or '').strip()
            item.is_featured = request.POST.get('is_featured') == 'on'
            item.is_visible = request.POST.get('is_visible', 'on') == 'on'
            item.save()
            messages.success(request, f'{collection.name_singular} "{title}" saved.')
            return redirect('builder:collection_items',
                            site_id=site.id, collection_id=collection.id)

    return render(request, 'builder/item_form.html', {
        'site': site, 'collection': collection, 'item': item,
    })


@login_required
@require_POST
def item_delete(request, site_id, collection_id, item_id):
    site = _my_site(request, site_id)
    collection = get_object_or_404(SiteCollection, id=collection_id, website=site)
    item = get_object_or_404(SiteItem, id=item_id, collection=collection)
    item.delete()
    messages.success(request, f'"{item.title}" has been deleted.')
    return redirect('builder:collection_items', site_id=site.id, collection_id=collection.id)


@login_required
def ai_status(request):
    """
    Diagnostic ya AI — inaonyesha hasa kipi kimekwama:
    package, API key, mtandao kwenda Groq, cache. Staff PEKEE — inaonyesha
    vipande vya API key na REDIS_URL.
    """
    if not request.user.is_staff:
        raise Http404
    import time
    checks = {}

    # 1. groq package
    try:
        import groq  # noqa
        checks['groq_package'] = {'ok': True, 'detail': f'installed (v{getattr(groq, "__version__", "?")})'}
    except ImportError:
        checks['groq_package'] = {'ok': False, 'detail': 'NOT installed — run: pip install groq'}

    # 2. API key
    key = os.getenv('GROQ_API_KEY', '')
    checks['api_key'] = {'ok': bool(key),
        'detail': f'present ({key[:7]}…)' if key else 'MISSING — add GROQ_API_KEY to .env / Render env'}

    # 3. Mtandao kwenda Groq (models list — nyepesi, haitumii tokens)
    if checks['groq_package']['ok'] and key:
        try:
            from groq import Groq
            t0 = time.time()
            client = Groq(api_key=key)
            models = client.models.list()
            ms = int((time.time() - t0) * 1000)
            names = [m.id for m in models.data][:3]
            checks['groq_reachable'] = {'ok': True,
                'detail': f'reachable in {ms}ms · models e.g. {names}'}
        except Exception as e:
            checks['groq_reachable'] = {'ok': False,
                'detail': f'{type(e).__name__}: {str(e)[:180]} — check internet/VPN/firewall on the SERVER side'}
    else:
        checks['groq_reachable'] = {'ok': False, 'detail': 'skipped (fix package/key first)'}

    # 4. Model configured
    from .ai import GROQ_MODEL
    checks['model'] = {'ok': True, 'detail': GROQ_MODEL}

    # 5. Cache backend (+ REDIS_URL forensics — prefix tu, password haionyeshwi)
    from django.core.cache import cache
    redis_url = os.getenv('REDIS_URL', '')
    url_info = ''
    if redis_url:
        prefix = redis_url[:14]
        url_info = (f' · REDIS_URL starts with: {prefix!r} '
                    f'(len={len(redis_url)}, '
                    f'leading_space={redis_url != redis_url.lstrip()}, '
                    f'has_quotes={redis_url[0] in chr(34) + chr(39)})')
    else:
        url_info = ' · REDIS_URL is EMPTY/absent (LocMem in use)'
    try:
        cache.set('jt_diag', 'ok', 10)
        backend = type(cache).__name__
        checks['cache'] = {'ok': cache.get('jt_diag') == 'ok',
                           'detail': backend + url_info}
    except Exception as e:
        checks['cache'] = {'ok': False,
                           'detail': f'{type(e).__name__}: {str(e)[:120]}{url_info}'}

    # 6. Rate limit yako
    from .ai import _check_rate_limit, AI_DAILY_LIMIT
    ok_rate, remaining = _check_rate_limit(request.user)
    checks['your_rate_limit'] = {'ok': ok_rate,
        'detail': f'{remaining}/{AI_DAILY_LIMIT} requests left today'}

    all_ok = all(c['ok'] for c in checks.values())
    return JsonResponse({'all_ok': all_ok, 'checks': checks},
                        json_dumps_params={'indent': 2})


# ═══════════════════════════════════════════════════════════
# SUPER-ADMIN — udhibiti wa platform nzima (staff only)
# ═══════════════════════════════════════════════════════════

def _staff_only(user):
    return user.is_authenticated and user.is_staff


@login_required
def superadmin_db_check(request):
    """
    Uchunguzi wa database ya production kwa staff, bila shell ya Render.

    Kuunda site kulileta 500 kwenye production pekee (Postgres safi na SQLite
    zinafanya kazi), na DEBUG=False haionyeshi traceback. Ukurasa huu
    unaonyesha: migrations za builder, nguzo zinazokosekana/za ziada, na
    jaribio la kuunda site + kurasa ndani ya transaction inayorudishwa nyuma
    — likishindwa, traceback kamili. Hakuna kinachobaki kwenye database.
    """
    if not request.user.is_staff:
        raise Http404
    import io
    import traceback
    from django.core.management import call_command
    from django.db.migrations.recorder import MigrationRecorder
    from django.http import HttpResponse

    out = io.StringIO()
    out.write('== Migrations za builder zilizowekwa ==\n')
    applied = MigrationRecorder.Migration.objects.filter(app='builder').order_by('id')
    for m in applied:
        out.write(f'  [X] {m.name}\n')

    out.write('\n== Tofauti kati ya models na database (builder) ==\n')
    try:
        call_command('check_db_drift', app='builder', stdout=out)
    except Exception:
        out.write(traceback.format_exc())

    out.write('\n== Jaribio: kuunda site + kurasa (rollback) ==\n')

    class _Rollback(Exception):
        pass
    try:
        with transaction.atomic():
            site = ClientWebsite.objects.create(
                owner=request.user, subdomain='zz-dbcheck-rollback',
                site_name='DB check', website_type='companyprofile')
            site.bootstrap_from_schema()
            apply_template(site, 'clean_start')
            out.write(f'  OK: kurasa {site.pages.count()}, collections {site.collections.count()}\n')
            raise _Rollback
    except _Rollback:
        out.write('  Imerudishwa nyuma — hakuna kilichobaki kwenye database.\n')
    except Exception:
        out.write('  IMESHINDWA:\n' + traceback.format_exc())
    return HttpResponse(out.getvalue(), content_type='text/plain; charset=utf-8')


@login_required
def superadmin(request):
    """Dashboard ya wewe (staff): sites zote, stats, na actions."""
    if not request.user.is_staff:
        return redirect('builder:my_sites')

    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta

    now = timezone.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    all_sites = ClientWebsite.objects.select_related('owner')

    stats = {
        'total_sites': all_sites.count(),
        'published': all_sites.filter(is_published=True).count(),
        'premium': all_sites.filter(is_premium=True).count(),
        'suspended': all_sites.filter(is_suspended=True).count(),
        'new_week': all_sites.filter(created_at__gte=week_ago).count(),
        'new_month': all_sites.filter(created_at__gte=month_ago).count(),
        'total_users': User.objects.count(),
        'inquiries_total': SiteInquiry.objects.count(),
        'inquiries_week': SiteInquiry.objects.filter(created_at__gte=week_ago).count(),
        'ai_calls_week': AiUsageLog.objects.filter(created_at__gte=week_ago).count(),
    }

    # Filters + search
    q = (request.GET.get('q') or '').strip()
    flt = request.GET.get('f', 'all')
    sites = all_sites.annotate(
        items_count=Count('collections__items', distinct=True),
        inq_count=Count('inquiries', distinct=True),
    ).order_by('-created_at')

    if q:
        sites = sites.filter(
            Q(subdomain__icontains=q) | Q(site_name__icontains=q) |
            Q(owner__username__icontains=q) | Q(custom_domain__icontains=q))
    if flt == 'published':
        sites = sites.filter(is_published=True)
    elif flt == 'draft':
        sites = sites.filter(is_published=False)
    elif flt == 'premium':
        sites = sites.filter(is_premium=True)
    elif flt == 'suspended':
        sites = sites.filter(is_suspended=True)

    return render(request, 'builder/superadmin.html', {
        'stats': stats,
        'sites': sites[:200],
        'q': q,
        'flt': flt,
    })


@login_required
@require_POST
def superadmin_action(request, site_id):
    """Actions: toggle premium / suspend / publish."""
    if not request.user.is_staff:
        return redirect('builder:my_sites')
    site = get_object_or_404(ClientWebsite, id=site_id)
    action = request.POST.get('action')

    if action == 'toggle_premium':
        site.is_premium = not site.is_premium
        site.save(update_fields=['is_premium'])
        messages.success(request,
            f'{site.subdomain}: premium {"ON ⭐" if site.is_premium else "OFF"}')
    elif action == 'toggle_suspend':
        site.is_suspended = not site.is_suspended
        site.save(update_fields=['is_suspended'])
        site.bump_version()
        messages.success(request,
            f'{site.subdomain}: {"SUSPENDED 🚫" if site.is_suspended else "reactivated ✓"}')
    elif action == 'toggle_publish':
        site.is_published = not site.is_published
        site.save(update_fields=['is_published'])
        site.bump_version()
        messages.success(request,
            f'{site.subdomain}: {"published" if site.is_published else "unpublished"}')

    back = request.POST.get('back', '')
    return redirect(f"/builder/superadmin/?{back}")


# ── Navbar / Footer customization ──

@login_required
def nav_editor(request, site_id):
    """Ukurasa wa kuhariri navbar/footer: presets + custom HTML."""
    site = _my_site(request, site_id)
    from .nav_presets import get_preset_catalog, NAV_PRESETS, FOOTER_PRESETS
    return render(request, 'builder/nav_editor.html', {
        'site': site,
        'catalog': get_preset_catalog(),
        'nav_presets_json': json.dumps({k: v['html'] for k, v in NAV_PRESETS.items()}),
        'footer_presets_json': json.dumps({k: {'html': v['html'], 'css': v['css']}
                                           for k, v in FOOTER_PRESETS.items()}),
    })


@login_required
@require_POST
def ai_nav_generate(request, site_id):
    """AI ina-generate navbar au footer HTML kutoka maneno."""
    site = _my_site(request, site_id)
    from .ai import _check_rate_limit, AI_DAILY_LIMIT
    ok_rate, remaining = _check_rate_limit(request.user)
    if not ok_rate:
        return JsonResponse({'ok': False,
            'error': f'Daily AI limit reached ({AI_DAILY_LIMIT}). Try again tomorrow.'}, status=429)

    brief = (request.POST.get('brief') or '').strip()
    target = request.POST.get('target', 'nav')  # 'nav' au 'footer'
    if len(brief) < 3:
        return JsonResponse({'ok': False, 'error': 'Please describe what you want.'}, status=400)

    try:
        from . import ai_nav
        if target == 'footer':
            ok, html = ai_nav.generate_footer(site, brief)
        else:
            ok, html = ai_nav.generate_navbar(site, brief)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('ai_nav crashed')
        return JsonResponse({'ok': False,
            'error': f'Server error ({type(e).__name__}). Check /builder/ai/status/.'}, status=500)

    if not ok:
        return JsonResponse({'ok': False, 'error': html}, status=400)
    AiUsageLog.objects.create(user=request.user)
    return JsonResponse({'ok': True, 'html': html, 'remaining': remaining - 1})


@login_required
@require_POST
def nav_save(request, site_id):
    """Hifadhi navbar. mode=preset (jina) au mode=custom (HTML)."""
    site = _my_site(request, site_id)
    mode = request.POST.get('mode')
    from .nav_presets import NAV_PRESETS, HEADERS
    if mode == 'custom':
        site.custom_nav_html = (request.POST.get('html') or '')[:40000]
        site.nav_preset = ''
    elif mode == 'preset':
        key = request.POST.get('preset', '')
        if key in HEADERS or key in NAV_PRESETS:
            site.nav_preset = key
            site.custom_nav_html = ''
    elif mode == 'default':
        site.nav_preset = ''
        site.custom_nav_html = ''
    site.save(update_fields=['custom_nav_html', 'nav_preset'])
    site.bump_version()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def footer_save(request, site_id):
    """Hifadhi footer. mode=preset/custom/default."""
    site = _my_site(request, site_id)
    mode = request.POST.get('mode')
    from .nav_presets import FOOTER_PRESETS, FOOTERS
    if mode == 'custom':
        site.custom_footer_html = (request.POST.get('html') or '')[:40000]
    elif mode == 'preset':
        key = request.POST.get('preset', '')
        if key in FOOTERS or key in FOOTER_PRESETS:
            site.footer_preset = key
            site.custom_footer_html = ''
    elif mode == 'default':
        site.custom_footer_html = ''
        site.footer_preset = ''
    site.save(update_fields=['custom_footer_html', 'footer_preset'])
    site.bump_version()
    return JsonResponse({'ok': True})


# ── Global CSS + AI Theme (customization ya website nzima) ──

@login_required
@require_POST
def save_global_css(request, site_id):
    """Hifadhi Global CSS — inatumika pages ZOTE za site + public."""
    site = _my_site(request, site_id)
    css = (request.POST.get('global_css') or '')[:60000]
    site.global_css = css
    site.save(update_fields=['global_css'])
    site.bump_version()
    return JsonResponse({'ok': True, 'saved': True})


@login_required
def get_global_css(request, site_id):
    """Rudisha Global CSS ya sasa (kwa editor kuipakia)."""
    site = _my_site(request, site_id)
    return JsonResponse({'ok': True, 'global_css': site.global_css or ''})


@login_required
@require_POST
def ai_theme(request, site_id):
    """
    AI Theme: mtu anaandika 'nataka iwe ya kisasa, rangi za bahari' →
    AI ina-generate Global CSS block inayobadilisha look ya website nzima.
    """
    site = _my_site(request, site_id)

    from .ai import _check_rate_limit, AI_DAILY_LIMIT
    ok_rate, remaining = _check_rate_limit(request.user)
    if not ok_rate:
        return JsonResponse({'ok': False,
            'error': f'Daily AI limit reached ({AI_DAILY_LIMIT}). Try again tomorrow.'},
            status=429)

    brief = (request.POST.get('brief') or '').strip()
    if len(brief) < 3:
        return JsonResponse({'ok': False, 'error': 'Please describe the look you want.'}, status=400)

    try:
        from . import ai_theme as ai_theme_mod
        ok, css = ai_theme_mod.generate_theme_css(site, brief)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('ai_theme crashed')
        return JsonResponse({'ok': False,
            'error': f'Server error ({type(e).__name__}). Check /builder/ai/status/.'}, status=500)

    if not ok:
        return JsonResponse({'ok': False, 'error': css}, status=400)

    AiUsageLog.objects.create(user=request.user)
    return JsonResponse({'ok': True, 'css': css, 'remaining': remaining - 1})


# ── AI Field Helper (magic buttons) ────────────────────

@login_required
@require_POST
def ai_field(request):
    """
    Endpoint ya AJAX inayoitwa na kila magic ✨ button kwenye forms.
    POST fields:
        field_type — moja ya keys za FIELD_PROMPTS (site_name, tagline, ...)
        site_id    — hiari; ClientWebsite ambayo mtu anahariri
        context    — JSON (hiari) ya fields nyingine za form
        hint       — user note (hiari)
    """
    from . import ai_field as ai_field_mod

    # Rate limit share ile ile ya ai_assist
    from .ai import _check_rate_limit
    ok_rate, remaining = _check_rate_limit(request.user)
    if not ok_rate:
        from .ai import AI_DAILY_LIMIT
        return JsonResponse({'ok': False,
            'error': f'Daily AI limit reached ({AI_DAILY_LIMIT}). Try again tomorrow.'},
            status=429)

    field_type = (request.POST.get('field_type') or '').strip()
    hint = (request.POST.get('hint') or '').strip()

    site = None
    site_id = request.POST.get('site_id')
    if site_id:
        try:
            site = ClientWebsite.objects.get(id=site_id, owner=request.user)
        except (ClientWebsite.DoesNotExist, ValueError):
            pass

    ctx = {}
    ctx_raw = request.POST.get('context')
    if ctx_raw:
        try:
            parsed = json.loads(ctx_raw)
            if isinstance(parsed, dict):
                ctx = {k: v for k, v in parsed.items() if isinstance(v, (str, int, float))}
        except (ValueError, TypeError):
            pass

    try:
        ok, result = ai_field_mod.generate_field(field_type, site, ctx, hint)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('ai_field crashed')
        return JsonResponse({'ok': False,
            'error': f'Server error ({type(e).__name__}). '
                     'Check /builder/ai/status/ for diagnostics.'}, status=500)
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)

    # Log usage kwa ajili ya rate limit
    AiUsageLog.objects.create(user=request.user)
    return JsonResponse({'ok': True, 'text': result, 'remaining': remaining - 1})


@login_required
@require_POST
def ai_suggest_items(request, site_id, collection_id):
    """
    AI Coach action: generate items 4-6 mpya, ziingie kama HIDDEN drafts
    ili mtu azipitie kabla hazijaonekana kwenye website.
    """
    site = _my_site(request, site_id)
    collection = get_object_or_404(SiteCollection, id=collection_id, website=site)

    from .ai import _check_rate_limit, AI_DAILY_LIMIT
    ok_rate, remaining = _check_rate_limit(request.user)
    if not ok_rate:
        messages.error(request,
            f'Daily AI limit reached ({AI_DAILY_LIMIT}). Try again tomorrow.')
        return redirect('builder:collection_items', site_id=site.id,
                        collection_id=collection.id)

    from . import ai_oneshot
    ok, result = ai_oneshot.suggest_items(site, collection, count=5)
    if not ok:
        messages.error(request, result)
        return redirect('builder:collection_items', site_id=site.id,
                        collection_id=collection.id)

    created = 0
    for it in result:
        data = {'description': it['description'], 'price': it['price']}
        for k, v in (it.get('extra') or {}).items():
            if isinstance(v, (str, int, float)) and str(v).strip():
                data[str(k)[:40]] = str(v)[:600]
        SiteItem.objects.create(
            collection=collection, title=it['title'], data=data,
            is_visible=False,  # HIDDEN draft — mtu ana-review kwanza
        )
        created += 1

    AiUsageLog.objects.create(user=request.user)
    site.bump_version()
    messages.success(request,
        f'✨ AI added {created} suggestions as HIDDEN drafts — review each one, '
        f'add photos, then tick "Visible on website" to publish the ones you like.')
    return redirect('builder:collection_items', site_id=site.id,
                    collection_id=collection.id)


# ── Inquiries / Bookings ────────────────────────────────

@login_required
def inquiries_list(request, site_id):
    site = _my_site(request, site_id)
    status = request.GET.get('status', 'all')
    qs = site.inquiries.select_related('item').all()
    if status in ('new', 'contacted', 'closed'):
        qs = qs.filter(status=status)
    return render(request, 'builder/inquiries.html', {
        'site': site,
        'inquiries': qs[:200],
        'status': status,
        'counts': {
            'all': site.inquiries.count(),
            'new': site.inquiries.filter(status='new').count(),
            'contacted': site.inquiries.filter(status='contacted').count(),
            'closed': site.inquiries.filter(status='closed').count(),
        },
    })


@login_required
@require_POST
def inquiry_status(request, site_id, inquiry_id):
    site = _my_site(request, site_id)
    inq = get_object_or_404(SiteInquiry, id=inquiry_id, website=site)
    new_status = request.POST.get('status')
    if new_status in ('new', 'contacted', 'closed'):
        inq.status = new_status
        inq.save(update_fields=['status'])
    return redirect(f"/builder/site/{site.id}/inquiries/?status={request.POST.get('back', 'all')}")


# ── Assets (Supabase Storage) ───────────────────────────

@login_required
@require_POST
def asset_upload(request, site_id):
    """
    Mteja anapakia image ya tovuti yake kwenda Supabase.

    File inapita hapa, inakwenda Supabase, URL inarudi. Njia ya zamani
    (`asset_save`) ilipokea URL iliyokwisha pakiwa na browser kwenda
    Uploadcare; imeondolewa kwa sababu hakuna tovuti iliyoijengwa nayo.

    Folda ni kwa kila tovuti — image za mteja mmoja haziingiliani na
    za mwingine, na ikibidi kufuta tovuti, folda nzima inaondoka.
    """
    from apps import storage

    site = _my_site(request, site_id)
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'error': 'Hakuna file'}, status=400)

    result = storage.upload(f, folder=f'sites/{site.id}')
    if not result.get('success'):
        return JsonResponse({'error': result.get('error', 'Imeshindwa')}, status=400)

    asset = SiteAsset.objects.create(
        website=site, url=result['url'], file_name=f.name[:200],
    )
    return JsonResponse({'status': 'ok', 'id': asset.id, 'url': result['url']})


@login_required
def asset_list(request, site_id):
    site = _my_site(request, site_id)
    return JsonResponse({'assets': [
        {'id': a.id, 'url': a.url, 'name': a.file_name}
        for a in site.assets.all()[:100]
    ]})
