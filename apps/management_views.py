# apps/management_views.py — JamiiTek Management Panel

import json, secrets, logging
from datetime import date, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.http import require_GET, require_POST
from apps.security import same_site_logout
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, Count, Q

logger = logging.getLogger(__name__)


def staff_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/manage/login/?next={request.path}')
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, 'Access denied. Staff accounts only.')
            return redirect('/manage/login/')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

staff_member_required = staff_required

from .models import (
    ManagedWebsite, HostingPayment, WebsiteFeature,
    ScheduledAction, ClientNotification, Client,
    DomainRecord, DomainRenewalPayment,
    EmailHostingPlan, EmailHostingPayment,
)


# ── DASHBOARD ─────────────────────────────────────────────────────

@staff_required
def management_dashboard(request):
    websites = ManagedWebsite.objects.select_related('client').all()
    today = date.today()

    # Hesabu zote kwa swali MOJA kwa kila jedwali (conditional aggregation).
    # Awali zilikuwa maswali 7 tofauti — kila moja safari ya kwenda
    # Supabase. Matokeo ni yale yale.
    from django.db.models import Count, Q
    w = ManagedWebsite.objects.aggregate(
        total=Count('pk'),
        active=Count('pk', filter=Q(status='active')),
        suspended=Count('pk', filter=Q(status='suspended')),
        maintenance=Count('pk', filter=Q(status='maintenance')),
        terminated=Count('pk', filter=Q(status='terminated')),
    )
    rev = HostingPayment.objects.aggregate(
        month=Sum('amount', filter=Q(payment_date__month=today.month,
                                     payment_date__year=today.year)),
        total=Sum('amount'),
    )
    stats = dict(w, revenue_month=rev['month'] or 0, revenue_total=rev['total'] or 0)

    overdue = [w for w in websites if w.is_overdue and w.status == 'active']
    expiring_soon = [w for w in websites
                     if w.days_until_expiry is not None
                     and 0 <= w.days_until_expiry <= 14 and not w.is_overdue]

    pending_actions = ScheduledAction.objects.filter(
        status='pending').select_related('website').order_by('scheduled_at')[:10]
    recent_notifications = ClientNotification.objects.select_related(
        'client', 'website').order_by('-sent_at')[:8]
    recent_payments = HostingPayment.objects.select_related(
        'website__client').order_by('-payment_date')[:6]

    # ── Bot stats ──────────────────────────────────────────────────
    try:
        from apps.chatbot.models import BotConfig, BotSubscription, SubscriptionPayment, Message, Conversation
        from django.db.models import Sum as DSum
        from django.db.models import Count as DCount, Q as DQ
        b = BotConfig.objects.aggregate(
            total=DCount('pk'),
            active=DCount('pk', filter=DQ(status='active')),
            pending=DCount('pk', filter=DQ(status='pending')),
            suspended=DCount('pk', filter=DQ(status='suspended')),
        )
        pay = SubscriptionPayment.objects.aggregate(
            revenue=DSum('amount', filter=DQ(status='verified')),
            pending_payments=DCount('pk', filter=DQ(status='pending')),
        )
        # Jedwali la jumbe ni kubwa: jumla zinahesabiwa upya kila dakika tu
        from django.core.cache import cache
        msg = cache.get('manage:msg_totals')
        if msg is None:
            msg = Message.objects.aggregate(
                total_msgs=DCount('pk'),
                today_msgs=DCount('pk', filter=DQ(created_at__date=today)),
            )
            cache.set('manage:msg_totals', msg, 60)
        bot_stats = dict(b, revenue=pay['revenue'] or 0,
                         pending_payments=pay['pending_payments'], **msg)
        bots_pending_setup = BotConfig.objects.filter(status='pending').select_related('client')[:5]
    except Exception:
        bot_stats = {}
        bots_pending_setup = []

    return render(request, 'management/dashboard.html', {
        'title': 'Dashboard',
        'websites': websites.order_by('-created_at')[:10],
        'stats': stats,
        'overdue': overdue,
        'expiring_soon': expiring_soon,
        'pending_actions': pending_actions,
        'recent_notifications': recent_notifications,
        'recent_payments': recent_payments,
        'bot_stats': bot_stats,
        'bots_pending_setup': bots_pending_setup,
    })


# ── WEBSITE LIST ───────────────────────────────────────────────────

@staff_required
def website_list(request):
    status_filter = request.GET.get('status', '')
    search = request.GET.get('q', '')
    # client__user na payments kwa JOIN/prefetch — awali maswali 2 kwa kila mstari
    websites = (ManagedWebsite.objects.select_related('client__user')
                .prefetch_related('payments'))
    if status_filter:
        websites = websites.filter(status=status_filter)
    if search:
        websites = websites.filter(
            Q(name__icontains=search) | Q(client__name__icontains=search) | Q(url__icontains=search))
    return render(request, 'management/website_list.html', {
        'title': 'All Websites',
        'websites': websites.order_by('name'),
        'status_filter': status_filter,
        'search': search,
        'status_choices': [('', 'All'), ('active', 'Active'), ('suspended', 'Suspended'), ('maintenance', 'Maintenance'), ('terminated', 'Terminated')],
    })


# ── WEBSITE DETAIL ─────────────────────────────────────────────────

