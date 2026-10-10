"""
Pesapal views — initiate, callback, IPN, na status page.

Njia:
  1. Mteja abonyeza "Lipa na Pesapal"  → view ya initiate hujenga
     PesapalTransaction, huanzisha order, na kumpeleka kwenye Pesapal.
  2. Baada ya kulipa, Pesapal humrudisha kwenye `pesapal_callback`
     (redirect ya browser) NA hutuma `pesapal_ipn` (server-to-server).
  3. Zote mbili huangalia hali halisi kupitia GetTransactionStatus
     kisha huendesha fulfillment (idempotent).
"""
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.http import Http404
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .pesapal_client import PesapalClient, PesapalError, STATUS_MAP
from .pesapal_models import PesapalTransaction
from .pesapal_fulfill import fulfill

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _abs(path):
    base = (getattr(settings, 'PESAPAL_BASE_URL', '') or '').rstrip('/')
    return f'{base}{path}'


def _safe_back(request):
    """Rudi ukurasa uliotoka — ndani ya tovuti hii tu (si open redirect)."""
    from django.utils.http import url_has_allowed_host_and_scheme
    ref = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return ref
    return '/'


def _start(tx, request):
    """
    Anzisha order Pesapal na mpeleke mteja. Inarudisha HttpResponse
    (redirect kwenda Pesapal, au kurudi na ujumbe wa hitilafu).
    """
    client = PesapalClient()
    if not client.configured:
        messages.error(request, 'Malipo ya mtandaoni bado hayajawashwa. Wasiliana na JamiiTek.')
        return redirect(_safe_back(request))

    tx.save()
    ipn_url = _abs(reverse('pesapal_ipn'))
    callback_url = _abs(reverse('pesapal_callback'))

    def _submit(ipn_id):
        return client.submit_order(
            merchant_reference=tx.merchant_reference,
            amount=tx.amount,
            currency=tx.currency,
            description=tx.description,
            callback_url=callback_url,
            ipn_id=ipn_id,
            email=tx.email,
            phone=tx.phone,
            first_name=tx.first_name,
            last_name=tx.last_name,
        )

    try:
        try:
            data = _submit(client.get_ipn_id(ipn_url))
        except PesapalError as first:
            # Self-heal: ipn ya zamani/env ikiwa batili, sajili mpya na jaribu tena
            if 'ipn' in str(first).lower():
                logger.warning('Pesapal IPN batili — nasajili upya: %s', first)
                data = _submit(client.get_ipn_id(ipn_url, force=True))
            else:
                raise
    except PesapalError as e:
        logger.error('Pesapal submit_order imeshindikana: %s', e)
        tx.status = 'failed'
        tx.raw_status = {'error': str(e)}
        tx.save(update_fields=['status', 'raw_status'])
        messages.error(request, f'Imeshindikana kuanzisha malipo: {e}')
        return redirect(_safe_back(request))

    tx.order_tracking_id = data['order_tracking_id']
    tx.redirect_url = data['redirect_url']
    tx.save(update_fields=['order_tracking_id', 'redirect_url'])
    return redirect(data['redirect_url'])


def _sync(tx):
    """Angalia hali halisi Pesapal na sasisha transaction. Inarudisha tx."""
    client = PesapalClient()
    try:
        data = client.get_status(tx.order_tracking_id)
    except PesapalError as e:
        logger.error('Pesapal get_status imeshindikana kwa %s: %s', tx.merchant_reference, e)
        return tx

    code = data.get('status_code')
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None

    tx.status_code = code
    tx.status = STATUS_MAP.get(code, 'pending')
    tx.payment_method = data.get('payment_method', '') or tx.payment_method
    tx.confirmation_code = data.get('confirmation_code', '') or tx.confirmation_code
    tx.raw_status = data
    if tx.status == 'completed' and not tx.completed_at:
        tx.completed_at = timezone.now()
    tx.save()
    return tx


