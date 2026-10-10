"""
JamiiTek ChatBot — Management Views (Staff Only)
William's panel to manage all bots, clients, payments, WhatsApp setup.
"""
import logging
from datetime import date, timedelta

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.conf import settings

from .models import (
    ChatbotClient, BotConfig, BotSubscription,
    SubscriptionPlan, SubscriptionPayment, Conversation, Message
)

logger = logging.getLogger('chatbot.manage')


def staff_required(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return redirect('/manage/login/')
        return view_func(request, *args, **kwargs)
    return wrapper


def manage_context(request):
    """Context processor — adds pending counts to all manage pages."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return {}
    try:
        pending_payments = SubscriptionPayment.objects.filter(status='pending').count()

        pending_bots = BotConfig.objects.filter(status='pending').count()
        return {
            'chatbot_pending_payments': pending_payments,
            'chatbot_pending_bots': pending_bots,
        }
    except Exception:
        return {}


# ════════════════════════════════════════════════════════
# OVERVIEW DASHBOARD
# ════════════════════════════════════════════════════════

@staff_required
def manage_chatbot_overview(request):
    """Main JamiiBot management dashboard."""
    from datetime import date, timedelta
    from django.db.models import Count

    from django.core.cache import cache
    from django.db.models import Q

    # Kasi: awali kila Conversation (pamoja na memory/metadata) ilipakiwa ili
    # kuhesabu tu. Sasa idadi inatoka kwa annotate, na hali 4 kwa swali moja.
    all_bots = list(BotConfig.objects.select_related('client', 'subscription__plan')
                    .annotate(conv_count=Count('conversations'))
                    .order_by('-created_at'))
    all_clients = ChatbotClient.objects.count()
    by_status = BotConfig.objects.aggregate(
        active=Count('pk', filter=Q(status='active')),
        pending=Count('pk', filter=Q(status='pending')),
        suspended=Count('pk', filter=Q(status='suspended')),
        draft=Count('pk', filter=Q(status='draft')),
    )
    active_bots, pending_bots = by_status['active'], by_status['pending']
    suspended_bots, draft_bots = by_status['suspended'], by_status['draft']

    # Jumla za majedwali makubwa — zinahesabiwa upya kila dakika moja tu
    totals = cache.get('manage:bot_totals')
    if totals is None:
        totals = (Message.objects.count(), Conversation.objects.count())
        cache.set('manage:bot_totals', totals, 60)
    total_msgs, total_convs = totals
    today_msgs  = Message.objects.filter(created_at__date=date.today()).count()

    total_revenue = SubscriptionPayment.objects.filter(
        status='verified'
    ).aggregate(t=Sum('amount'))['t'] or 0

    pending_payments = SubscriptionPayment.objects.filter(status='pending').count()

    # Wanaosubiri binadamu. Hii ndiyo namba pekee hapa inayogusa mteja
    # anayesubiri SASA HIVI — inapaswa kuonekana kabla ya nyingine zote.
    waiting_qs = (Conversation.objects
                  .filter(is_human_handoff=True, handoff_at__isnull=False)
                  .select_related('bot')
                  .order_by('handoff_at'))
    waiting_handoffs = waiting_qs.count()
    waiting_list = list(waiting_qs[:6])
    waiting_worst = waiting_list[0].handoff_waiting_minutes if waiting_list else 0

    recent_clients = ChatbotClient.objects.select_related('user').order_by('-created_at')[:8]

    bots_needing_setup = [b for b in all_bots if b.status == 'pending']

    # Chart data — last 30 days
    from .stats import daily_counts
    chart_data = daily_counts(Message.objects.all(), 30)

    import json
    context = {
        'all_bots': all_bots,
        'all_clients': all_clients,
        'active_bots': active_bots,
        'pending_bots': pending_bots,
        'suspended_bots': suspended_bots,
        'draft_bots': draft_bots,
        'clients': all_clients,
        'total_msgs': total_msgs,
        'total_convs': total_convs,
        'today_msgs': today_msgs,
        'total_revenue': total_revenue,
        'pending_bot_payments': pending_payments,
        'recent_clients': recent_clients,
        'bots_needing_setup': bots_needing_setup,
        'chart_data': json.dumps(chart_data),
        'waiting_handoffs': waiting_handoffs,
        'waiting_list': waiting_list,
        'waiting_worst': waiting_worst,
    }
    return render(request, 'management/chatbot_overview.html', context)


# ════════════════════════════════════════════════════════
# BOT DETAIL & CONTROL
# ════════════════════════════════════════════════════════

@staff_required
def manage_bot_detail(request, bot_id):
    """Full control panel for a single bot."""
    bot  = get_object_or_404(BotConfig, id=bot_id)
    sub  = getattr(bot, 'subscription', None)
    convs = bot.conversations.order_by('-last_message_at')[:15]
    payments = sub.payments.order_by('-payment_date') if sub else []

    total_msgs  = Message.objects.filter(conversation__bot=bot).count()
    total_users = bot.conversations.values('customer_phone').distinct().count()
    today_msgs  = Message.objects.filter(
        conversation__bot=bot, created_at__date=date.today()
    ).count()

    context = {
        'bot': bot, 'sub': sub,
        'conversations': convs,
        'payments': payments,
        'total_msgs': total_msgs,
        'total_users': total_users,
        'today_msgs': today_msgs,
        'global_token_set': bool(getattr(settings, 'WHATSAPP_MASTER_TOKEN', '')),
        'services': bot.services.all(),
        'faqs': bot.faqs.all(),
    }
    return render(request, 'management/chatbot_bot_detail.html', context)


@staff_required
def manage_bot_action(request, bot_id):
    """Handle bot actions: suspend, activate, add phone ID, notes."""
    if request.method != 'POST':
        return redirect('manage_bot_detail', bot_id=bot_id)

    bot    = get_object_or_404(BotConfig, id=bot_id)
    action = request.POST.get('action')

    if action == 'suspend':
        bot.status    = 'suspended'
        bot.is_active = False
        bot.admin_suspended_reason = request.POST.get('reason', 'Admin action')
        bot.save()
        messages.success(request, f"Bot '{bot.bot_name}' imesimamishwa.")

    elif action == 'activate':
        # Zamani hii ilidai `whatsapp_phone_id` ya Meta. Kwa Baileys
        # hakuna phone ID — mteja anascan QR. Sharti hilo lingezuia
        # kila bot milele.
        bot.status    = 'active'
        bot.is_active = True
        bot.admin_suspended_reason = ''
        bot.save()
        messages.success(request, f"Bot '{bot.bot_name}' imewashwa! ✅")

    elif action == 'save_whatsapp':
        phone_number  = request.POST.get('whatsapp_number', '').strip()
        phone_id      = request.POST.get('whatsapp_phone_id', '').strip()
        token_override = request.POST.get('whatsapp_token', '').strip()

        bot.whatsapp_number   = phone_number
        bot.whatsapp_phone_id = phone_id
        if token_override:
            bot.whatsapp_token = token_override
        bot.save(update_fields=['whatsapp_number', 'whatsapp_phone_id', 'whatsapp_token'])

        if phone_id:
            # Auto-activate if was pending
            if bot.status == 'pending':
                bot.status    = 'active'
                bot.is_active = True
                bot.save()
            messages.success(request, f"✅ WhatsApp imeunganishwa! Bot '{bot.bot_name}' inafanya kazi.")
        else:
            messages.warning(request, "Phone Number ID haikuwekwa — bot bado haijawashwa.")

    elif action == 'admin_note':
        bot.admin_notes = request.POST.get('note', '')
        bot.save(update_fields=['admin_notes'])
        messages.success(request, "Admin notes saved.")

    elif action == 'reset_webhook':
        import secrets
        bot.webhook_verify_token = secrets.token_hex(16)
        bot.save(update_fields=['webhook_verify_token'])
        messages.success(request, "Webhook token has been reset.")

    elif action == 'save_config':
        bot.bot_name      = request.POST.get('bot_name', bot.bot_name).strip()
        bot.description   = request.POST.get('description', bot.description).strip()
        bot.language      = request.POST.get('language', bot.language)
        bot.tone          = request.POST.get('tone', bot.tone)
        bot.ai_temperature = float(request.POST.get('ai_temperature', bot.ai_temperature))
        bot.business_name = request.POST.get('business_name', bot.business_name).strip()
        bot.save(update_fields=['bot_name', 'description', 'language', 'tone', 'ai_temperature', 'business_name'])
        messages.success(request, f"✅ Bot configuration saved.")

    elif action == 'save_messages':
        bot.greeting_msg     = request.POST.get('greeting_msg', bot.greeting_msg).strip()
        bot.fallback_msg     = request.POST.get('fallback_msg', bot.fallback_msg).strip()
        bot.human_handoff_msg = request.POST.get('human_handoff_msg', bot.human_handoff_msg).strip()
        bot.collect_name     = 'collect_name' in request.POST
        bot.collect_phone    = 'collect_phone' in request.POST
        bot.save(update_fields=['greeting_msg', 'fallback_msg', 'human_handoff_msg', 'collect_name', 'collect_phone'])
        messages.success(request, "✅ Bot messages saved.")

    elif action == 'add_service':
        from .models import BotService
        name  = request.POST.get('service_name', '').strip()
        desc  = request.POST.get('service_desc', '').strip()
        price = request.POST.get('service_price', '').strip()
        if name and desc:
            BotService.objects.create(bot=bot, name=name, description=desc, price=price)
            messages.success(request, f"✅ Service '{name}' added.")
        else:
            messages.error(request, "Service name and description are required.")

    elif action == 'delete_service':
        from .models import BotService
        svc_id = request.POST.get('service_id')
        BotService.objects.filter(id=svc_id, bot=bot).delete()
        messages.success(request, "Service deleted.")

    elif action == 'add_faq':
        from .models import BotFAQ
        question = request.POST.get('faq_question', '').strip()
        answer   = request.POST.get('faq_answer', '').strip()
        if question and answer:
            BotFAQ.objects.create(bot=bot, question=question, answer=answer)
            messages.success(request, "✅ FAQ added.")
        else:
            messages.error(request, "Question and answer are required.")

    elif action == 'delete_faq':
        from .models import BotFAQ
        faq_id = request.POST.get('faq_id')
        BotFAQ.objects.filter(id=faq_id, bot=bot).delete()
        messages.success(request, "FAQ deleted.")

    elif action == 'extend_subscription':
        if sub:
            from datetime import timedelta
            days = int(request.POST.get('days', 30))
            from django.utils import timezone
            import datetime
            base = sub.end_date if sub.end_date and sub.end_date >= datetime.date.today() else datetime.date.today()
            sub.end_date = base + timedelta(days=days)
            sub.status   = 'active'
            sub.save()
            messages.success(request, f"✅ Subscription extended by {days} days.")

    return redirect('manage_bot_detail', bot_id=bot_id)


# ════════════════════════════════════════════════════════
# PAYMENTS
# ════════════════════════════════════════════════════════

@staff_required
def manage_bot_payments(request):
    """All pending & recent payments."""
    pending  = SubscriptionPayment.objects.filter(
        status='pending'
    ).select_related('subscription__bot__client').order_by('-payment_date')

    verified = SubscriptionPayment.objects.filter(
        status='verified'
    ).select_related('subscription__bot__client', 'verified_by').order_by('-verified_at')[:30]

    rejected = SubscriptionPayment.objects.filter(
        status='rejected'
    ).select_related('subscription__bot__client').order_by('-payment_date')[:10]

    total_revenue = SubscriptionPayment.objects.filter(
        status='verified'
    ).aggregate(t=Sum('amount'))['t'] or 0

    pending_amount = pending.aggregate(t=Sum('amount'))['t'] or 0

    context = {
        'pending': pending,
        'verified': verified,
        'rejected': rejected,
        'total_revenue': total_revenue,
        'pending_amount': pending_amount,
    }
    return render(request, 'management/chatbot_payments.html', context)


@staff_required
def manage_verify_payment(request, payment_id):
    """Verify a payment and extend subscription."""
    if request.method != 'POST':
        return redirect('manage_bot_payments')

    pay = get_object_or_404(SubscriptionPayment, id=payment_id)
    from .billing import verify_payment
    if not verify_payment(pay, user=request.user, months=request.POST.get('months')):
        # Awali kubonyeza mara ya pili kuliongeza mwezi mwingine bure
        messages.info(request, f"Malipo #{pay.id} yalikwisha thibitishwa — hakuna kilichobadilika.")
        return redirect('manage_bot_payments')
    sub = pay.subscription
    sub.refresh_from_db()
    messages.success(
        request,
        f"✅ Malipo yamethibitishwa! {sub.bot.bot_name} — {sub.plan.name} hadi {sub.end_date}."
    )
    return redirect('manage_bot_payments')


@staff_required
def manage_reject_payment(request, payment_id):
    """Reject a payment."""
    if request.method != 'POST':
        return redirect('manage_bot_payments')

    pay = get_object_or_404(SubscriptionPayment, id=payment_id)
    pay.status = 'rejected'
    pay.save()
    messages.warning(request, f"Malipo #{payment_id} yamekataliwa.")
    return redirect('manage_bot_payments')


@staff_required
def manage_bulk_payment_action(request):
    """Bulk verify or reject selected payments."""
    if request.method != 'POST':
        return redirect('manage_bot_payments')

    action  = request.POST.get('bulk_action')
    pay_ids = request.POST.getlist('payment_ids')

    if not pay_ids:
        messages.warning(request, "Hakuna malipo yaliyochaguliwa.")
        return redirect('manage_bot_payments')

    pays = SubscriptionPayment.objects.filter(id__in=pay_ids, status='pending')

    if action == 'verify_all':
        from .billing import verify_payment, price_for
        # list() — `pays.count()` baada ya kuthibitisha ilihesabu upya na
        # kupata 0 (hakuna tena yaliyo 'pending'), ikaripoti "Malipo 0".
        # Mteja ndiye anayechagua mpango/miezi/kiasi kwenye fomu, kwa hiyo
        # kuthibitisha kwa wingi kunakubali TU malipo ambayo kiasi kinatosha
        # bei ya mpango huo. Mengine yanabaki 'pending' yakaguliwe moja moja.
        done, held = 0, 0
        for pay in list(pays):
            if pay.plan and int(pay.amount or 0) < price_for(pay.plan, pay.months_covered):
                held += 1
                continue
            done += verify_payment(pay, user=request.user)
        messages.success(request, f"✅ Malipo {done} yamethibitishwa.")
        if held:
            messages.warning(request, f"⚠️ Malipo {held} hayakuthibitishwa: kiasi ni pungufu ya bei ya "
                                      f"mpango uliochaguliwa. Yakague moja moja.")

    elif action == 'reject_all':
        pays.update(status='rejected')
        messages.warning(request, f"Malipo {len(pay_ids)} yamekataliwa.")

    return redirect('manage_bot_payments')


# ════════════════════════════════════════════════════════
# CLIENTS
# ════════════════════════════════════════════════════════

@staff_required
def manage_bot_clients(request):
    """All registered JamiiBot clients."""
    from datetime import date
    search = request.GET.get('q', '').strip()
    filter_status = request.GET.get('status', '').strip()

    clients = ChatbotClient.objects.select_related('user').prefetch_related(
        'bots', 'bots__subscription__plan'
    ).order_by('-created_at')

    if search:
        clients = clients.filter(
            Q(full_name__icontains=search) |
            Q(business_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    today = date.today()
    total_clients   = ChatbotClient.objects.count()
    active_bots     = ChatbotClient.objects.filter(bots__status='active').distinct().count()
    this_month      = ChatbotClient.objects.filter(
        created_at__month=today.month, created_at__year=today.year
    ).count()
    no_bot          = ChatbotClient.objects.filter(bots__isnull=True).count()

    context = {
        'clients':       clients,
        'search':        search,
        'total_clients': total_clients,
        'active_bots':   active_bots,
        'this_month':    this_month,
        'no_bot':        no_bot,
    }
    return render(request, 'management/chatbot_clients.html', context)


# ════════════════════════════════════════════════════════
# WHATSAPP SETUP PER BOT
# ════════════════════════════════════════════════════════

@staff_required
def manage_bot_whatsapp(request, bot_id):
    """
    Namba za bot: ya biashara na ya mmiliki.

    UKURASA HUU ULIKUWA WA META. Ulikuwa unadai Phone Number ID na
    `WHATSAPP_MASTER_TOKEN`, ukisema "Token haijawekwa! Bots zote
    hazitafanya kazi" — si kweli tangu tulipohamia Baileys.

    Mbaya zaidi, ulikuwa unaagiza: "Mwambie mteja afute akaunti yake
    ya WhatsApp kwenye simu kwanza." Kwa Meta hiyo ilikuwa lazima.
    Kwa Baileys ingevunja bot kabisa — WhatsApp inapaswa KUBAKI
    kwenye simu ili QR iweze kuscanwa na session ikae hai.

    Sasa unashughulikia namba pekee; kuunganisha kunafanyika
    /manage/chatbot/sessions/.
    """
    from apps.chatbot import bridge

    bot = get_object_or_404(BotConfig, id=bot_id)

    if request.method == 'POST':
        bot.whatsapp_number = request.POST.get('whatsapp_number', '').strip()
        bot.owner_whatsapp  = request.POST.get('owner_whatsapp', '').strip()
        bot.notify_handoff  = bool(request.POST.get('notify_handoff'))
        # Namba ya mmiliki ikibadilika, LID ya zamani haifai tena
        bot.owner_lid = ''
        bot.save(update_fields=['whatsapp_number', 'owner_whatsapp',
                                'notify_handoff', 'owner_lid'])
        messages.success(request, f"Namba za {bot.bot_name} zimehifadhiwa.")
        return redirect('manage_bot_whatsapp', bot_id=bot_id)

    live = None
    if bridge.is_configured():
        data = bridge.session_status(bot.session_name, timeout=5)
        if data.get('success'):
            live = data

    return render(request, 'management/chatbot_whatsapp.html', {
        'bot': bot,
        'live': live,
        'bridge_ok': bridge.is_configured(),
        'all_bots': BotConfig.objects.select_related('client').order_by('bot_name'),
    })


# ════════════════════════════════════════════════════════
# PUBLIC LANDING PAGE
# ════════════════════════════════════════════════════════

def jamiibot_landing(request):
    """Public marketing page for JamiiBot."""
    from apps.seo.schema import jamiibot_product_schema, breadcrumb_schema, render_schemas
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('price_tzs')
    schema = render_schemas(
        jamiibot_product_schema(list(plans)),
        breadcrumb_schema([('Home', '/'), ('JamiiBot', '/bot/')]),
    )
    return render(request, 'chatbot_landing/jamiibot_landing.html', {'plans': plans, 'schema_markup': schema})

# ══════════════════════════════════════════════════════════════
#  BAILEYS SESSIONS
# ══════════════════════════════════════════════════════════════

@staff_required
def manage_sessions(request):
    """Orodha ya sessions zote pamoja na hali yao halisi kutoka bridge."""
    from apps.chatbot import bridge

    bots = list(BotConfig.objects.select_related('client').order_by('bot_name'))

    # Bridge ya free tier inaweza kulala: awali ukurasa ulisubiri hadi
    # sekunde 23 (health 8s + sessions 15s). Sasa muda mfupi, na jibu
    # linahifadhiwa sekunde 20 (sekunde 60 kama bridge haipatikani).
    from django.core.cache import cache
    snap = cache.get('manage:bridge_sessions')
    if snap is None or request.GET.get('refresh'):
        health = bridge.health(timeout=4)
        sessions = bridge.list_sessions(timeout=6).get('sessions', []) if health.get('success') else []
        snap = {'health': health, 'sessions': sessions}
        cache.set('manage:bridge_sessions', snap, 20 if health.get('success') else 60)
    health = snap['health']
    live = {s['session']: s for s in snap['sessions'] if s.get('session')}

    for b in bots:
        b.live = live.get(b.session_name)

    return render(request, 'management/chatbot_sessions.html', {
        'bots': bots,
        'bridge_ok': bool(health.get('success')),
        'bridge_error': health.get('error', ''),
        'bridge_configured': bridge.is_configured(),
        'health': health,
    })


@staff_required
def manage_session_qr(request, bot_id):
    """
    JSON kwa modal ya QR. Ukurasa unaipiga kila sekunde 5 —
    QR ya WhatsApp inaisha baada ya ~60s, kwa hiyo inabidi ionekane
    mpya bila kurefresh ukurasa.
    """
    bot = get_object_or_404(BotConfig, id=bot_id)
    from apps.chatbot import bridge

    data = bridge.session_qr(bot.session_name)

    # Session bado haijaanzishwa kwenye bridge — ianzishe
    if not data.get('success') and 'haipo' in str(data.get('error', '')):
        bridge.start_session(bot.session_name)
        data = bridge.session_qr(bot.session_name)

    _sync_bot_status(bot, data)
    return JsonResponse(data)


@staff_required
def manage_session_action(request, bot_id):
    """start | restart | stop | logout"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST pekee'}, status=405)

    bot = get_object_or_404(BotConfig, id=bot_id)
    action = request.POST.get('action', '')
    from django.core.cache import cache
    cache.delete('manage:bridge_sessions')   # orodha ionyeshe hali mpya mara moja
    from apps.chatbot import bridge

    if action == 'start':
        data = bridge.start_session(bot.session_name)
    elif action == 'restart':
        data = bridge.restart_session(bot.session_name)
    elif action == 'stop':
        data = bridge.stop_session(bot.session_name)
    elif action == 'logout':
        # Kufuta session kunamlazimisha mteja kuscan QR upya — labda
        # hayuko ofisini. Kwa hiyo inadai jina la biashara liandikwe,
        # kama GitHub inavyodai jina la repo kabla ya kuifuta.
        typed = (request.POST.get('confirm') or '').strip().lower()
        if typed != (bot.business_name or '').strip().lower():
            return JsonResponse({
                'success': False,
                'error': 'Andika jina la biashara kwa usahihi ili kuthibitisha.',
            }, status=400)
        data = bridge.logout_session(bot.session_name)
    else:
        return JsonResponse({'success': False, 'error': 'Kitendo hakijulikani'}, status=400)

    _sync_bot_status(bot, data)

    # Kila kitendo kinaingia kwenye kumbukumbu. Siku mteja atakapouliza
    # "kwa nini nilitakiwa kuscan tena Jumanne?", jibu lipo.
    try:
        from apps.integration_models import IntegrationAuditLog
        IntegrationAuditLog.record(
            action=f'baileys_{action}',
            user=request.user,
            detail={'session': bot.session_name, 'bot': bot.bot_name,
                    'ok': bool(data.get('success')), 'error': data.get('error', '')},
            request=request,
        )
    except Exception:
        logger.warning('audit log imeshindwa kwa %s', bot.session_name)

    return JsonResponse(data)


def _sync_bot_status(bot, data):
    """Hifadhi hali ya bridge kwenye BotConfig ili dashboard isome haraka."""
    if not data.get('success'):
        return
    fields = []
    status = data.get('status')
    if status and status != bot.connection_status:
        bot.connection_status = status
        fields.append('connection_status')
    number = data.get('number') or ''
    if number and number != bot.connected_number:
        bot.connected_number = number
        fields.append('connected_number')
    if status == 'connected':
        from django.utils import timezone as _tz
        bot.last_seen_at = _tz.now()
        fields.append('last_seen_at')
    if fields:
        bot.save(update_fields=fields)