@staff_required
def website_detail(request, pk):
    website = get_object_or_404(ManagedWebsite.objects.select_related('client'), pk=pk)
    return render(request, 'management/website_detail.html', {
        'title': website.name,
        'website': website,
        'features': WebsiteFeature.objects.filter(website=website),
        'scheduled': ScheduledAction.objects.filter(website=website, status='pending').order_by('scheduled_at'),
        'payments': HostingPayment.objects.filter(website=website).order_by('-payment_date'),
        'notifications': ClientNotification.objects.filter(website=website).order_by('-sent_at')[:30],
        'action_types': ScheduledAction.ACTION_TYPES,
        'notification_types': ClientNotification.NOTIFICATION_TYPES,
    })


# ── ADD WEBSITE ────────────────────────────────────────────────────

@staff_required
def website_add(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')
        name = request.POST.get('name', '').strip()
        url = request.POST.get('url', '').strip()
        if not all([client_id, name, url,
                    request.POST.get('hosting_start_date'),
                    request.POST.get('hosting_end_date')]):
            messages.error(request, 'Please fill in all required fields.')
        else:
            try:
                website = ManagedWebsite.objects.create(
                    client=Client.objects.get(pk=client_id),
                    name=name, url=url,
                    site_type=request.POST.get('site_type', 'static'),
                    hosting_start_date=request.POST.get('hosting_start_date'),
                    hosting_end_date=request.POST.get('hosting_end_date'),
                    monthly_cost=Decimal(request.POST.get('monthly_cost', 0)),
                    notes=request.POST.get('notes', ''),
                    auto_suspend_on_expiry=request.POST.get('auto_suspend_on_expiry') == 'on',
                    send_expiry_warnings=request.POST.get('send_expiry_warnings') == 'on',
                    status='active',
                )
                messages.success(request, f'Website "{name}" added successfully.')
                return redirect('website_detail', pk=website.pk)
            except Exception as e:
                messages.error(request, f'Error: {e}')
    return render(request, 'management/website_add.html', {
        'title': 'Add Website',
        'clients': Client.objects.all().order_by('name'),
    })


# ── EDIT WEBSITE ───────────────────────────────────────────────────

@staff_required
def website_edit(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    if request.method == 'POST':
        from datetime import datetime
        website.name = request.POST.get('name', website.name).strip()
        website.url = request.POST.get('url', website.url).strip()
        website.site_type = request.POST.get('site_type', website.site_type)
        website.monthly_cost = Decimal(request.POST.get('monthly_cost', website.monthly_cost))
        website.notes = request.POST.get('notes', '')
        website.auto_suspend_on_expiry = request.POST.get('auto_suspend_on_expiry') == 'on'
        website.send_expiry_warnings = request.POST.get('send_expiry_warnings') == 'on'
        end = request.POST.get('hosting_end_date')
        if end:
            website.hosting_end_date = datetime.strptime(end, '%Y-%m-%d').date()
        website.save()
        messages.success(request, 'Website updated.')
        return redirect('website_detail', pk=pk)
    return render(request, 'management/website_edit.html', {
        'title': f'Edit — {website.name}', 'website': website,
        'clients': Client.objects.all().order_by('name'),
    })


# ── SUSPEND ────────────────────────────────────────────────────────

@staff_required
@require_POST
def suspend_website(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    reason = request.POST.get('reason', '').strip()
    msg = request.POST.get('suspension_message', '').strip() or \
        'This website has been suspended. Please contact us for more information.'
    if not reason:
        messages.error(request, 'Suspension reason is required.')
        return redirect('website_detail', pk=pk)
    website.status = 'suspended'
    website.suspension_reason = reason
    website.suspension_message = msg
    website.save()
    if request.POST.get('notify_client') == 'on':
        _send_notification(website, 'suspension',
            f'Website Suspended — {website.name}',
            f'Dear {website.client.name},\n\nYour website ({website.name}) has been suspended.\n\nReason: {reason}\n\n{msg}\n\nContact us to resolve this.\n\nJamiiTek Team',
            request.user)
    messages.success(request, f'"{website.name}" has been suspended.')
    return redirect('website_detail', pk=pk)


# ── RESTORE ────────────────────────────────────────────────────────

@staff_required
@require_POST
def restore_website(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    website.status = 'active'
    website.suspension_reason = ''
    website.suspension_message = ''
    website.save()
    if request.POST.get('notify_client') == 'on':
        _send_notification(website, 'restoration',
            f'Website Restored — {website.name}',
            f'Dear {website.client.name},\n\nYour website ({website.name}) is now live again.\n\nURL: {website.url}\n\nThank you!\n\nJamiiTek Team',
            request.user)
    messages.success(request, f'"{website.name}" restored successfully.')
    return redirect('website_detail', pk=pk)


# ── MAINTENANCE ────────────────────────────────────────────────────

@staff_required
@require_POST
def set_maintenance(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    msg = request.POST.get('maintenance_message', '').strip() or \
        'We are performing scheduled maintenance. We will be back shortly. Thank you for your patience.'
    website.status = 'maintenance'
    website.suspension_message = msg
    website.save()
    if request.POST.get('notify_client') == 'on':
        _send_notification(website, 'maintenance',
            f'Scheduled Maintenance — {website.name}',
            f'Dear {website.client.name},\n\nYour website ({website.name}) is in maintenance mode.\n\nVisitors will see: {msg}\n\nWe will notify you when done.\n\nJamiiTek Team',
            request.user)
    messages.success(request, f'"{website.name}" is in maintenance mode.')
    return redirect('website_detail', pk=pk)


# ── FEATURES ───────────────────────────────────────────────────────

@staff_required
@require_POST
def toggle_feature(request, pk, feature_pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    feature = get_object_or_404(WebsiteFeature, pk=feature_pk, website=website)
    feature.is_enabled = not feature.is_enabled
    feature.save()
    messages.success(request, f'Feature "{feature.feature_name}" {"enabled" if feature.is_enabled else "disabled"}.')
    return redirect('website_detail', pk=pk)


@staff_required
@require_POST
def add_feature(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    feature_key = request.POST.get('feature_key', '').strip().lower().replace(' ', '_')
    feature_name = request.POST.get('feature_name', '').strip()
    if not feature_key or not feature_name:
        messages.error(request, 'Feature key and name are required.')
        return redirect('website_detail', pk=pk)
    _, created = WebsiteFeature.objects.get_or_create(
        website=website, feature_key=feature_key,
        defaults={'feature_name': feature_name, 'is_enabled': True})
    messages.success(request, f'Feature "{feature_name}" {"added" if created else "already exists"}.')
    return redirect('website_detail', pk=pk)


# ── PAYMENTS ───────────────────────────────────────────────────────

@staff_required
@require_POST
def add_payment(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    try:
        from datetime import datetime
        from apps.chatbot.billing import parse_amount
        # "150,000" ilishindwa kusomwa na Decimal()
        parsed = parse_amount(request.POST.get('amount'))
        if parsed is None:
            messages.error(request, 'Kiasi hakisomeki. Andika kama 150000 au 150,000.')
            return redirect('website_detail', pk=pk)
        amount = Decimal(parsed)
        payment_date = datetime.strptime(request.POST.get('payment_date'), '%Y-%m-%d').date()
        months_covered = int(request.POST.get('months_covered', 1))
        payment_method = request.POST.get('payment_method', '')
        transaction_ref = request.POST.get('transaction_ref', '').strip()
        extend_hosting = request.POST.get('extend_hosting') == 'on'
        auto_restore = request.POST.get('auto_restore') == 'on'
        notify_client = request.POST.get('notify_client') == 'on'

        # Namba ile ile ya muamala kurekodiwa mara mbili (refresh, kubonyeza
        # mara mbili) iliongeza hosting MARA MBILI kwa malipo moja.
        if transaction_ref and HostingPayment.objects.filter(
                website=website, transaction_ref__iexact=transaction_ref).exists():
            messages.warning(request, f'Malipo yenye namba {transaction_ref} yalikwisha rekodiwa kwa '
                                      f'{website.name}. Hakuna kilichoongezwa.')
            return redirect('website_detail', pk=pk)

        HostingPayment.objects.create(
            website=website, amount=amount, payment_date=payment_date,
            months_covered=months_covered, payment_method=payment_method,
            transaction_ref=transaction_ref,
            notes=request.POST.get('notes', ''),
            recorded_by=request.user)

        if extend_hosting and months_covered > 0:
            try:
                from dateutil.relativedelta import relativedelta
                base = website.hosting_end_date if (website.hosting_end_date and website.hosting_end_date >= date.today()) else date.today()
                website.hosting_end_date = base + relativedelta(months=months_covered)
            except ImportError:
                website.hosting_end_date = (website.hosting_end_date or date.today()) + timedelta(days=30 * months_covered)
            website.save()

        if auto_restore and website.status == 'suspended':
            website.status = 'active'
            website.suspension_reason = ''
            website.suspension_message = ''
            website.save()

        if notify_client:
            new_expiry = website.hosting_end_date.strftime('%d %B %Y') if website.hosting_end_date else 'N/A'
            _send_notification(website, 'payment_received',
                f'Payment Received — {website.name}',
                f'Dear {website.client.name},\n\nPayment received!\n\nAmount: TZS {amount:,.0f}\nMethod: {payment_method}\nMonths: {months_covered}\nRef: {transaction_ref or "N/A"}\nValid until: {new_expiry}\n\nThank you!\n\nJamiiTek Team',
                request.user)

        messages.success(request, f'Payment of TZS {amount:,.0f} recorded.')
    except Exception as e:
        messages.error(request, f'Error recording payment: {e}')
    return redirect('website_detail', pk=pk)


# ── SEND NOTIFICATION ──────────────────────────────────────────────

@staff_required
def send_notification(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        message_body = request.POST.get('message', '').strip()
        notification_type = request.POST.get('notification_type', 'general')
        if not subject or not message_body:
            messages.error(request, 'Subject and message are required.')
        else:
            _send_notification(website, notification_type, subject, message_body, request.user)
            messages.success(request, f'Message sent to {website.client.name} successfully.')
        return redirect('website_detail', pk=pk)
    # GET: show dedicated page too (for backwards compat)
    return render(request, 'management/send_notification.html', {
        'title': f'Send Message — {website.name}',
        'website': website,
        'notification_types': ClientNotification.NOTIFICATION_TYPES,
    })


# ── SCHEDULE ACTION ────────────────────────────────────────────────

@staff_required
@require_POST
def schedule_action(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    try:
        from datetime import datetime
        action_type = request.POST.get('action_type')
        scheduled_at = timezone.make_aware(
            datetime.strptime(request.POST.get('scheduled_at'), '%Y-%m-%dT%H:%M'))
        action_data = {
            'reason': request.POST.get('reason', ''),
            'message': request.POST.get('message', ''),
            'notify_client': request.POST.get('notify_client') == 'on',
            'email_subject': request.POST.get('email_subject', ''),
            'email_body': request.POST.get('email_body', ''),
            'feature_key': request.POST.get('feature_key', ''),
        }
        ScheduledAction.objects.create(
            website=website, action_type=action_type,
            scheduled_at=scheduled_at, action_data=action_data,
            created_by=request.user)
        messages.success(request, f'Action scheduled for {scheduled_at.strftime("%d %b %Y %H:%M")}.')
    except Exception as e:
        messages.error(request, f'Error scheduling: {e}')
    return redirect('website_detail', pk=pk)


@staff_required
@require_POST
def cancel_scheduled_action(request, action_pk):
    action = get_object_or_404(ScheduledAction, pk=action_pk)
    wpk = action.website.pk
    action.status = 'cancelled'
    action.save()
    messages.success(request, 'Action cancelled.')
    return redirect('website_detail', pk=wpk)


# ── REGENERATE API KEY ─────────────────────────────────────────────

@staff_required
@require_POST
def regenerate_api_key(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    website.api_key = secrets.token_urlsafe(48)
    website.save()
    messages.success(request, 'API key regenerated. Update the script on the client website.')
    return redirect('website_detail', pk=pk)


# ── CLIENT LIST ────────────────────────────────────────────────────

@staff_required
def client_list(request):
    clients = list(Client.objects.select_related('user').annotate(
        website_count=Count('managed_websites')).order_by('name'))
    return render(request, 'management/client_list.html', {
        'title': 'Clients', 'clients': clients,
    })


@staff_required
def client_detail_admin(request, pk):
    client = get_object_or_404(Client, pk=pk)
    payments = (HostingPayment.objects.filter(website__client=client)
                .select_related('website').order_by('-payment_date'))
    return render(request, 'management/client_detail.html', {
        'title': client.name, 'client': client,
        'websites': list(ManagedWebsite.objects.filter(client=client)),
        'payments': payments,
        'notifications': ClientNotification.objects.filter(client=client).order_by('-sent_at')[:20],
        'total_revenue': payments.aggregate(total=Sum('amount'))['total'] or 0,
    })


# ── PUBLIC API ─────────────────────────────────────────────────────

@require_GET
def site_status_api(request, api_key):
    try:
        website = ManagedWebsite.objects.get(api_key=api_key)
        data = {
            'status': website.status,
            'is_active': website.is_active,
            'suspension_message': website.suspension_message if not website.is_active else '',
            'features': {f.feature_key: f.is_enabled for f in website.features.all()},
            'site_name': website.name,
        }
        resp = JsonResponse(data)
    except ManagedWebsite.DoesNotExist:
        resp = JsonResponse({'status': 'active', 'is_active': True, 'features': {}})

    resp['Access-Control-Allow-Origin'] = '*'
    resp['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    resp['Cache-Control'] = 'no-store, no-cache'
    return resp


@require_GET
def get_js_snippet(request, api_key):
    try:
        website = ManagedWebsite.objects.get(api_key=api_key)
    except ManagedWebsite.DoesNotExist:
        return HttpResponse("// JamiiTek: Invalid API key", content_type='application/javascript')

    api_url = request.build_absolute_uri(f'/api/site-status/{api_key}/')

    js_code = f"""/* JamiiTek Status Guard v2 — {website.name} */
(function(){{
  'use strict';
  var API='{api_url}';
  var RETRY=3,TIMEOUT=8000;
  var hideStyle=document.createElement('style');
  hideStyle.id='_jt_guard';
  hideStyle.textContent='html{{opacity:0!important;pointer-events:none!important}}';
  (document.head||document.documentElement).appendChild(hideStyle);
  function reveal(){{var s=document.getElementById('_jt_guard');if(s)s.parentNode.removeChild(s);}}
  function showBlock(status,msg){{
    reveal();
    var isMaint=status==='maintenance';
    var icon=isMaint?'🔧':'🔒';
    var title=isMaint?'Under Maintenance':'Service Suspended';
    var accent=isMaint?'#f59e0b':'#ef4444';
    document.documentElement.style.cssText='height:100%;margin:0';
    document.body.style.cssText='margin:0;padding:0;min-height:100vh;background:#0b0f1a;font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;display:flex;align-items:center;justify-content:center';
    document.body.innerHTML='<div style="text-align:center;padding:32px;max-width:520px;width:100%"><div style="display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);padding:7px 16px;border-radius:100px;font-size:12px;color:rgba(255,255,255,0.4);font-weight:600;letter-spacing:0.5px;margin-bottom:32px"><span style="width:7px;height:7px;border-radius:50%;background:'+accent+';display:inline-block"></span>'+(isMaint?'Maintenance Mode':'Suspended')+'</div><div style="font-size:72px;margin-bottom:24px;line-height:1">'+icon+'</div><h1 style="font-size:clamp(22px,4vw,32px);font-weight:800;color:#fff;margin:0 0 16px;letter-spacing:-0.5px">'+title+'</h1><p style="font-size:16px;color:rgba(255,255,255,0.5);line-height:1.7;margin:0 0 32px;max-width:400px;margin-inline:auto">'+((msg&&msg.trim())||'This website is temporarily unavailable. Please contact the administrator.')+'</p><div style="display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:10px;border:1px solid rgba(255,255,255,0.08);color:rgba(255,255,255,0.25);font-size:13px">Managed by JamiiTek</div></div>';
    document.title=title+' — '+document.title;
  }}
  function check(attempt){{
    var controller=typeof AbortController!=='undefined'?new AbortController():null;
    var timer=controller?setTimeout(function(){{controller.abort();}},TIMEOUT):null;
    var opts={{cache:'no-store'}};
    if(controller)opts.signal=controller.signal;
    fetch(API,opts)
      .then(function(r){{if(timer)clearTimeout(timer);return r.json();}})
      .then(function(data){{
        window.JAMIITEK=data;
        document.dispatchEvent(new CustomEvent('jamiitek:ready',{{detail:data}}));
        if(!data.is_active){{showBlock(data.status,data.suspension_message);}}
        else{{reveal();}}
      }})
      .catch(function(){{
        if(timer)clearTimeout(timer);
        if(attempt<RETRY){{setTimeout(function(){{check(attempt+1);}},1500*attempt);}}
        else{{console.warn('[JamiiTek] Could not reach status API. Showing page.');reveal();}}
      }});
  }}
  if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',function(){{check(1);}});}}
  else{{check(1);}}
}})();""".strip()

    resp = HttpResponse(js_code, content_type='application/javascript; charset=utf-8')
    resp['Access-Control-Allow-Origin'] = '*'
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp['Pragma'] = 'no-cache'
    return resp


# ── AUTH ───────────────────────────────────────────────────────────

def management_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('management_dashboard')
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user and (user.is_staff or user.is_superuser):
            login(request, user)
            from django.utils.http import url_has_allowed_host_and_scheme
            nxt = request.POST.get('next') or ''
            if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
                nxt = '/manage/'
            return redirect(nxt)
        if getattr(request, 'login_locked', False):
            from apps.security import lockout_message
            error = lockout_message()
        else:
            error = 'Invalid credentials or insufficient permissions.'
    return render(request, 'management/login.html', {
        'error': error, 'next': request.GET.get('next', ''),
    })


@same_site_logout
def management_logout(request):
    logout(request)
    return redirect('management_login')


# ── HELPER ─────────────────────────────────────────────────────────

def _send_notification(website, notification_type, subject, message, sent_by=None):
    """Rekodi ya taarifa kwenye portal, pamoja na barua pepe.

    Kusitishwa (`suspension`) ni tofauti: barua yake inatumwa na
    `apps/suspension_signals.py` mara tu status inapobadilika, kwa
    template kamili ya HTML — na inatumwa kwa NJIA ZOTE za kusitisha,
    si hii pekee. Hapa tunaweka rekodi ya portal tu, ili mteja
    asipokee barua mbili.

    `fail_silently=True`: barua isiyotoka haipaswi kuvunja kitendo cha
    admin wala kumpa mtumiaji ukurasa wa hitilafu. Kosa linaingia
    kwenye logs.
    """
    n = ClientNotification.objects.create(
        website=website, client=website.client,
        notification_type=notification_type,
        subject=subject, message=message,
        sent_by=sent_by, email_sent=False)

    if notification_type == 'suspension':
        return n

    if website.client.email:
        try:
            sent = send_mail(
                subject=subject, message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
                recipient_list=[website.client.email], fail_silently=True)
            if sent:
                n.email_sent = True
                n.save(update_fields=['email_sent'])
        except Exception:
            logger.exception('[JamiiTek] barua ya taarifa imeshindwa: %s', website.pk)
    return n


# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@staff_required
def domain_list(request):
    from datetime import timedelta
    today = date.today()
    domains = DomainRecord.objects.select_related('website', 'website__client').all()
    expiring = [d for d in domains if not d.is_expired and d.days_until_expiry <= 30]
    expired  = [d for d in domains if d.is_expired]
    return render(request, 'management/domain_list.html', {
        'title': 'Domain Management',
        'domains': domains,
        'expiring': expiring,
        'expired': expired,
    })


@staff_required
def domain_add(request):
    websites = ManagedWebsite.objects.select_related('client').all()
    if request.method == 'POST':
        website = get_object_or_404(ManagedWebsite, pk=request.POST['website'])
        d = DomainRecord.objects.create(
            website=website,
            domain_name=request.POST.get('domain_name', '').strip(),
            registrar=request.POST.get('registrar', 'other'),
            registrar_other=request.POST.get('registrar_other', '').strip(),
            registration_date=request.POST['registration_date'],
            expiry_date=request.POST['expiry_date'],
            renewal_cost=Decimal(request.POST.get('renewal_cost') or 0),
            auto_renew=bool(request.POST.get('auto_renew')),
            send_renewal_warnings=bool(request.POST.get('send_renewal_warnings')),
            warning_days_before=int(request.POST.get('warning_days_before') or 30),
            dns_nameservers=request.POST.get('dns_nameservers', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
        messages.success(request, f'Domain {d.domain_name} added successfully.')
        return redirect('domain_detail', pk=d.pk)
    return render(request, 'management/domain_add.html', {
        'title': 'Add Domain',
        'websites': websites,
        'registrar_choices': DomainRecord.REGISTRAR_CHOICES,
    })


@staff_required
def domain_detail(request, pk):
    domain   = get_object_or_404(DomainRecord, pk=pk)
    payments = domain.renewal_payments.all()
    return render(request, 'management/domain_detail.html', {
        'title': domain.domain_name,
        'domain': domain,
        'payments': payments,
        'status_choices': DomainRecord.STATUS_CHOICES,
    })


@staff_required
@require_POST
def domain_renew(request, pk):
    domain = get_object_or_404(DomainRecord, pk=pk)
    renewed_until = request.POST['renewed_until']
    DomainRenewalPayment.objects.create(
        domain=domain,
        amount=Decimal(request.POST.get('amount') or domain.renewal_cost),
        paid_date=request.POST.get('paid_date') or date.today(),
        renewed_until=renewed_until,
        payment_method=request.POST.get('payment_method', ''),
        transaction_ref=request.POST.get('transaction_ref', ''),
        notes=request.POST.get('notes', ''),
        recorded_by=request.user,
    )
    domain.expiry_date = renewed_until
    domain.status = 'active'
    domain.save()
    if request.POST.get('notify_client'):
        _send_domain_notification(domain, renewed_until)
    messages.success(request, f'Domain {domain.domain_name} renewed until {renewed_until}.')
    return redirect('domain_detail', pk=domain.pk)


@staff_required
@require_POST
def domain_update_status(request, pk):
    domain = get_object_or_404(DomainRecord, pk=pk)
    domain.status = request.POST.get('status', domain.status)
    domain.notes  = request.POST.get('notes', domain.notes)
    domain.save()
    messages.success(request, 'Domain status updated.')
    return redirect('domain_detail', pk=domain.pk)


def _send_domain_notification(domain, renewed_until):
    client = domain.website.client
    if not client.email:
        return
    try:
        send_mail(
            subject=f'Domain Renewal Confirmed — {domain.domain_name}',
            message=(
                f'Dear {client.name},\n\n'
                f'Your domain {domain.domain_name} has been renewed.\n\n'
                f'Valid Until: {renewed_until}\n'
                f'Registrar: {domain.get_registrar_display()}\n\n'
                f'JamiiTek Team\ninfo@jamiitek.com'
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
            recipient_list=[client.email],
            fail_silently=True,
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL HOSTING MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@staff_required
def email_hosting_list(request):
    today = date.today()
    plans    = EmailHostingPlan.objects.select_related('client', 'website').all()
    expiring = [p for p in plans if not p.is_overdue and p.days_until_expiry <= 14]
    expired  = [p for p in plans if p.is_overdue]
    return render(request, 'management/email_hosting_list.html', {
        'title': 'Email Hosting',
        'plans': plans,
        'expiring': expiring,
        'expired': expired,
        'stats': {
            'total':     plans.count(),
            'active':    plans.filter(status='active').count(),
            'suspended': plans.filter(status='suspended').count(),
            'exp_count': len(expired),
        },
    })


@staff_required
def email_hosting_add(request):
    clients  = Client.objects.all()
    websites = ManagedWebsite.objects.select_related('client').all()
    if request.method == 'POST':
        client  = get_object_or_404(Client, pk=request.POST['client'])
        website = None
        if request.POST.get('website'):
            website = ManagedWebsite.objects.filter(pk=request.POST['website']).first()
        plan = EmailHostingPlan.objects.create(
            client=client,
            website=website,
            plan_name=request.POST.get('plan_name', '').strip(),
            email_domain=request.POST.get('email_domain', '').strip(),
            accounts_count=int(request.POST.get('accounts_count') or 1),
            storage_gb=Decimal(request.POST.get('storage_gb') or 5),
            monthly_cost=Decimal(request.POST.get('monthly_cost') or 0),
            start_date=request.POST['start_date'],
            end_date=request.POST['end_date'],
            auto_suspend_on_expiry=bool(request.POST.get('auto_suspend_on_expiry')),
            send_expiry_warnings=bool(request.POST.get('send_expiry_warnings')),
            warning_days_before=int(request.POST.get('warning_days_before') or 7),
            notes=request.POST.get('notes', ''),
        )
        messages.success(request, f'Email plan "{plan.plan_name}" created.')
        return redirect('email_hosting_detail', pk=plan.pk)
    return render(request, 'management/email_hosting_add.html', {
        'title': 'Add Email Hosting Plan',
        'clients': clients,
        'websites': websites,
    })


@staff_required
def email_hosting_detail(request, pk):
    plan     = get_object_or_404(EmailHostingPlan, pk=pk)
    payments = plan.email_payments.all()
    return render(request, 'management/email_hosting_detail.html', {
        'title': plan.plan_name,
        'plan': plan,
        'payments': payments,
        'notification_types': ClientNotification.NOTIFICATION_TYPES,
    })


@staff_required
@require_POST
def email_hosting_payment(request, pk):
    plan   = get_object_or_404(EmailHostingPlan, pk=pk)
    amount = Decimal(request.POST.get('amount') or plan.monthly_cost)
    months = int(request.POST.get('months_covered') or 1)
    EmailHostingPayment.objects.create(
        plan=plan,
        amount=amount,
        payment_date=request.POST.get('payment_date') or date.today(),
        months_covered=months,
        payment_method=request.POST.get('payment_method', ''),
        transaction_ref=request.POST.get('transaction_ref', ''),
        notes=request.POST.get('notes', ''),
        recorded_by=request.user,
    )
    if request.POST.get('extend_plan'):
        from dateutil.relativedelta import relativedelta
        plan.end_date = plan.end_date + relativedelta(months=months)
        if plan.status in ('suspended', 'expired'):
            plan.status = 'active'
        plan.save()
    if request.POST.get('notify_client') and plan.client.email:
        try:
            send_mail(
                subject=f'Email Hosting Payment Received — {plan.email_domain}',
                message=(
                    f'Dear {plan.client.name},\n\n'
                    f'We have received your email hosting payment.\n\n'
                    f'Plan: {plan.plan_name}\n'
                    f'Domain: {plan.email_domain}\n'
                    f'Amount: TZS {amount}\n'
                    f'Valid Until: {plan.end_date}\n\n'
                    f'JamiiTek Team'
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
                recipient_list=[plan.client.email],
                fail_silently=True,
            )
        except Exception:
            pass
    messages.success(request, f'Payment recorded. Plan valid until {plan.end_date}.')
    return redirect('email_hosting_detail', pk=plan.pk)


@staff_required
@require_POST
def email_hosting_suspend(request, pk):
    plan = get_object_or_404(EmailHostingPlan, pk=pk)
    plan.status = 'suspended'
    plan.suspension_message = request.POST.get('suspension_message', plan.suspension_message)
    plan.save()
    if request.POST.get('notify_client') and plan.client.email:
        send_mail(
            subject=f'Email Hosting Suspended — {plan.email_domain}',
            message=f'Dear {plan.client.name},\n\nYour email hosting for {plan.email_domain} has been suspended.\n\n{plan.suspension_message}\n\nJamiiTek Team',
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
            recipient_list=[plan.client.email], fail_silently=True)
    messages.success(request, 'Email plan suspended.')
    return redirect('email_hosting_detail', pk=plan.pk)


@staff_required
@require_POST
def email_hosting_restore(request, pk):
    plan = get_object_or_404(EmailHostingPlan, pk=pk)
    plan.status = 'active'
    plan.save()
    if request.POST.get('notify_client') and plan.client.email:
        send_mail(
            subject=f'Email Hosting Restored — {plan.email_domain}',
            message=f'Dear {plan.client.name},\n\nYour email hosting for {plan.email_domain} has been restored.\n\nJamiiTek Team',
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jamiitek.com'),
            recipient_list=[plan.client.email], fail_silently=True)
    messages.success(request, 'Email plan restored.')
    return redirect('email_hosting_detail', pk=plan.pk)

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-SUSPEND (tovuti zilizofikia mwisho wa muda)
# ══════════════════════════════════════════════════════════════════════════════

@staff_required
def run_auto_suspend_view(request):
    """
    Endesha auto-suspend kwa mkono.
    GET  → onyesha zitakazosimamishwa (dry run)
    POST → simamisha kweli
    """
    from . import hosting_service

    if request.method == 'POST':
        report = hosting_service.run_auto_suspend(
            dry_run=False,
            notify=request.POST.get('notify') == 'on',
            actor=request.user,
        )
        n = len(report['suspended'])
        m = len(report['maintenance'])
        if report.get('systemic_failure'):
            messages.error(request,
                           'A system problem occurred. Affected websites were put '
                           'in maintenance, not suspended. Please check the logs.')
        elif n or m:
            parts = []
            if n:
                parts.append(f'{n} website(s) suspended')
            if m:
                parts.append(f'{m} set to maintenance (system issue)')
            messages.success(request, ' · '.join(parts) + '.')
        else:
            messages.info(request, 'No expired websites — nothing to suspend.')
        return redirect('website_list')

    # GET — hakiki tu
    report = hosting_service.run_auto_suspend(dry_run=True)
    return render(request, 'management/auto_suspend.html', {
        'report': report,
        'candidates': report['suspended'],
    })


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT YA KAZI ZA KILA SIKU (kwa cron ya nje — bila kuhitaji login)
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
def daily_tasks_endpoint(request):
    """
    Endesha kazi za kila siku kwa kupitia URL yenye token.
    Imeundwa kwa ajili ya UptimeRobot / cron-job.org.

        https://jamiitek.com/tasks/daily/?token=XXXXX

    Tabia:
      • Inafanya kazi MARA MOJA tu kwa siku, hata ikipigwa kila dakika 5.
        (Inatumia alama ile ile ya middleware — hazirudii kazi.)
      • Inarudisha jibu MARA MOJA (chini ya sekunde 1). Kazi halisi
        inafanyika kwenye thread ya nyuma — UptimeRobot haitakata muunganisho.
      • Daima 200 kama token ni sahihi — UptimeRobot isione "down" bure.

    Vigezo:
      ?dry=1     → onyesha zitakazoguswa, bila kubadilisha (haraka, bila AI)
      ?force=1   → lazimisha ikimbie hata kama imeshakimbia leo
    """
    import os
    import threading
    from datetime import date as _date
    from django.core.cache import cache
    from django.http import JsonResponse
    from . import hosting_service, daily_tasks

    expected = os.getenv('TASKS_TOKEN', '')
    if not expected:
        return JsonResponse(
            {'ok': False, 'error': 'Endpoint disabled — TASKS_TOKEN is not set.'},
            status=503)

    given = request.GET.get('token') or request.headers.get('X-Tasks-Token', '')
    if not secrets.compare_digest(str(given), str(expected)):
        return JsonResponse({'ok': False, 'error': 'Invalid token.'}, status=403)

    # Dry run — haraka, bila AI, bila kubadilisha chochote
    if request.GET.get('dry') in ('1', 'true', 'yes'):
        try:
            report = hosting_service.run_auto_suspend(dry_run=True)
        except Exception as e:
            logger.exception('daily tasks dry run failed')
            return JsonResponse({'ok': False, 'error': type(e).__name__}, status=500)
        return JsonResponse({
            'ok': True, 'dry_run': True, 'checked': report['checked'],
            'would_suspend': [r['website'].name for r in report['suspended']],
        })

    today = _date.today().isoformat()
    force = request.GET.get('force') in ('1', 'true', 'yes')

    # Imeshakimbia leo? (alama ile ile ya middleware)
    try:
        already = cache.get(daily_tasks.CACHE_KEY) == today
    except Exception:
        already = False

    if already and not force:
        return JsonResponse({'ok': True, 'status': 'already_ran_today', 'date': today})

    # Zuia kazi mbili kwa wakati mmoja
    with daily_tasks._thread_lock:
        if daily_tasks._running:
            return JsonResponse({'ok': True, 'status': 'already_running'})
        daily_tasks._running = True

    try:
        cache.set(daily_tasks.CACHE_KEY, today, daily_tasks.CACHE_TTL)
    except Exception:
        pass  # cache imelala — bado tunaendelea

    threading.Thread(target=daily_tasks._run_tasks_in_background,
                     name='jamiitek-daily-tasks-http', daemon=True).start()

    return JsonResponse({'ok': True, 'status': 'started', 'date': today})


# ══════════════════════════════════════════════════════════════
#  AI NEWSROOM — rasimu za habari za kila siku (cron endpoint)
# ══════════════════════════════════════════════════════════════

def news_blog_endpoint(request):
    """
    Endesha AI newsroom kupitia URL yenye token (cron-job.org / UptimeRobot):

        https://jamiitek.com/tasks/news/?token=XXXXX

    Inafanya kazi MARA MOJA kwa siku, baada ya saa NEWSROOM_HOUR (default 05:00 EAT).
    Inafaa kwa cron-job.org (mara moja kwa siku) au UptimeRobot (kila dakika 5 —
    pia inazuia Render isilale). Kazi halisi (AI + RSS) inafanyika kwenye thread
    ya nyuma; jibu linarudi mara moja. ?force=1 kulazimisha.
    """
    import os
    import threading
    from datetime import date as _date
    from django.core.cache import cache
    from django.http import JsonResponse

    expected = os.getenv('TASKS_TOKEN', '')
    if not expected:
        return JsonResponse({'ok': False, 'error': 'Endpoint disabled — TASKS_TOKEN not set.'}, status=503)

    given = request.GET.get('token') or request.headers.get('X-Tasks-Token', '')
    if not secrets.compare_digest(str(given), str(expected)):
        return JsonResponse({'ok': False, 'error': 'Invalid token.'}, status=403)

    from django.utils import timezone as _tz
    now = _tz.localtime()                      # saa za Tanzania (TIME_ZONE)
    today = now.date().isoformat()
    force = request.GET.get('force') in ('1', 'true', 'yes')
    CACHE_KEY = 'news_blog_ran_date'

    # Saa ya kuanza (default 05:00). Inaruhusu monitor inayopiga kila dakika 5
    # (UptimeRobot) — maombi kabla ya saa hii yanajibiwa 'waiting' bila kazi yoyote,
    # na ombi la kwanza baada yake ndilo linaloanzisha newsroom (mara moja kwa siku).
    try:
        start_hour = int(os.getenv('NEWSROOM_HOUR', '5'))
    except ValueError:
        start_hour = 5
    if not force and now.hour < start_hour:
        return JsonResponse({'ok': True, 'status': 'waiting',
                             'runs_at': f'{start_hour:02d}:00', 'date': today})

    try:
        already = cache.get(CACHE_KEY) == today
    except Exception:
        already = False
    if already and not force:
        return JsonResponse({'ok': True, 'status': 'already_ran_today', 'date': today})

    try:
        cache.set(CACHE_KEY, today, 60 * 60 * 26)
    except Exception:
        pass

    def _bg():
        try:
            from apps import news_blog
            news_blog.run_and_notify()      # email ya rasimu, au ripoti ikishindwa
        except Exception:
            logger.exception('AI newsroom background run failed')
        # JamiiTek Spotlight: makala 1 kuhusu JamiiTek, Jumatatu/Jumatano/Jumamosi.
        # Inajiamulia yenyewe kama leo ni siku yake na kama imeshaandika leo.
        try:
            from apps import spotlight_blog
            spotlight_blog.run_and_notify()
        except Exception:
            logger.exception('JamiiTek Spotlight background run failed')

    threading.Thread(target=_bg, name='jamiitek-news-blog', daemon=True).start()
    return JsonResponse({'ok': True, 'status': 'started', 'date': today})


# ══════════════════════════════════════════════════════════════
#  KUPAKIA IMAGE (Supabase Storage)
# ══════════════════════════════════════════════════════════════

@staff_required
def upload_file(request):
    """
    Inapokea file kutoka widget, inaipeleka Supabase, inarudisha URL.

    Ni ya staff pekee. Builder ina njia yake (`builder.views.asset_save`)
    inayomruhusu mteja kupakia kwenye tovuti yake mwenyewe.
    """
    from apps import storage

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST pekee'}, status=405)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'success': False, 'error': 'Hakuna file'}, status=400)

    result = storage.upload(f, folder=request.POST.get('folder', 'media'))
    return JsonResponse(result, status=200 if result.get('success') else 400)


@staff_required
def storage_health(request):
    """Ukaguzi wa haraka: je, bucket ipo na funguo inafanya kazi?"""
    from apps import storage
    return JsonResponse(storage.health())