# ─────────────────────────────────────────────
# INITIATE — CHATBOT SUBSCRIPTION
# ─────────────────────────────────────────────
@login_required(login_url='chatbot_login')
def pay_subscription(request):
    from apps.chatbot.models import SubscriptionPlan, BotSubscription
    from apps.chatbot.views import _get_or_create_client

    if request.method != 'POST':
        return redirect('chatbot_billing')

    client = _get_or_create_client(request.user)
    bot = client.bots.first()
    if not bot:
        messages.warning(request, 'Please complete your bot setup first.')
        return redirect('chatbot_setup_wizard')

    from apps.chatbot.billing import clean_months, price_for
    plan_id = request.POST.get('plan_id')
    months = clean_months(request.POST.get('months', 1))
    plan = SubscriptionPlan.objects.filter(id=plan_id, is_active=True).first() if str(plan_id or '').isdigit() else None
    if not plan:
        messages.error(request, 'Mpango uliochagua haupo.')
        return redirect('chatbot_billing')

    sub = getattr(bot, 'subscription', None)
    if not sub:
        from datetime import date, timedelta
        sub = BotSubscription.objects.create(
            bot=bot, plan=plan, status='trial',
            trial_ends=date.today() + timedelta(days=7),
            end_date=date.today() + timedelta(days=7),
        )

    # Punguzo sawa na linaloonyeshwa kwenye ukurasa (apps/chatbot/billing.py)
    amount = price_for(plan, months)
    tx = PesapalTransaction(
        purpose='chatbot_subscription',
        target_id=str(sub.id),
        amount=amount,
        currency='TZS',
        months=months,
        plan_id=plan.pk,          # ili fulfill iweke mpango uliolipiwa
        description=f'{plan.name} — {bot.bot_name} ({months} mo)',
        email=client.email or request.user.email,
        phone=client.phone or '',
        first_name=(client.full_name or '').split(' ')[0][:80],
        last_name=' '.join((client.full_name or '').split(' ')[1:])[:80],
    )
    return _start(tx, request)


# ─────────────────────────────────────────────
# INITIATE — HOSTING RENEWAL
# ─────────────────────────────────────────────
@login_required(login_url='/portal/login/')
def pay_hosting(request, website_pk):
    from apps.models import ManagedWebsite
    from .models import Client

    if request.method != 'POST':
        return redirect('portal_billing')

    # Resolve client (portal client, au chatbot user)
    client = Client.objects.filter(user=request.user).first()
    if not client:
        messages.error(request, 'Akaunti haijaunganishwa na client profile.')
        return redirect('/portal/login/')

    website = get_object_or_404(ManagedWebsite, pk=website_pk, client=client)
    # Chaguo zile zile zinazoonyeshwa kwenye portal. Awali `int()` ya moja
    # kwa moja: 'abc' ilileta Server Error, na months=500 iliunda agizo la
    # TZS 25,000,000 kwa website ya TZS 50,000/mwezi.
    from apps.chatbot.billing import clean_months
    months = clean_months(request.POST.get('months', 1))
    price = website.price_for(months)
    amount = price.get('total') or (float(website.monthly_cost or 0) * months)
    if not amount or float(amount) <= 0:
        messages.error(request, f'{website.name} haina bei ya hosting iliyowekwa. Wasiliana na JamiiTek.')
        return redirect('portal_billing')

    tx = PesapalTransaction(
        purpose='hosting_renewal',
        target_id=str(website.pk),
        amount=amount,
        currency='TZS',
        months=months,
        description=f'Hosting — {website.name} ({months} mo)',
        email=client.email or request.user.email,
        phone=getattr(client, 'phone', '') or '',
        first_name=(client.name or '').split(' ')[0][:80],
        last_name=' '.join((client.name or '').split(' ')[1:])[:80],
    )
    return _start(tx, request)


