# app/view.py
from django.shortcuts import render
from .models import Question,Service,Team,BlogPost
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.models import User, auth
from django.contrib.auth.decorators import login_required

# `send_mail` haikuwahi kuimportwa. Contact form ilianguka kwa
# NameError kwenye KILA ujumbe tangu iandikwe, na `except Exception`
# iliyoizunguka iliifanya ionekane kama kosa la SMTP badala ya bug.
# Hakuna ujumbe wa mteja uliowahi kufika.
import logging
from django.core.mail import send_mail


# # Home Page
# def home(request):
#     from apps.seo.schema import (
#         organization_schema, website_schema, local_business_schema,
#         jamiibot_product_schema, faq_schema, render_schemas
#     )
#     team = Team.objects.all()

#     faqs = [
#         ("Je, JamiiTek ni nini?", "JamiiTek ni kampuni ya teknolojia Tanzania inayotengeneza websites, apps, na AI WhatsApp bots kwa biashara."),
#         ("What is JamiiBot?", "JamiiBot is an AI-powered WhatsApp chatbot that responds to customer questions 24/7 in Swahili and English, starting from TZS 15,000/month."),
#         ("How much does a website cost in Tanzania?", "JamiiTek builds websites starting from TZS 150,000. Price depends on complexity, features, and design requirements."),
#         ("Je, JamiiBot inafanya kazi vipi?", "JamiiBot inajibu maswali ya wateja kupitia WhatsApp kiotomatiki, saa 24 kwa lugha ya Kiswahili na Kiingereza."),
#         ("Do you offer web hosting in Tanzania?", "Yes, JamiiTek offers reliable web hosting with 99.9% uptime, SSL certificates, and daily backups."),
#         ("How long does website development take?", "Most websites are delivered within 2-6 weeks depending on scope and content availability."),
#         ("Je, mnaunda WhatsApp bot Tanzania?", "Ndiyo! JamiiBot ni AI WhatsApp bot ya biashara Tanzania. Inajibu wateja saa 24 bila msaada wa binadamu."),
#         ("What programming languages do you use?", "We use Python/Django, JavaScript, React, and modern web technologies for all our projects."),
#     ]

#     schema_html = render_schemas(
#         organization_schema(),
#         website_schema(),
#         local_business_schema(),
#         jamiibot_product_schema(),
#         faq_schema(faqs),
#     )

#     context = {
#         'team': team,
#         'schema_markup': schema_html,
#         'latest_posts': BlogPost.objects.filter(status='published')[:3],
#         'page_title': 'JamiiTek — Web Development & AI WhatsApp Bot Tanzania',
#         'page_desc': (
#             "JamiiTek: Tanzania's leading web developer. We build websites, AI WhatsApp bots "
#             "(JamiiBot), web hosting & domains. Serving Dar es Salaam and all Tanzania. "
#             "Tunajenga website Tanzania. Bot WhatsApp Tanzania."
#         ),
#         'canonical': 'https://jamiitek.com/',
#     }
#     return render(request, 'index.html', context)





# Replacement for the `home` view in apps/views.py
#
# Only the context changes — the SEO block is untouched.

from django.shortcuts import render

from .models import Team, BlogPost, Service
from .site_content import HeroSlide, PortfolioItem, Testimonial


