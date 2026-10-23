# apps/client_portal_views.py
# JamiiTek Client Portal — Website owners can log in and manage their account

import secrets
import logging
from decimal import Decimal
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

from apps.utils.email_notifications import send_welcome_email
from django.core.mail import send_mail
from .account_billing import build_account

from .models import (
    Client, ManagedWebsite, HostingPayment, ClientNotification, WebsiteFeature,
    DomainRecord, EmailHostingPlan, EmailHostingPayment,
    HostingConfiguration, DomainDNSRecord,
)


# ── HELPER ─────────────────────────────────────────────────────────

def client_required(view_func):
    """Require login as a client. Accepts portal, JamiiBot and Web Builder accounts alike."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/portal/login/?next={request.path}')
        if request.user.is_staff or request.user.is_superuser:
            return redirect('/manage/')
        # Akaunti moja kwa Portal, JamiiBot na Web Builder (apps/accounts_link.py)
        from apps.accounts_link import ensure_client_profile
        request.client_profile = ensure_client_profile(request.user)
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── REGISTER ───────────────────────────────────────────────────────
from apps.turnstile import verify_token, get_client_ip
from apps.contact import contact as _contact
from apps.security import same_site_logout

def portal_register(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect('portal_dashboard')

    if request.method == 'POST':
        errors = []

        # ── Turnstile kwanza ──
        ok, codes = verify_token(
            request.POST.get('cf-turnstile-response'),
            get_client_ip(request),
        )
        if not ok:
            errors.append('Uthibitisho umeshindikana. Tafadhali jaribu tena.')

        username    = request.POST.get('username', '').strip()
        email       = request.POST.get('email', '').strip()
        phone       = request.POST.get('phone', '').strip()
        full_name   = request.POST.get('full_name', '').strip()
        website_name = request.POST.get('website_name', '').strip()
        website_url  = request.POST.get('website_url', '').strip()
        password    = request.POST.get('password', '')
        password2   = request.POST.get('password2', '')

        if not all([username, email, full_name, password]):
            errors.append('All fields except phone are required.')
        if password != password2:
            errors.append('Passwords do not match.')
        from apps.security import password_problems
        errors += password_problems(password, username, email, full_name)
        if User.objects.filter(username__iexact=username).exists():
            errors.append('That username is already taken.')
        if email and User.objects.filter(email__iexact=email).exists():
            errors.append('That email is already registered.')

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username, email=email, password=password,
                        first_name=full_name.split()[0],
                        last_name=' '.join(full_name.split()[1:]) if len(full_name.split()) > 1 else '',
                    )
                    client = Client.objects.create(
                        user=user, name=full_name,
                        email=email, phone=phone,
                        company=website_name,
                    )

                # Welcome email — never crash registration
                try:
                    send_welcome_email(client)
                except Exception as e:
                    logger.warning(f"Welcome email failed (non-fatal): {e}")

                # Store website URL note
                if website_url:
                    try:
                        from .models import ClientNotification
                        ClientNotification.objects.create(
                            website=None, client=client,
                            notification_type='general',
                            subject=f'New Registration — Website URL: {website_url}',
                            message=(
                                f'Client {full_name} registered.\n'
                                f'Website URL: {website_url}\n'
                                f'Phone: {phone}\n'
                                f'Please add their website in the management panel.'
                            ),
                            email_sent=False,
                        )
                    except Exception as e:
                        logger.warning(f"Notification creation failed (non-fatal): {e}")

                # Notify staff
                try:
                    send_mail(
                        subject=f'New Portal Registration — {full_name}',
                        message=(
                            f'New client registered on JamiiTek portal.\n\n'
                            f'Name: {full_name}\nEmail: {email}\nPhone: {phone}\n'
                            f'Website interest: {website_name}\nUsername: {username}\n\n'
                            f'Log in to the management panel to review.'
                        ),
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
                        recipient_list=[getattr(settings, 'ADMIN_EMAIL', 'info@jamiitek.com')],
                        fail_silently=True,
                    )
                except Exception as e:
                    logger.warning(f"Staff notification email failed (non-fatal): {e}")

                login(request, user)
                messages.success(request, f'Welcome, {full_name}! Your account has been created.')
                return redirect('portal_dashboard')

            except Exception as e:
                logger.exception(f"Portal registration failed: {e}")
                messages.error(request, 'Registration failed due to a technical error. Please try again or contact support.')

    return render(request, 'portal/register.html', {'title': 'Create Account'})


# ── LOGIN ──────────────────────────────────────────────────────────
from apps.turnstile import verify_token, get_client_ip

def portal_login(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect('portal_dashboard')

    error = None
    if request.method == 'POST':
        # ── Turnstile kwanza, kabla ya kugusa password ──
        ok, codes = verify_token(
            request.POST.get('cf-turnstile-response'),
            get_client_ip(request),
        )
        if not ok:
            error = 'Uthibitisho umeshindikana. Tafadhali jaribu tena.'
        else:
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            if '@' in username:   # email badala ya username (kama Web Builder)
                u = User.objects.filter(email__iexact=username).first()
                if u:
                    username = u.username
            user = authenticate(request, username=username, password=password)
            if user:
                if user.is_staff or user.is_superuser:
                    error = 'Staff accounts use the management panel.'
                else:
                    # Akaunti ya JamiiBot au Web Builder inaingia pia — profile inatengenezwa
                    from apps.accounts_link import ensure_client_profile
                    ensure_client_profile(user)
                    login(request, user)
                    from django.utils.http import url_has_allowed_host_and_scheme
                    nxt = request.POST.get('next') or ''
                    if not (nxt.startswith('/') and url_has_allowed_host_and_scheme(
                            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())):
                        nxt = '/portal/'
                    return redirect(nxt)
            elif getattr(request, 'login_locked', False):
                from apps.security import lockout_message
                error = lockout_message()
            else:
                error = 'Invalid username or password.'

    return render(request, 'portal/login.html', {
        'error': error, 'next': request.GET.get('next', ''),
    })


@same_site_logout
def portal_logout(request):
    logout(request)
    return redirect('portal_login')


# ── DASHBOARD ──────────────────────────────────────────────────────

@client_required
def portal_dashboard(request):
    import json as _json
    client      = request.client_profile
    websites    = ManagedWebsite.objects.filter(client=client).select_related('client')
    domains     = DomainRecord.objects.filter(website__client=client)
    email_plans = EmailHostingPlan.objects.filter(client=client)
    today       = date.today()

    # Hakuna jumla ya pesa — mteja anaona AWAMU na mwenendo badala yake
    from . import payment_history as ph_service
    history = ph_service.build_history(client, websites)
    notifications = ClientNotification.objects.filter(
        client=client).order_by('-sent_at')[:5]

    # Alerts - no duplicate for suspended+overdue
    alerts = []
    for w in websites:
        if w.status == 'suspended':
            alerts.append({'type': 'danger', 'msg': f'<strong>{w.name}</strong> is suspended. Contact JamiiTek to restore.'})
        elif w.is_overdue:
            alerts.append({'type': 'danger', 'msg': f'<strong>{w.name}</strong> — hosting expired! Please make a payment immediately.'})
        elif w.days_until_expiry <= 3:
            alerts.append({'type': 'danger', 'msg': f'<strong>{w.name}</strong> — hosting expires in <strong>{w.days_until_expiry}</strong> day(s)! Renew now.'})
        elif w.days_until_expiry <= 7:
            alerts.append({'type': 'warning', 'msg': f'<strong>{w.name}</strong> — hosting expires in {w.days_until_expiry} day(s).'})

    for d in domains:
        raw_d = (d.expiry_date - today).days
        if raw_d <= 0:
            alerts.append({'type': 'danger', 'msg': f'Domain <strong>{d.domain_name}</strong> has expired!'})
        elif raw_d <= 14:
            alerts.append({'type': 'warning', 'msg': f'Domain <strong>{d.domain_name}</strong> expires in {d.days_until_expiry} day(s).'})

    for ep in email_plans:
        if ep.status == 'suspended':
            alerts.append({'type': 'danger', 'msg': f'Email hosting <strong>{ep.email_domain}</strong> is suspended.'})
        elif ep.is_overdue:
            alerts.append({'type': 'danger', 'msg': f'Email hosting <strong>{ep.email_domain}</strong> has expired!'})
        elif ep.days_until_expiry <= 7:
            alerts.append({'type': 'warning', 'msg': f'Email hosting <strong>{ep.email_domain}</strong> expires in {ep.days_until_expiry} day(s).'})

    # Payment chart - last 6 months
    try:
        # Chart inaonyesha SIKU ZA KUCHELEWA kwa kila awamu — si pesa
        chart_labels = history['chart']['labels']
        chart_values = history['chart']['values']
        chart_colors = history['chart']['colors']
        chart_names  = history['chart']['names']
    except Exception:
        chart_labels, chart_values, chart_colors, chart_names = [], [], [], []

    # Hosting expiry timeline
    expiry_data = []
    for w in websites:
        raw = (w.hosting_end_date - today).days
        st = 'expired' if raw <= 0 else ('critical' if raw <= 3 else ('warning' if raw <= 7 else 'ok'))
        expiry_data.append({'name': w.name[:18], 'days': max(raw, 0), 'raw': raw, 'status': st})

    health = {
        'active':    websites.filter(status='active').count(),
        'suspended': websites.filter(status='suspended').count(),
        'expiring':  sum(1 for w in websites if 0 < (w.hosting_end_date - today).days <= 7),
        'domains_ok': domains.filter(status='active').count(),
    }

    # Check if client has a JamiiBot account (same Django user)
    bot_client = None
    bot_config = None
    try:
        from apps.chatbot.models import ChatbotClient as BotClient, BotConfig
        bot_client = BotClient.objects.filter(user=request.user).first()
        if bot_client:
            bot_config = BotConfig.objects.filter(client=bot_client).first()
    except Exception:
        pass

    return render(request, 'portal/dashboard.html', {
        'title':         'My Dashboard',
        'client':        client,
        'websites':      websites,
        'domains':       domains,
        'email_plans':   email_plans,
        'history':       history,
        'pay_stats':     history['stats'],
        'notifications': notifications,
        'alerts':        alerts,
        'today':         today,
        'chart_labels':  _json.dumps(chart_labels),
        'chart_values':  _json.dumps(chart_values),
        'chart_colors':  _json.dumps(chart_colors),
        'chart_names':   _json.dumps(chart_names),
        'expiry_data':   _json.dumps(expiry_data),
        'health':        health,
        'bot_client':    bot_client,
        'bot_config':    bot_config,
    })


# ── MY WEBSITES ────────────────────────────────────────────────────

@client_required
def portal_website_list(request):
    client = request.client_profile
    websites = ManagedWebsite.objects.filter(client=client).select_related('static_repo').order_by('name')
    return render(request, 'portal/website_list.html', {
        'title': 'My Websites',
        'client': client,
        'websites': websites,
    })


@client_required
def portal_website_detail(request, pk):
    client = request.client_profile
    website = get_object_or_404(ManagedWebsite, pk=pk, client=client)
    payments = HostingPayment.objects.filter(website=website).order_by('-payment_date')
    notifications = ClientNotification.objects.filter(website=website).order_by('-sent_at')[:20]
    features = WebsiteFeature.objects.filter(website=website)

    months_paid = payments.aggregate(total=Sum('months_covered'))['total'] or 0
    from . import payment_history as ph_service
    phases = list(reversed(ph_service.website_phases(website)))
    coverage = ph_service.coverage_bar(website)

    return render(request, 'portal/website_detail.html', {
        'title': website.name,
        'client': client,
        'website': website,
        'payments': payments,
        'notifications': notifications,
        'features': features,
        'phases': phases,
        'coverage': coverage,
        'months_paid': months_paid,
    })


# ── BILLING & PAYMENTS ─────────────────────────────────────────────

 
# ══════════════════════════════════════════════════════════════
@client_required
def portal_billing(request):
    client = request.client_profile
    websites = ManagedWebsite.objects.filter(client=client)
    payments = HostingPayment.objects.filter(
        website__client=client).order_by('-payment_date').select_related('website')
 
    from . import payment_history as ph_service
    history = ph_service.build_history(client, websites)
 
    # Account-level balance, but every amount still tied to its own website.
    account = build_account(client, websites)
 
    billing_plans = [
        {'website': w, 'options': w.billing_options}
        for w in websites
    ]
 
    payment_info = {
        'bank': 'NMB Bank',
        'account_name': 'JamiiTek Technologies',
        'account_number': getattr(settings, 'NMB_ACCOUNT', '21410034200'),
        'branch': 'Dar es Salaam',
        'reference_format': 'WEBSITE NAME + PHONE',
    }
 
    return render(request, 'portal/billing.html', {
        'title': 'Billing & Payments',
        'client': client,
        'websites': websites,
        'payments': payments,
        'history': history,
        'pay_stats': history['stats'],
        'total_due': account['balance'],     # unchanged name, same meaning
        'account': account,
        'payment_info': payment_info,
        'billing_plans': billing_plans,
    })
 
 
# ══════════════════════════════════════════════════════════════
@client_required
@require_POST
def portal_submit_payment(request):
    """
    Accepts either shape:
 
      single site (unchanged)  website=<pk>  months_covered=<n>  amount=<n>
      several sites (new)      pay_website=<pk>&pay_website=<pk>  months_<pk>=<n>
 
    Either way one ClientNotification is raised per website, so you verify and
    record each site separately and each hosting_end_date moves on its own.
    """
    from .models import ClientNotification
 
    client = request.client_profile
    transaction_ref = request.POST.get('transaction_ref', '').strip()
    payment_method = request.POST.get('payment_method', 'NMB Bank Transfer')
    notes = request.POST.get('notes', '').strip()
 
    selected = request.POST.getlist('pay_website')
    is_multi = bool(selected)
 
    if not is_multi:
        single = request.POST.get('website')
        if single:
            selected = [single]
 
    if not selected or not transaction_ref:
        messages.error(request, 'Please fill in all required fields.')
        return redirect('portal_billing')
 
    websites = list(ManagedWebsite.objects.filter(pk__in=selected, client=client))
    if not websites:
        messages.error(request, 'Website not found.')
        return redirect('portal_billing')
 
    # Work out what each site is being paid for. Prices come from the model,
    # never from the form — the browser only says which site and how long.
    entries = []
    for website in websites:
        if is_multi:
            raw_months = request.POST.get(f'months_{website.pk}', '1')
        else:
            raw_months = request.POST.get('months_covered', '1')
        try:
            months = int(raw_months)
        except (TypeError, ValueError):
            months = 1
        if months not in (1, 3, 6, 12):
            months = 1
 
        price = website.price_for(months)
        entries.append({'website': website, 'months': months, 'expected': price['total']})
 
    expected_total = sum(e['expected'] for e in entries)
 
    # What the client says they sent. Used for reconciliation only.
    try:
        declared = float((request.POST.get('amount') or '0').replace(',', '').strip())
    except ValueError:
        declared = 0
    if not declared:
        declared = float(expected_total)
 
    site_list = ', '.join(f"{e['website'].name} ({e['months']}mo)" for e in entries)
 
    for entry in entries:
        website = entry['website']
        body = (
            f'Client {client.name} submitted payment proof.\n\n'
            f'This site:   {website.name}\n'
            f'Months:      {entry["months"]}\n'
            f'Expected:    TZS {entry["expected"]:,.0f}\n'
            f'Method:      {payment_method}\n'
            f'Ref:         {transaction_ref}\n'
        )
        if len(entries) > 1:
            body += (
                f'\nPart of one payment covering {len(entries)} websites.\n'
                f'Sites:            {site_list}\n'
                f'Expected total:   TZS {expected_total:,.0f}\n'
                f'Client declared:  TZS {declared:,.0f}\n'
            )
            if abs(declared - float(expected_total)) > 1:
                body += 'MISMATCH — the declared amount differs from the expected total.\n'
        if notes:
            body += f'\nNotes: {notes}\n'
        body += '\nPlease verify and record the payment in the management panel.'
 
        ClientNotification.objects.create(
            website=website, client=client,
            notification_type='payment_received',
            subject=f'Payment Submission — {website.name}',
            message=body,
            email_sent=False,
        )
 
    try:
        send_mail(
            subject=f'[JamiiTek] Payment proof — {client.name} ({len(entries)} site{"" if len(entries) == 1 else "s"})',
            message=(
                f'Client: {client.name}\n'
                f'Sites:  {site_list}\n'
                f'Ref:    {transaction_ref}\n'
                f'Method: {payment_method}\n'
                f'Expected total: TZS {expected_total:,.0f}\n'
                f'Declared:       TZS {declared:,.0f}\n\n'
                f'{notes}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[getattr(settings, 'ADMIN_EMAIL', 'info@jamiitek.com')],
            fail_silently=True,
        )
    except Exception:
        pass
 
    if len(entries) == 1:
        messages.success(
            request,
            f'Payment proof for {entries[0]["website"].name} received. '
            'We verify within 24 hours.')
    else:
        messages.success(
            request,
            f'Payment proof received for {len(entries)} websites. '
            'Each one is verified separately, within 24 hours.')
 
    return redirect('portal_billing')

# ── NOTIFICATIONS ──────────────────────────────────────────────────

@client_required
def portal_notifications(request):
    client = request.client_profile
    notifications = ClientNotification.objects.filter(
        client=client).order_by('-sent_at')
    return render(request, 'portal/notifications.html', {
        'title': 'Messages & Notifications',
        'client': client,
        'notifications': notifications,
    })


# ── PROFILE ────────────────────────────────────────────────────────

@client_required
def portal_profile(request):
    client = request.client_profile
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_profile':
            client.name = request.POST.get('name', client.name).strip()
            client.phone = request.POST.get('phone', client.phone).strip()
            client.company = request.POST.get('company', client.company).strip()
            client.save()
            # Update email on user too
            new_email = request.POST.get('email', '').strip()
            if new_email and new_email != client.user.email:
                if User.objects.filter(email=new_email).exclude(pk=client.user.pk).exists():
                    messages.error(request, 'That email is already in use.')
                else:
                    client.user.email = new_email
                    client.email = new_email
                    client.user.save()
                    client.save()
            messages.success(request, 'Profile updated successfully.')

        elif action == 'change_password':
            from apps.security import password_problems
            current = request.POST.get('current_password', '')
            new_pw = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')
            problems = password_problems(new_pw, client.user.username, client.user.email, client.name)
            if not client.user.check_password(current):
                messages.error(request, 'Current password is incorrect.')
            elif new_pw != confirm:
                messages.error(request, 'New passwords do not match.')
            elif problems:
                for p in problems:
                    messages.error(request, p)
            else:
                client.user.set_password(new_pw)
                client.user.save()
                messages.success(request, 'Password changed. Please log in again.')
                return redirect('portal_login')

        return redirect('portal_profile')

    return render(request, 'portal/profile.html', {
        'title': 'My Profile',
        'client': client,
    })


# ── SUPPORT REQUEST ────────────────────────────────────────────────

@client_required
def portal_support(request):
    client = request.client_profile
    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        message_body = request.POST.get('message', '').strip()
        website_pk = request.POST.get('website', '')
        priority = request.POST.get('priority', 'normal')
        if not subject or not message_body:
            messages.error(request, 'Subject and message are required.')
        else:
            website = None
            if website_pk:
                try:
                    website = ManagedWebsite.objects.get(pk=website_pk, client=client)
                except ManagedWebsite.DoesNotExist:
                    pass

            ClientNotification.objects.create(
                website=website, client=client,
                notification_type='support',
                subject=f'[{priority.upper()}] Support: {subject}',
                message=f'From: {client.name} ({client.email})\nPriority: {priority}\n\n{message_body}',
                email_sent=False,
            )
            try:
                send_mail(
                    subject=f'[Support/{priority.upper()}] {subject} — {client.name}',
                    message=f'Client: {client.name}\nEmail: {client.email}\nPhone: {client.phone}\nWebsite: {website.name if website else "N/A"}\nPriority: {priority}\n\n{message_body}',
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
                    recipient_list=[getattr(settings, 'ADMIN_EMAIL', 'info@jamiitek.com')],
                    fail_silently=True,
                )
            except Exception:
                pass
            messages.success(request, 'Support request submitted! We will respond within 24 hours.')
            return redirect('portal_support')

    faqs = [
        {'q': 'How do I renew my hosting?', 'a': 'Transfer payment to NMB Bank Account 21410034200 (JamiiTek Technologies), then submit your proof in the Billing section. We verify within 24 hours.'},
        {'q': 'My website is suspended — why?', 'a': 'This usually means your hosting payment has expired. Go to Billing, renew your hosting, and submit payment proof.'},
        {'q': 'How long does payment verification take?', 'a': 'We verify payments within 24 hours on business days (Monday to Saturday). You will receive a confirmation message once verified.'},
        {'q': 'How do I update content on my website?', 'a': 'Contact JamiiTek support via this form or WhatsApp. Describe the changes you need and we will handle them for you.'},
        {'q': 'What is the NMB reference I should use?', 'a': 'Use your full name as the payment reference when transferring. This helps us identify your payment quickly.'},
    ]
    return render(request, 'portal/support.html', {
        'title': 'Support',
        'client': client,
        'websites': ManagedWebsite.objects.filter(client=client),
        'faqs': faqs,
    })


# ── PORTAL: MY DOMAINS ──────────────────────────────────────────────

@client_required
def portal_domains(request):
    client  = request.client_profile
    domains = DomainRecord.objects.filter(website__client=client).select_related('website')
    return render(request, 'portal/domains.html', {
        'title': 'My Domains',
        'client': client,
        'domains': domains,
    })


# ── PORTAL: EMAIL HOSTING ────────────────────────────────────────────

@client_required
def portal_email_hosting(request):
    client      = request.client_profile
    email_plans = EmailHostingPlan.objects.filter(client=client).select_related('website')
    payments    = EmailHostingPayment.objects.filter(
        plan__client=client).select_related('plan').order_by('-payment_date')
    months_paid = sum(getattr(p, 'months_covered', 0) or 0 for p in payments)
    payment_info = {
        'bank':           'NMB Bank',
        'account_name':   'JamiiTek Technologies',
        'account_number': getattr(settings, 'NMB_ACCOUNT', '21410034200'),
    }
    return render(request, 'portal/email_hosting.html', {
        'title': 'Email Hosting',
        'client': client,
        'email_plans': email_plans,
        'payments': payments,
        'months_paid': months_paid,
        'payment_info': payment_info,
    })


# ══════════════════════════════════════════════════════════════
# HOSTING CONTROL PANEL
# ══════════════════════════════════════════════════════════════

@client_required
def portal_hosting_config(request, pk):
    client  = request.client_profile
    website = get_object_or_404(ManagedWebsite, pk=pk, client=client)
    from .live_config import live_config
    cfg = live_config(website)
    return render(request, 'portal/hosting_config.html', {
        'title':   f'Hosting Panel — {website.name}',
        'client':  client,
        'website': website,
        'cfg':     cfg,
    })


# ══════════════════════════════════════════════════════════════
# DNS MANAGER
# ══════════════════════════════════════════════════════════════

@client_required
def portal_dns_manager(request, pk):
    client = request.client_profile
    domain = get_object_or_404(DomainRecord, pk=pk, website__client=client)
    records = domain.dns_records.all().order_by('record_type', 'name')
    return render(request, 'portal/dns_manager.html', {
        'title':   f'DNS Manager — {domain.domain_name}',
        'client':  client,
        'domain':  domain,
        'records': records,
    })

# ── ANKARA YA KUONGEZA HOSTING (mteja anaomba mwenyewe) ────────────

@client_required
@require_POST
def portal_request_invoice(request):
    """
    Mteja anachagua muda (1/3/6/12 miezi) na kuomba ankara.
    Inaunda Invoice yenye bei sahihi + punguzo + njia za kulipa,
    kisha inampeleka kwenye ankara moja kwa moja.
    """
    from .models import Invoice
    client = request.client_profile

    website_pk = request.POST.get('website')
    try:
        months = int(request.POST.get('months', 1))
    except (TypeError, ValueError):
        months = 1
    if months not in (1, 3, 6, 12):
        months = 1

    try:
        website = ManagedWebsite.objects.get(pk=website_pk, client=client)
    except ManagedWebsite.DoesNotExist:
        messages.error(request, 'Website not found.')
        return redirect('portal_billing')

    pricing = website.price_for(months)
    if not pricing['total']:
        messages.error(request, 'No hosting price is set for this website. Please contact us.')
        return redirect('portal_billing')

    label = {1: '1 month', 3: '3 months', 6: '6 months', 12: '12 months'}[months]

    # Muda mpya utakaoanzia (kutoka mwisho wa sasa, au leo kama umeshapita)
    start = website.hosting_end_date if (website.hosting_end_date and
                                         website.hosting_end_date >= date.today()) else date.today()
    try:
        from dateutil.relativedelta import relativedelta
        new_end = start + relativedelta(months=months)
    except ImportError:
        new_end = start + timedelta(days=30 * months)

    desc = f'Hosting renewal — {website.name} ({label}: {start:%d %b %Y} → {new_end:%d %b %Y})'

    invoice = Invoice.objects.create(
        client=client,
        client_name=client.name,
        client_email=client.email or '',
        client_company=getattr(client, 'company', '') or '',
        client_phone=getattr(client, 'phone', '') or '',
        title=f'Hosting Renewal — {website.name}',
        project_name=website.name,
        invoice_type='recurring',
        status='sent',
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        currency='TZS',
        line_items=[{
            'desc': desc,
            'qty': 1,
            'unit_price': round(pricing['total']),
            'amount': round(pricing['total']),
        }],
        payment_methods=[
            {'method': 'NMB Bank', 'details': f"{getattr(settings, 'NMB_ACCOUNT', '21410034200')} — JamiiTek Technologies"},
            {'method': 'M-Pesa', 'details': getattr(settings, 'MPESA_NUMBER', '') or _contact()['mpesa'] + ' — JamiiTek'},
        ],
        payment_terms='Please pay by the due date to avoid service interruption.',
        notes_en=(f'This invoice covers {label} of hosting for {website.name}. '
                  f'You save TZS {pricing["saving"]:,.0f} by paying for {label} at once.'
                  if pricing['saving'] else
                  f'This invoice covers {label} of hosting for {website.name}.'),
        notes_sw=(f'Ankara hii ni kwa ajili ya hosting ya {website.name} kwa {label}. '
                  f'Unaokoa TZS {pricing["saving"]:,.0f} kwa kulipa kwa mkupuo.'
                  if pricing['saving'] else
                  f'Ankara hii ni kwa ajili ya hosting ya {website.name} kwa {label}.'),
        sent_at=timezone.now(),
    )

    messages.success(request,
                     f'Invoice {invoice.invoice_number} created for {label}. '
                     f'You can download it or pay using the details shown.')
    return redirect(invoice.public_url)


# ══════════════════════════════════════════════════════════════════
#  RIPOTI YA MWEZI (mteja anajipakulia mwenyewe)
# ══════════════════════════════════════════════════════════════════

@client_required
def portal_monthly_report(request, pk):
    from django.http import HttpResponse

    from . import reports
    website = get_object_or_404(
        ManagedWebsite, pk=pk, client=request.client_profile)
    pdf = reports.build_pdf(website)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{reports.filename(website)}"'
    return resp