# ─────────────────────────────────────────────
# INITIATE — INVOICE (public)
# ─────────────────────────────────────────────
def pay_invoice(request, token):
    from apps.models import Invoice

    inv = get_object_or_404(Invoice, token=token)
    if inv.status in ('draft', 'cancelled'):
        raise Http404
    if inv.is_paid:
        messages.info(request, 'Invoice hii tayari imelipwa.')
        return redirect('invoice_view', token=token)

    amount = inv.balance_due or inv.grand_total
    if amount <= 0:
        messages.error(request, 'Kiasi cha kulipa si sahihi.')
        return redirect('invoice_view', token=token)

    tx = PesapalTransaction(
        purpose='invoice',
        target_id=inv.token,
        amount=amount,
        currency=inv.currency or 'TZS',
        months=1,
        description=f'{inv.invoice_number or "Invoice"} — {inv.display_client}'[:100],
        email=inv.client_email or '',
        phone=inv.client_phone or '',
        first_name=(inv.display_client or '').split(' ')[0][:80],
        last_name=' '.join((inv.display_client or '').split(' ')[1:])[:80],
    )
    return _start(tx, request)


# ─────────────────────────────────────────────
# CALLBACK (browser redirect back)
# ─────────────────────────────────────────────
def pesapal_callback(request):
    tracking = request.GET.get('OrderTrackingId') or request.GET.get('orderTrackingId')
    ref = request.GET.get('OrderMerchantReference') or request.GET.get('orderMerchantReference')

    tx = None
    if tracking:
        tx = PesapalTransaction.objects.filter(order_tracking_id=tracking).first()
    if not tx and ref:
        tx = PesapalTransaction.objects.filter(merchant_reference=ref).first()

    if not tx:
        return render(request, 'pesapal/status.html', {'tx': None, 'not_found': True}, status=404)

    if tx.status != 'completed':
        _sync(tx)
    if tx.status == 'completed':
        try:
            fulfill(tx)
        except Exception:
            logger.exception('Pesapal callback fulfillment error')

    return render(request, 'pesapal/status.html', {
        'tx': tx,
        'continue_url': _continue_url(tx),
    })


# ─────────────────────────────────────────────
# IPN (server-to-server)
# ─────────────────────────────────────────────
@csrf_exempt
def pesapal_ipn(request):
    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode() or '{}')
        except (ValueError, UnicodeDecodeError):
            body = {}
        tracking = body.get('OrderTrackingId') or request.POST.get('OrderTrackingId')
        ref = body.get('OrderMerchantReference') or request.POST.get('OrderMerchantReference')
        ntype = body.get('OrderNotificationType') or request.POST.get('OrderNotificationType')
    else:
        tracking = request.GET.get('OrderTrackingId')
        ref = request.GET.get('OrderMerchantReference')
        ntype = request.GET.get('OrderNotificationType')

    if not tracking:
        return HttpResponseBadRequest('Missing OrderTrackingId')

    tx = PesapalTransaction.objects.filter(order_tracking_id=tracking).first()
    if not tx and ref:
        tx = PesapalTransaction.objects.filter(merchant_reference=ref).first()

    status = 200
    if tx:
        _sync(tx)
        if tx.status == 'completed':
            try:
                fulfill(tx)
            except Exception:
                logger.exception('Pesapal IPN fulfillment error')
                status = 500
    else:
        logger.warning('Pesapal IPN: transaction haipo (tracking=%s ref=%s)', tracking, ref)

    return JsonResponse({
        'orderNotificationType': ntype,
        'orderTrackingId': tracking,
        'orderMerchantReference': ref,
        'status': status,
    })


def _continue_url(tx):
    """Wapi mteja aende baada ya status page."""
    if not tx:
        return '/'
    if tx.purpose == 'chatbot_subscription':
        return reverse('chatbot_billing')
    if tx.purpose == 'hosting_renewal':
        return reverse('portal_billing')
    if tx.purpose == 'invoice':
        try:
            return reverse('invoice_view', kwargs={'token': tx.target_id})
        except Exception:
            return '/'
    return '/'