def home(request):
    from apps.seo.schema import (
        organization_schema, website_schema, local_business_schema,
        jamiibot_product_schema, faq_schema, render_schemas
    )

    faqs = [
        ("Je, JamiiTek ni nini?", "JamiiTek ni kampuni ya teknolojia Tanzania inayotengeneza websites, apps, na AI WhatsApp bots kwa biashara."),
        ("What is JamiiBot?", "JamiiBot is an AI-powered WhatsApp chatbot that responds to customer questions 24/7 in Swahili and English, starting from TZS 15,000/month."),
        ("How much does a website cost in Tanzania?", "JamiiTek builds websites starting from TZS 150,000. Price depends on complexity, features, and design requirements."),
        ("Je, JamiiBot inafanya kazi vipi?", "JamiiBot inajibu maswali ya wateja kupitia WhatsApp kiotomatiki, saa 24 kwa lugha ya Kiswahili na Kiingereza."),
        ("Do you offer web hosting in Tanzania?", "Yes, JamiiTek offers reliable web hosting with 99.9% uptime, SSL certificates, and daily backups."),
        ("How long does website development take?", "Most websites are delivered within 2-6 weeks depending on scope and content availability."),
        ("Je, mnaunda WhatsApp bot Tanzania?", "Ndiyo! JamiiBot ni AI WhatsApp bot ya biashara Tanzania. Inajibu wateja saa 24 bila msaada wa binadamu."),
        ("What programming languages do you use?", "We use Python/Django, JavaScript, React, and modern web technologies for all our projects."),
    ]

    schema_html = render_schemas(
        organization_schema(),
        website_schema(),
        local_business_schema(),
        jamiibot_product_schema(),
        faq_schema(faqs),
    )

    context = {
        # ── slider content (all admin-managed) ──────────────────
        # Slaidi bila picha bado inaonekana (asili ya navy), ili usidhani
        # admin haifanyi kazi. list() — template inaitumia mara kadhaa
        # (slaidi, dots, hesabu, preload); bila list() kila moja ni swali.
        'hero_slides':  list(HeroSlide.objects.filter(is_active=True)),
        # Project bila picha bado inaonekana (kadi ina herufi ya kwanza),
        # badala ya kupotea kimya na kukufanya udhani admin haifanyi kazi.
        'portfolio':    list(PortfolioItem.objects.filter(is_featured=True)[:12]),
        'testimonials': Testimonial.objects.filter(is_active=True)[:9],
        'services':     list(Service.objects.filter(show_on_home=True).order_by('order', 'created_at')[:12]),
        'team':         Team.objects.all(),
        'latest_posts': BlogPost.objects.filter(status='published')[:3],

        # ── SEO (unchanged) ─────────────────────────────────────
        'schema_markup': schema_html,
        'page_title': 'JamiiTek — Web Development & AI WhatsApp Bot Tanzania',
        'page_desc': (
            "Websites, AI WhatsApp bots (JamiiBot), hosting and domains for businesses in "
            "Tanzania. Built in Dar es Salaam — fast, secure and mobile-first."
        ),
        'canonical': 'https://www.jamiitek.com/',
    }
    return render(request, 'index.html', context)

# Elimu ya Ufahamu
def service(request):
    from apps.seo.schema import (
        organization_schema, faq_schema, render_schemas, breadcrumb_schema
    )
    services = Service.objects.all()
    questions = Question.objects.all()

    # Build FAQ from DB questions
    faqs_data = [(q.question, q.answer) for q in questions] if questions else [
        ("What web services does JamiiTek offer?", "JamiiTek offers website development, mobile app development, AI WhatsApp bots, web hosting, domain registration, UI/UX design, and system integration."),
        ("How much does website development cost in Tanzania?", "Websites start from TZS 150,000 for basic sites up to TZS 5,000,000+ for complex web applications."),
        ("Je, mnatengeneza website Tanzania?", "Ndiyo, JamiiTek inatengeneza websites za hali ya juu Tanzania kwa bei nafuu."),
        ("Do you build mobile apps?", "Yes, we develop Android and iOS apps using modern frameworks."),
    ]

    schema_html = render_schemas(
        organization_schema(),
        breadcrumb_schema([("Home", "/"), ("Services", "/service/")]),
        faq_schema(faqs_data),
    )

    context = {
        'services': services,
        'questions': questions,
        'schema_markup': schema_html,
        'page_title': 'Services — Web Development, AI Bots & Hosting | JamiiTek',
        'page_desc': 'JamiiTek services: website development, AI WhatsApp bots, web hosting, domain registration, mobile apps, UI/UX design. Best web developer in Tanzania.',
        'canonical': 'https://www.jamiitek.com/service/',
        'page_keywords': 'web development services Tanzania, AI WhatsApp bot, website design Tanzania, web hosting Tanzania, domain registration Tanzania, mobile app Tanzania',
    }
    return render(request, 'service.html', context)

