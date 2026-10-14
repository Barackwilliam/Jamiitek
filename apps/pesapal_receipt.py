"""
Receipt + email ya kiotomatiki baada ya malipo ya Pesapal kukamilika.

Inatengeneza `DevelopmentReceipt` (risiti ile ile inayotumika popote kwenye
mfumo), inaitengenezea PDF (xhtml2pdf — hakuna system deps), kisha inaituma
kwa mteja kwa email na nakala kwa mmiliki (info@jamiitek.com).

Yote ni best-effort: hitilafu yoyote hairudishi malipo wala kuvunja
fulfillment — inaandikwa kwenye log tu. Idempotent: risiti moja kwa kila
transaction (guard kwa payment_reference).
"""
import logging
from io import BytesIO

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

OWNER_EMAIL = getattr(settings, 'PAYMENTS_OWNER_EMAIL', 'info@jamiitek.com')
FROM_EMAIL = getattr(settings, 'DEFAULT_FROM_EMAIL', 'JamiiTek <noreply@jamiitek.com>')


# ── ramani ya njia ya malipo → chaguo za receipt ─────────
def _map_method(raw):
    r = (raw or '').lower()
    if 'mpesa' in r or 'm-pesa' in r:
        return 'mpesa'
    if 'airtel' in r:
        return 'airtel'
    if 'tigo' in r or 'mixx' in r:
        return 'tigopesa'
    if 'halo' in r:
        return 'halopesa'
    if 'bank' in r or 'visa' in r or 'master' in r or 'card' in r:
        return 'bank'
    return 'other'


def _title_for(tx):
    return {
        'chatbot_subscription': 'JamiiBot Subscription',
        'hosting_renewal':      'Hosting Renewal',
        'invoice':              'Invoice Payment',
        'builder_template':     'Website Template',
        'builder_logo':         'Remove JamiiTek Logo',
    }.get(tx.purpose, 'Payment')


def create_receipt(tx):
    """Tengeneza (au rudisha iliyopo) DevelopmentReceipt kwa transaction."""
    from apps.models import DevelopmentReceipt, ManagedWebsite

    ref = tx.confirmation_code or tx.merchant_reference

    existing = DevelopmentReceipt.objects.filter(payment_reference=ref).first()
    if existing:
        return existing

    website = None
    if tx.purpose == 'hosting_renewal':
        website = ManagedWebsite.objects.filter(pk=tx.target_id).first()

    amount = tx.amount
    receipt = DevelopmentReceipt.objects.create(
        website=website,
        client_name_manual=tx.full_name or (tx.email.split('@')[0] if tx.email else 'Customer'),
        client_email_manual=tx.email or '',
        client_phone_manual=tx.phone or '',
        project_label=_title_for(tx),
        kind='full',
        title=_title_for(tx),
        description=tx.description or '',
        line_items=[{
            'desc': tx.description or _title_for(tx),
            'qty': 1,
            'unit_price': float(amount),
            'amount': float(amount),
        }],
        currency=tx.currency or 'TZS',
        amount_paid=amount,
        payment_method=_map_method(tx.payment_method),
        payment_reference=ref,
        payment_date=timezone.now().date(),
        received_by='JamiiTek (Pesapal)',
        is_published=True,
    )
    return receipt


def render_pdf(receipt):
    """Rudisha bytes za PDF ya risiti, au None ikishindikana."""
    try:
        from apps.receipt_graphics import qr_data_uri, barcode_data_uri
        ctx = {
            'r': receipt,
            'pdf': True,
            'qr': qr_data_uri(receipt.verify_url),
            'barcode': barcode_data_uri(receipt.barcode_value),
        }
        html = render_to_string('receipts/receipt_doc.html', ctx)
        from xhtml2pdf import pisa
        buf = BytesIO()
        status = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
        if status.err:
            return None
        return buf.getvalue()
    except Exception:
        logger.exception('Pesapal: kutengeneza PDF ya risiti kumeshindikana')
        return None


def _email_context(tx, receipt):
    return {
        'subject': f'Payment Receipt — {receipt.receipt_number}',
        'customer_name': tx.first_name or receipt.client_name_manual or 'there',
        'receipt_number': receipt.receipt_number,
        'service': _title_for(tx),
        'currency': tx.currency or 'TZS',
        'amount': tx.amount,
        'payment_method': receipt.get_payment_method_display(),
        'reference': receipt.payment_reference,
        'payment_date': receipt.payment_date,
        'verify_url': getattr(receipt, 'verify_url', ''),
    }


def email_receipt(tx, receipt, pdf_bytes=None):
    """
    Tuma risiti kwa mteja (na nakala kwa mmiliki) kwa template nzuri ya HTML,
    na plain-text fallback + PDF ambatanisho. Best-effort.
    """
    from django.utils.html import strip_tags

    to = tx.email or OWNER_EMAIL
    bcc = [OWNER_EMAIL] if (tx.email and OWNER_EMAIL and tx.email != OWNER_EMAIL) else None
    ctx = _email_context(tx, receipt)

    try:
        html_body = render_to_string('emails/payment_receipt.html', ctx)
        plain_body = strip_tags(html_body)
        msg = EmailMultiAlternatives(
            subject=f'Payment Receipt — {receipt.receipt_number} | JamiiTek',
            body=plain_body,
            from_email=FROM_EMAIL,
            to=[to],
            bcc=bcc,
        )
        msg.attach_alternative(html_body, 'text/html')
        if pdf_bytes:
            msg.attach(f'{receipt.receipt_number}.pdf', pdf_bytes, 'application/pdf')
        msg.send(fail_silently=True)
        logger.info('Pesapal: risiti %s imetumwa kwa %s', receipt.receipt_number, to)
        return True
    except Exception:
        logger.exception('Pesapal: kutuma email ya risiti kumeshindikana')
        return False


def issue_receipt(tx):
    """
    Njia moja: tengeneza risiti, PDF, na tuma email. Inaitwa baada ya
    fulfillment kukamilika (kwenye on_commit). Haitupi exception.
    """
    try:
        receipt = create_receipt(tx)
    except Exception:
        logger.exception('Pesapal: kutengeneza risiti kumeshindikana kwa %s', tx.merchant_reference)
        return
    pdf = render_pdf(receipt)
    email_receipt(tx, receipt, pdf)
