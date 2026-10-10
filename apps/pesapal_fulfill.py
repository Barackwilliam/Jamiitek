"""
Fulfillment — kinachotokea baada ya malipo KUKAMILIKA.

Kila `purpose` ina handler yake. Zote ni idempotent: `tx.fulfilled` +
`select_for_update()` huhakikisha kazi inafanyika MARA MOJA tu, hata kama
callback na IPN zote mbili zikija (Pesapal hutuma zote).

Hakuna kitu kinachobadilishwa kwenye model zilizopo isipokuwa kuongeza
rekodi ya malipo na kusogeza tarehe ya mwisho — sawasawa na jinsi staff
walivyokuwa wanafanya kwa mkono.
"""
import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def _add_months(d, months):
    try:
        from dateutil.relativedelta import relativedelta
        return d + relativedelta(months=int(months))
    except ImportError:
        return d + timedelta(days=30 * int(months))


def fulfill(tx):
    """
    Elekeza kwenye handler sahihi. Inaitwa na callback NA ipn.
    Inarudisha True ikiwa fulfillment imefanyika sasa (mara ya kwanza).
    """
    if tx.status != 'completed':
        return False

    with transaction.atomic():
        # Funga rekodi ili callback + IPN zisigongane
        locked = type(tx).objects.select_for_update().get(pk=tx.pk)
        if locked.fulfilled:
            return False

        handler = {
            'chatbot_subscription': _fulfill_subscription,
            'hosting_renewal':      _fulfill_hosting,
            'invoice':              _fulfill_invoice,
        }.get(locked.purpose)

        if not handler:
            logger.error('Pesapal: purpose isiyojulikana %s', locked.purpose)
            return False

        try:
            delivered = handler(locked)
        except Exception:
            logger.exception('Pesapal fulfillment imeshindikana kwa %s', locked.merchant_reference)
            raise

        if delivered is False:
            # Pesa imepokelewa lakini kitu kilicholipiwa hakipo (kimefutwa).
            # Awali hii iliandikwa kwenye log tu — mteja amelipa, hakupata
            # huduma, na hakuna aliyejua. Sasa JamiiTek inaarifiwa mara moja.
            def _alert(tx=locked):
                try:
                    from apps.notify import notify
                    notify(f'⚠️ MALIPO BILA HUDUMA: {tx.merchant_reference} — TZS {tx.amount:,.0f} '
                           f'({tx.get_purpose_display()}, target={tx.target_id}) kutoka '
                           f'{tx.first_name} {tx.last_name} {tx.phone}. Kitu kilicholipiwa hakipo — '
                           f'kirejeshe au mrudishie pesa.')
                except Exception:
                    logger.exception('Pesapal: taarifa ya malipo bila huduma imeshindwa')
            transaction.on_commit(_alert)

        locked.fulfilled = True
        locked.completed_at = locked.completed_at or timezone.now()
        locked.save(update_fields=['fulfilled', 'completed_at'])

        # Risiti + email zitumwe MARA MOJA baada ya commit kufanikiwa
        # (nje ya lock) — hivyo hazitumwi kama transaction itarudishwa.
        def _issue():
            try:
                from .pesapal_receipt import issue_receipt
                issue_receipt(locked)
            except Exception:
                logger.exception('Pesapal: issue_receipt imeshindikana')
        transaction.on_commit(_issue)
        return True


# ─────────────────────────────────────────────
# CHATBOT SUBSCRIPTION
# ─────────────────────────────────────────────
def _fulfill_subscription(tx):
    from apps.chatbot.models import BotSubscription, SubscriptionPayment

    sub = BotSubscription.objects.select_for_update().filter(id=tx.target_id).first()
    if not sub:
        logger.error('Pesapal: BotSubscription %s haipo', tx.target_id)
        return False

    months = int(tx.months or 1)
    ref = tx.confirmation_code or tx.merchant_reference

    # Epuka kurekodi mara mbili kwa transaction ile ile
    if not SubscriptionPayment.objects.filter(transaction_ref=ref).exists():
        SubscriptionPayment.objects.create(
            subscription=sub,
            plan_id=tx.plan_id,
            amount=int(round(float(tx.amount))),
            months_covered=months,
            payment_method='Pesapal',
            transaction_ref=ref,
            status='verified',
            verified_at=timezone.now(),
            notes=f'Pesapal {tx.merchant_reference} ({tx.payment_method})',
        )

    # Mpango uliolipiwa — awali haukuwekwa, mteja alibaki kwenye wa zamani
    from apps.chatbot.billing import apply_payment
    from apps.chatbot.models import SubscriptionPlan
    plan = SubscriptionPlan.objects.filter(pk=tx.plan_id).first() if tx.plan_id else None
    apply_payment(sub, months, plan=plan)
    logger.info('Pesapal: subscription %s (%s) imeongezwa hadi %s',
                sub.pk, sub.plan.name, sub.end_date)


# ─────────────────────────────────────────────
# HOSTING RENEWAL
# ─────────────────────────────────────────────
def _fulfill_hosting(tx):
    from apps.models import ManagedWebsite, HostingPayment

    site = ManagedWebsite.objects.select_for_update().filter(pk=tx.target_id).first()
    if not site:
        logger.error('Pesapal: ManagedWebsite %s haipo', tx.target_id)
        return False

    months = int(tx.months or 1)
    ref = tx.confirmation_code or tx.merchant_reference

    if not HostingPayment.objects.filter(transaction_ref=ref).exists():
        HostingPayment.objects.create(
            website=site,
            amount=tx.amount,
            payment_date=timezone.now().date(),
            months_covered=months,
            payment_method='Pesapal',
            transaction_ref=ref,
            notes=f'Pesapal {tx.merchant_reference} ({tx.payment_method})',
        )

    today = timezone.now().date()
    base = site.hosting_end_date if (site.hosting_end_date and site.hosting_end_date > today) else today
    site.hosting_end_date = _add_months(base, months)
    if site.status in ('suspended', 'maintenance'):
        site.status = 'active'
    site.save(update_fields=['hosting_end_date', 'status'])
    logger.info('Pesapal: hosting %s imeongezwa hadi %s', site.pk, site.hosting_end_date)


# ─────────────────────────────────────────────
# INVOICE
# ─────────────────────────────────────────────
def _fulfill_invoice(tx):
    from apps.models import Invoice

    inv = Invoice.objects.select_for_update().filter(token=tx.target_id).first()
    if not inv:
        logger.error('Pesapal: Invoice %s haipo', tx.target_id)
        return False

    # Kiasi HALISI kilicholipwa, si "imelipwa yote". Invoice ikibadilishwa
    # baada ya mteja kuanzisha malipo (bidhaa imeongezwa), kiasi cha zamani
    # kiliiweka "Paid" kamili — na salio jipya likapotea. Malipo yanaingia
    # kwenye historia ya ankara; hali (partial/paid) inafuata kiasi.
    inv.record_payment(tx.amount, method='Pesapal',
                       reference=tx.confirmation_code or tx.merchant_reference,
                       by=tx.email or tx.phone or '', source='pesapal')
    inv.save(update_fields=['amount_paid', 'payments', 'status', 'paid_at', 'paid_reference', 'sent_at'])
    logger.info('Pesapal: invoice %s imelipwa', inv.invoice_number or inv.pk)