# Warsha za Kiroho
def contact(request):
    return render(request, 'contact.html')

# Ushuhuda wa Wateja
def About(request):
    """Ukurasa wa About — namba zote ni HALISI kutoka database.

    Awali ukurasa ulidai "since 2019", "192+ projects" na "5★ rating" bila
    chanzo chochote. Sasa zinajihesabu: kazi zilizo hewani, huduma, na
    websites tunazohost. Namba ikiwa 0, haionyeshwi.
    """
    from .models import ManagedWebsite, Service
    from .site_content import PortfolioItem
    stats = {
        'projects': PortfolioItem.objects.filter(is_featured=True).count(),
        'services': Service.objects.filter(show_on_home=True).count(),
        'hosted': ManagedWebsite.objects.filter(status='active').count(),
    }
    return render(request, 'about.html', {
        'stats': stats,
        'services': list(Service.objects.filter(show_on_home=True).order_by('order', 'created_at')[:8]),
        'work': list(PortfolioItem.objects.filter(is_featured=True)[:3]),
    })

def contact(request):
    """
    Contact form view with Turnstile protection
    
    Flow:
    1. GET — render form kwa TURNSTILE_SITEKEY
    2. POST — frontend sends cf-turnstile-response token
    3. Mixin au middleware validates token
    4. Form cleaned (kama valid)
    5. Email sent to admin
    """
    
    if request.method == 'POST':
        # ── Honeypot (mtego wa bot) ──────────────────────────────
        # Sehemu ya siri iliyofichwa kwa CSS. Binadamu haioni, kwa hiyo
        # haijazi. Bot za spam hujaza KILA sehemu — zikijaza hii,
        # tunanyamaza (hatutumii email) na kuonyesha "mafanikio" ili
        # bot isijue imekamatwa. Hii inafanya kazi HATA bila Turnstile
        # keys, kwa hiyo inazuia spam mara moja.
        if request.POST.get('company_website', '').strip():
            logger.info("Contact honeypot tripped — spam dropped silently.")
            messages.success(request, "Thank you! We'll get back to you within 24 hours.")
            return render(request, 'contact.html')

        # Pata data kutoka POST
        full_name = request.POST.get('full_name', '')
        email = request.POST.get('email', '')
        subject = request.POST.get('subject', '')
        message = request.POST.get('message', '')
        
        # Token verification ni automatic via middleware (kama enabled)
        # Kama hapo na error, middleware itarudi 403 na request hautafikia hapa
        
        # Validate required fields
        if not all([full_name, email, subject, message]):
            messages.error(request, "Please fill in all fields.")
            return render(request, 'contact.html')
        
        # Email validation (kama inataka zaidi)
        try:
            validate_email = email.endswith('.com') or email.endswith('.co.tz') or '@' in email
            if not validate_email:
                messages.error(request, "Invalid email address.")
                return render(request, 'contact.html')
        except:
            messages.error(request, "Invalid email address.")
            return render(request, 'contact.html')
        
        # Send email to admin
        try:
            admin_email = 'info@jamiitek.com'
            send_mail(
                subject=f"New Contact Form: {subject}",
                message=f"""
From: {full_name} <{email}>
Subject: {subject}
 
Message:
{message}
 
---
Contact form message from JamiiTek website
                """,
                from_email='info@jamiitek.com',
                recipient_list=[admin_email],
                fail_silently=False,
            )
            
            # Optional: Send confirmation email to customer
            send_mail(
                subject="We received your message — JamiiTek",
                message=f"""
Hi {full_name},
 
Thank you for reaching out. We've received your message and will respond within 24 hours.
 
Subject: {subject}
 
Best regards,
JamiiTek Team
                """,
                from_email='info@jamiitek.com',
                recipient_list=[email],
                fail_silently=True,
            )
            
            ujumbe = "✓ Your message has been sent successfully! We'll respond within 24 hours."
            messages.success(request, ujumbe)
            
        except Exception:
            # Kosa halisi linaenda logs, si kwa mteja. "name 'send_mail' is
            # not defined" halimsaidii, na linafichua muundo wa ndani.
            logger.exception('Contact form: kutuma email kumeshindwa')
            from apps.contact import contact
            ujumbe = (f"Samahani, ujumbe haujatoka. Tafadhali tupigie "
                      f"{contact()['phone_display']} au andika info@jamiitek.com.")
            messages.error(request, ujumbe)
            return render(request, 'contact.html', {'ujumbe': ujumbe})
    
    return render(request, 'contact.html')



def newsletter_subscribe(request):
    """Fomu ya newsletter kwenye footer (Home, Services, About, Contact).

    Awali fomu hii ilituma email PEKEE kwenda /contact/, ambayo inadai
    jina, mada na ujumbe pia — kila mgeni aliyejiandikisha alipata
    "Please fill in all fields" na hakuna aliyesajiliwa. Sasa ina njia
    yake: email moja inathibitishwa, timu inapata taarifa kwa barua pepe.

    AJAX (footer ina JS) -> JSON. Bila JS -> inarudi ukurasa uliotoka
    na ?subscribed=ok|invalid|error, ambayo footer inaionyesha.
    """
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    from django.http import JsonResponse
    from django.utils.http import url_has_allowed_host_and_scheme

    if request.method != 'POST':
        return redirect('home')

    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    back = request.META.get('HTTP_REFERER') or '/'
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        back = '/'
    from urllib.parse import urlsplit
    back = urlsplit(back).path or '/'

    def reply(state, text, code=200):
        if ajax:
            return JsonResponse({'ok': state == 'ok', 'message': text}, status=code)
        return redirect(f'{back}?subscribed={state}#site-footer')

    # Mtego wa bot: sehemu iliyofichwa; binadamu haijazi
    if request.POST.get('company_website', '').strip():
        return reply('ok', "You're subscribed. Asante!")

    email = (request.POST.get('email') or '').strip()
    try:
        validate_email(email)
    except ValidationError:
        return reply('invalid', 'Please enter a valid email address.', 400)

    try:
        send_mail(
            subject='New newsletter subscriber',
            message=f'{email} subscribed to the JamiiTek newsletter from {back}.',
            from_email='info@jamiitek.com',
            recipient_list=['info@jamiitek.com'],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Newsletter: kutuma taarifa kumeshindwa')
        return reply('error', 'Something went wrong. Please try again or WhatsApp us.', 502)
    return reply('ok', "You're subscribed. Asante!")



import os
from django.http import HttpResponse, Http404
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import WebsiteType, Client, ProjectProposal
from .forms import DynamicProposalForm

def select_website_type(request):
    website_types = WebsiteType.objects.all()
    # "Order This" kutoka /templates/preview/<pk>/ inabeba ?template=<pk>
    ref_template = None
    tpl_id = request.GET.get('template')
    if tpl_id:
        ref_template = WebsiteTemplate.objects.filter(
            pk=tpl_id, is_active=True).first()
    # Templates ↔ proposal: "hujaona template unayoipenda? tuandikie" — na
    # kinyume chake, template za kuchagua kama mfano wa muundo unaoutaka.
    active = WebsiteTemplate.objects.filter(is_active=True)
    featured = list(active.filter(category=ref_template.category).exclude(pk=ref_template.pk)[:4]) if ref_template else []
    featured += list(active.exclude(pk__in=[t.pk for t in featured] + ([ref_template.pk] if ref_template else []))
                     .order_by('order', '-created_at')[:4 - len(featured)])
    return render(request, 'select_website.html', {
        'website_types': website_types,
        'ref_template': ref_template,
        'featured_templates': featured,
        'template_count': active.count(),
        'title': 'Select Website Type'
    })


# ═══════════════════════════════════════════════════════════════════
# apps/views.py — REPLACEMENT kwa `dynamic_form`
#
# Badilisha function nzima ya `dynamic_form` (ilianzia mstari 200)
# na hii. Hakuna kingine kwenye file kinachohitaji kubadilishwa.
#
# Ongeza import hizi juu ya file kama hazipo:
#     import logging
#     logger = logging.getLogger(__name__)
# ═══════════════════════════════════════════════════════════════════

import logging

logger = logging.getLogger(__name__)


def _resolve_client(cleaned):
    """
    Pata Client anayelingana na email, au tengeneza mpya.

    KWA NINI SI get_or_create:
    `Client.email` HAINA unique=True (models.py:112), lakini get_or_create
    inaita .get() ndani yake — hivyo inavunjika na MultipleObjectsReturned
    mara tu duplicates zinapoingia. Duplicates zinatokea kwa sababu sehemu
    tatu tofauti zinatengeneza Client: portal register, chatbot fallback
    (client_portal_views.py:49), na form hii.

    .first() haiwezi kuvunjika hata kama kuna duplicates kumi.
    order_by('pk') inahakikisha tunachukua rekodi ileile kila mara,
    si ya nasibu — muhimu ili proposals za mteja zisitawanyike.
    """
    email = (cleaned.get('client_email') or '').strip().lower()

    # iexact: 'Willy@x.com' na 'willy@x.com' ni mtu mmoja
    matches = Client.objects.filter(email__iexact=email).order_by('pk')
    client = matches.first()

    if client is None:
        return Client.objects.create(
            email=email,
            name=(cleaned.get('client_name') or '').strip(),
            phone=(cleaned.get('client_phone') or '').strip(),
            company=(cleaned.get('client_company') or '').strip(),
        )

    count = matches.count()
    if count > 1:
        logger.warning(
            "Client duplicates kwa %s: %s rekodi (pk: %s). Natumia pk=%s.",
            email, count, list(matches.values_list('pk', flat=True)), client.pk,
        )

    # Jaza sehemu tupu TU. Mteja anaweza kuwa alijaza jina kamili kwenye
    # portal; proposal form isilifute kwa jina fupi alilotumia hapa.
    updated = []
    for field, value in (
        ('name',    cleaned.get('client_name')),
        ('phone',   cleaned.get('client_phone')),
        ('company', cleaned.get('client_company')),
    ):
        value = (value or '').strip()
        if value and not getattr(client, field):
            setattr(client, field, value)
            updated.append(field)

    if updated:
        client.save(update_fields=updated)

    return client


def _notify_new_proposal(proposal):
    """Proposal mpya → email kwa JamiiTek (nyuma, mteja asisubiri SMTP)."""
    import threading
    rows, total = _build_requirement_rows(proposal.requirements if isinstance(proposal.requirements, dict) else {})

    def _send():
        try:
            from apps.utils.email_notifications import send_new_proposal_notice
            send_new_proposal_notice(proposal, rows, total)
        except Exception:
            logger.exception('new proposal notice failed')
    threading.Thread(target=_send, daemon=True).start()


def dynamic_form(request, website_type_id):
    website_type = get_object_or_404(WebsiteType, id=website_type_id)

    # DynamicProposalForm inakubali request= tu kama TurnstileFormMixin
    # imeongezwa. Hii inaruhusu view kufanya kazi kabla NA baada ya mixin,
    # bila TypeError.
    form_kwargs = {}
    try:
        from apps.turnstile import TurnstileFormMixin
        if issubclass(DynamicProposalForm, TurnstileFormMixin):
            form_kwargs['request'] = request
    except ImportError:
        pass

    if request.method == 'POST':
        form = DynamicProposalForm(website_type.name, request.POST, **form_kwargs)

        if form.is_valid():
            client = _resolve_client(form.cleaned_data)

            requirements = dict(form.cleaned_data)
            # Token ya Turnstile ni ya matumizi ya mara moja — isihifadhiwe
            # kwenye JSON wala isionekane kwenye proposal ya mteja.
            requirements.pop('turnstile', None)

            tpl_id = request.POST.get('reference_template')
            if tpl_id:
                ref = WebsiteTemplate.objects.filter(
                    pk=tpl_id, is_active=True).first()
                if ref:
                    requirements['reference_template'] = {
                        'id': ref.pk,
                        'name': ref.name,
                        'category': ref.get_category_display(),
                        'preview_url': ref.get_absolute_url(),
                    }

            proposal = ProjectProposal.objects.create(
                client=client,
                website_type=website_type,
                requirements=requirements,
            )
            _notify_new_proposal(proposal)

            # Kivinjari hiki tu (pamoja na staff na mteja mwenye akaunti)
            # kinaweza kuona quotation hii — angalia _can_view_proposal.
            mine = request.session.get('my_proposals', [])
            request.session['my_proposals'] = (mine + [proposal.id])[-20:]

            return redirect(f"{reverse('proposal_preview', args=[proposal.id])}?sent=1")

    else:
        initial_data = {}
        if request.user.is_authenticated:
            profile = Client.objects.filter(user=request.user).first()
            if profile:
                initial_data = {
                    'client_name':    profile.name,
                    'client_email':   profile.email,
                    'client_phone':   profile.phone,
                    'client_company': profile.company,
                }

        form = DynamicProposalForm(
            website_type.name, initial=initial_data, **form_kwargs)

    # Gawa fields: client details dhidi ya project requirements
    client_fields = []
    project_fields = []
    for field in form:
        if field.name == 'turnstile':
            continue          # inarendwa peke yake kwenye template
        if field.name.startswith('client_'):
            client_fields.append(field)
        else:
            project_fields.append(field)

    ref_template = None
    tpl_id = request.GET.get('template') or request.POST.get('reference_template')
    if tpl_id:
        ref_template = WebsiteTemplate.objects.filter(
            pk=tpl_id, is_active=True).first()

    context = {
        'form': form,
        'website_type': website_type,
        'client_fields': client_fields,
        'project_fields': project_fields,
        'ref_template': ref_template,
        'title': f'{website_type.name} Requirements',
    }

    return render(request, 'dynamic_form.html', context)

# ═══════════════════════════════════════════════════════════════════
# PATCH kwa apps/views.py
# Badilisha function ya `proposal_preview` (ilikuwa mstari ~275)
# ═══════════════════════════════════════════════════════════════════

from django.shortcuts import get_object_or_404


# ── Helper: gawa "Feature Name | 250000" kuwa (jina, bei) ──────────
def _parse_choice(raw):
    """
    Values za checkbox zinahifadhiwa kama 'Online Payments | 250000'.
    Rudisha (name, price_int). Kama hakuna '|', bei ni 0.
    """
    text = str(raw)
    if '|' not in text:
        return text.strip(), 0

    name, _, price_part = text.rpartition('|')
    digits = ''.join(ch for ch in price_part if ch.isdigit())
    try:
        price = int(digits) if digits else 0
    except ValueError:
        price = 0
    return name.strip(), price


def _build_requirement_rows(requirements):
    """
    Geuza requirements dict kuwa rows tayari kwa template, na uhesabu jumla.

    MUHIMU: bei zinatokana TU na sehemu iliyo baada ya '|' kwenye chaguo
    zilizochaguliwa. Hesabu ya zamani ilikuwa inakusanya KILA tarakimu
    kwenye table — ikiwemo namba ya simu ya mteja — hivyo jumla ilikuwa
    inaweza kuwa mabilioni. Hii ndiyo sababu ya kuhesabu upande wa server.
    """
    rows = []
    total = 0

    for key, value in requirements.items():
        if key == 'reference_template' or key.startswith('client_'):
            continue
        if key in ('turnstile', 'csrfmiddlewaretoken'):
            continue

        label = key.replace('_', ' ').strip().title()

        # Chaguo nyingi (checkbox) → list
        if isinstance(value, (list, tuple)):
            items = []
            for raw in value:
                name, price = _parse_choice(raw)
                total += price
                items.append({'name': name, 'price': price or None})
            if items:
                rows.append({'label': label, 'items': items, 'text': None})

        # Jibu la maandishi
        else:
            text = str(value).strip() if value not in (None, '') else ''
            rows.append({'label': label, 'items': None, 'text': text})

    return rows, total


def _can_view_proposal(request, proposal):
    """
    Quotation ina jina, email, simu na bajeti ya mteja. Awali yeyote angeweza
    kupitia /proposals/preview/1/, /2/, /3/... na kuona data za wateja wote.
    Sasa: staff, mteja mwenyewe (akaunti), au kivinjari kilichoituma.
    """
    user = request.user
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return True
    if proposal.id in request.session.get('my_proposals', []):
        return True
    owner = getattr(proposal.client, 'user', None)
    return bool(user.is_authenticated and owner and owner.pk == user.pk)


def proposal_preview(request, proposal_id):
    proposal = get_object_or_404(ProjectProposal, id=proposal_id)
    if not _can_view_proposal(request, proposal):
        raise Http404

    requirements = proposal.requirements
    if isinstance(requirements, str):
        import json
        try:
            requirements = json.loads(requirements)
        except Exception:
            requirements = {}
    if not isinstance(requirements, dict):
        requirements = {}

    rows, total_cost = _build_requirement_rows(requirements)

    return render(request, 'proposal_preview.html', {
        'proposal': proposal,
        'requirement_rows': rows,
        'total_cost': total_cost,
        'just_sent': request.GET.get('sent') == '1',
        'title': 'Proposal Preview',
    })



from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.shortcuts import redirect
 
from apps.utils.proposal_pdf import generate_proposal_pdf
 
 
def generate_pdf(request, proposal_id):
    proposal = get_object_or_404(ProjectProposal, id=proposal_id)
    if not _can_view_proposal(request, proposal):
        raise Http404
 
    pdf_bytes = generate_proposal_pdf(proposal)
 
    if not pdf_bytes:
        # Ya zamani ilirudisha HTML mbichi ndani ya response ya PDF —
        # browser ilipakua faili bovu. Sasa mteja anarudi kwenye preview
        # na ujumbe unaoeleweka.
        messages.error(
            request,
            'We could not build the PDF just now. Please try again, '
            'or contact us and we will send it to you directly.'
        )
        return redirect('proposal_preview', proposal_id=proposal.id)
 
    filename = f'JamiiTek-Quotation-JT-{proposal.id}.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

# ============================================================
# WEBSITE TEMPLATES MARKETPLACE
# ============================================================
from .models import WebsiteTemplate
from django.utils.safestring import mark_safe

def _template_categories(all_templates):
    """Jamii zenye template, na idadi yake (kwa chips na kurasa za jamii)."""
    from collections import Counter
    from . import template_seo
    counts = Counter(all_templates.values_list('category', flat=True))
    labels = dict(WebsiteTemplate.CATEGORY_CHOICES)
    return [{'key': k, 'label': labels.get(k, k), 'count': n,
             'slug': template_seo.cat_slug(template_seo.cat_key(k))}
            for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]


def templates_marketplace(request, cat_slug=None):
    """Templates zote — au za jamii moja (/templates/c/<jamii>/, ukurasa wa SEO)."""
    from django.http import Http404
    from . import template_seo
    all_templates = WebsiteTemplate.objects.filter(is_active=True)
    categories = _template_categories(all_templates)

    category, cat = request.GET.get('category', 'all'), None
    if cat_slug:
        cat = next((c for c in categories if c['slug'] == cat_slug), None)
        if cat is None:
            raise Http404
        category = cat['key']
    templates = all_templates if category == 'all' else all_templates.filter(category=category)

    seo = None
    if cat:
        info = template_seo.cat_info(cat['key'])
        noun = info['noun'].title()
        seo = {
            'title': f'{noun} Website Templates — Tanzania | JamiiTek',
            'h1': f'{noun} website templates',
            'description': template_seo.plain(
                f'{cat["count"]} premium {info["noun"]} website template{"s" if cat["count"] != 1 else ""} for '
                f'{info["who"]}. Customize free in the JamiiTek Builder and publish today.', 158),
            'intro': f'Designs made for {info["who"]} in Tanzania and East Africa — '
                     f'{", ".join(f.lower() for f in info["features"])}. Kwa Kiswahili: templates za website ya {info["sw"]}.',
            'keywords': f'{info["noun"]} website template, {info["noun"]} website Tanzania, '
                        f'website ya {info["sw"]}, template ya {info["sw"]}, JamiiTek templates',
        }
        url = f'{template_seo.BASE_URL}/templates/c/{cat_slug}/'
        list_name = seo['h1']
    else:
        url, list_name = f'{template_seo.BASE_URL}/templates/', 'JamiiTek website templates'

    import json
    tpl_list = list(templates)
    return render(request, 'templates_marketplace.html', {
        'templates': tpl_list,
        'selected_category': category,
        'total_count': all_templates.count(),
        'filtered_count': len(tpl_list),
        'categories': categories,
        'seo': seo,
        'canonical': url,
        'item_list_ld': json.dumps(template_seo.item_list_ld(tpl_list, list_name, url), ensure_ascii=False),
    })


def template_detail(request, slug):
    """Ukurasa kamili wa template moja — ndio unaopatikana Google na kwenye AI."""
    import json
    from . import template_seo
    tpl = get_object_or_404(WebsiteTemplate, slug=slug, is_active=True)
    related = list(WebsiteTemplate.objects.filter(is_active=True, category=tpl.category)
                   .exclude(pk=tpl.pk).order_by('order', '-created_at')[:3])
    if len(related) < 3:
        related += list(WebsiteTemplate.objects.filter(is_active=True).exclude(pk=tpl.pk)
                        .exclude(pk__in=[r.pk for r in related]).order_by('order', '-created_at')[:3 - len(related)])
    return render(request, 'template_detail.html', {
        'tpl': tpl,
        'seo_title': template_seo.title(tpl),
        'seo_description': template_seo.description(tpl),
        'seo_keywords': template_seo.keywords(tpl),
        'canonical': template_seo.BASE_URL + tpl.get_absolute_url(),
        'cat_url': f'/templates/c/{template_seo.cat_slug(template_seo.cat_key(tpl))}/',
        'cat_noun': template_seo.cat_info(tpl)['noun'],
        'features': template_seo.features(tpl),
        'common_features': template_seo.COMMON_FEATURES,
        'article': template_seo.article(tpl),
        'faq': template_seo.faq(tpl),
        'related': related,
        'json_ld': [json.dumps(block, ensure_ascii=False) for block in template_seo.json_ld(tpl)],
    })


def template_preview(request, pk):
    """Wrapper page — preview bar + device toggle + iframe"""
    from django.shortcuts import get_object_or_404
    tpl = get_object_or_404(WebsiteTemplate, pk=pk, is_active=True)
    from . import template_seo
    # Google ipe ukurasa kamili (/templates/<slug>/) sifa, si fremu hii
    return render(request, 'template_preview.html', {
        'template': tpl, 'canonical': template_seo.BASE_URL + tpl.get_absolute_url()})


from django.views.decorators.clickjacking import xframe_options_exempt

@xframe_options_exempt
def template_preview_raw(request, pk):
    """Serves the raw template HTML inside the iframe — exempt from X-Frame-Options"""
    from django.shortcuts import get_object_or_404
    from django.http import HttpResponse
    tpl = get_object_or_404(WebsiteTemplate, pk=pk, is_active=True)
    if not tpl.preview_html or not tpl.preview_html.strip():
        resp = HttpResponse('<p style="font-family:sans-serif;padding:2rem;color:#999">Hakuna HTML iliyowekwa kwa template hii.</p>', content_type='text/html; charset=utf-8')
    else:
        resp = HttpResponse(tpl.preview_html, content_type='text/html; charset=utf-8')
    # HTML ghafi ya demo isiingie Google kama ukurasa wake (maudhui ya mfano,
    # nakala); ukurasa wa template ndio unaoorodheshwa.
    resp['X-Robots-Tag'] = 'noindex, follow'
    return resp