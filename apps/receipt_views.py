# apps/receipt_views.py
"""
Development receipts: staff builder + client download + public link.

Follows the same shape as docs_views / proposal_views so it drops straight
into the existing /manage/ UI.
"""

from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .models import ManagedWebsite, DevelopmentReceipt, Client
from .management_views import staff_member_required
from .client_portal_views import client_required
from .receipt_graphics import qr_data_uri, barcode_data_uri


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _render_pdf(request, template, ctx, filename):
    """Same approach used for contracts/proposals — xhtml2pdf, no system deps."""
    html = render(request, template, ctx).content.decode('utf-8')
    try:
        from xhtml2pdf import pisa
        buf = BytesIO()
        status = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
        if status.err:
            raise Exception('PDF error')
        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
    except Exception:
        # Never leave the user with nothing — fall back to the printable page
        return HttpResponse(html)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _doc_ctx(receipt, pdf=True):
    """Everything the receipt document needs, including generated graphics."""
    return {
        'r': receipt,
        'pdf': pdf,
        'qr': qr_data_uri(receipt.verify_url),
        'barcode': barcode_data_uri(receipt.barcode_value),
    }


def _dec(value, default=None):
    if value in (None, ''):
        return default
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return default


def _parse_line_items(request):
    """
    The form posts parallel arrays:
        item_desc[]  item_qty[]  item_price[]
    Amount is always recomputed here — never trusted from the browser.
    """
    descs = request.POST.getlist('item_desc')
    qtys = request.POST.getlist('item_qty')
    prices = request.POST.getlist('item_price')

    items = []
    for i, desc in enumerate(descs):
        desc = (desc or '').strip()
        if not desc:
            continue
        qty = _dec(qtys[i] if i < len(qtys) else 1, Decimal('1')) or Decimal('1')
        price = _dec(prices[i] if i < len(prices) else 0, Decimal('0')) or Decimal('0')
        items.append({
            'desc': desc,
            'qty': float(qty),
            'unit_price': float(price),
            'amount': float(qty * price),
        })
    return items


def _apply_post(receipt, request):
    receipt.kind = request.POST.get('kind', 'full')
    receipt.title = request.POST.get('title', '').strip() or 'Website Development Payment'
    receipt.description = request.POST.get('description', '').strip()
    receipt.line_items = _parse_line_items(request)
    receipt.currency = request.POST.get('currency', 'TZS').strip() or 'TZS'
    receipt.tax_percent = _dec(request.POST.get('tax_percent'))
    receipt.discount_amount = _dec(request.POST.get('discount_amount'))
    receipt.amount_paid = _dec(request.POST.get('amount_paid'), Decimal('0'))
    receipt.payment_method = request.POST.get('payment_method', 'mpesa')
    receipt.payment_reference = request.POST.get('payment_reference', '').strip()
    receipt.received_by = request.POST.get('received_by', '').strip() or 'W. Chipindi'
    receipt.notes = request.POST.get('notes', '').strip()
    receipt.is_published = bool(request.POST.get('is_published'))
    receipt.require_signature = bool(request.POST.get('require_signature'))

    # Website ni hiari — hizi zinatumika pale haipo
    receipt.project_label = request.POST.get('project_label', '').strip()
    cid = (request.POST.get('client') or '').strip()
    receipt.client = get_object_or_404(Client, pk=cid) if cid else None
    receipt.client_name_manual = request.POST.get('client_name_manual', '').strip()
    receipt.client_company_manual = request.POST.get('client_company_manual', '').strip()
    receipt.client_email_manual = request.POST.get('client_email_manual', '').strip()
    receipt.client_phone_manual = request.POST.get('client_phone_manual', '').strip()

    pay_date = parse_date((request.POST.get('payment_date') or '').strip())
    if pay_date:
        receipt.payment_date = pay_date
    return receipt


# ══════════════════════════════════════════════════════════════
# STAFF — /manage/receipts/
# ══════════════════════════════════════════════════════════════
@staff_member_required
def receipt_list(request):
    receipts = DevelopmentReceipt.objects.select_related('website__client', 'client')

    q = request.GET.get('q', '').strip()
    if q:
        receipts = receipts.filter(
            Q(receipt_number__icontains=q) |
            Q(website__name__icontains=q) |
            Q(website__client__name__icontains=q) |
            Q(client_name_manual__icontains=q) |
            Q(client_company_manual__icontains=q) |
            Q(project_label__icontains=q) |
            Q(payment_reference__icontains=q)
        )

    website_id = request.GET.get('website')
    if website_id:
        receipts = receipts.filter(website_id=website_id)

    total = receipts.aggregate(t=Sum('amount_paid'))['t'] or 0

    return render(request, 'management/receipt_list.html', {
        'title': 'Development Receipts',
        'receipts': receipts,
        'websites': ManagedWebsite.objects.select_related('client').order_by('name'),
        'clients': Client.objects.order_by('name'),
        'q': q,
        'website_id': website_id,
        'total_received': total,
    })


@staff_member_required
def receipt_new(request, website_pk=None):
    website = None
    if website_pk:
        website = get_object_or_404(ManagedWebsite, pk=website_pk)

    if request.method == 'POST':
        target_pk = request.POST.get('website') or website_pk
        receipt = DevelopmentReceipt()
        if target_pk:
            receipt.website = get_object_or_404(ManagedWebsite, pk=target_pk)
        _apply_post(receipt, request)

        # Bila website, angalau jina la mteja au la mradi linahitajika
        if not receipt.website_id and not (
                receipt.client_name_manual or receipt.client_company_manual
                or receipt.project_label):
            messages.error(
                request,
                'Choose a website, or fill in the client name or project name.')
            return redirect('receipt_new')

        receipt.save()
        messages.success(request, f'{receipt.receipt_number} created.')
        return redirect('receipt_edit', pk=receipt.pk)

    # Sensible starting point so the form isn't empty
    draft = DevelopmentReceipt(
        website=website,
        payment_date=timezone.now().date(),
        line_items=[{
            'desc': f'Website design & development — {website.name}' if website
                    else 'Website design & development',
            'qty': 1, 'unit_price': 0, 'amount': 0,
        }],
    )

    return render(request, 'management/receipt_form.html', {
        'title': 'New Receipt',
        'receipt': draft,
        'website': website,
        'websites': ManagedWebsite.objects.select_related('client').order_by('name'),
        'clients': Client.objects.order_by('name'),
        'is_new': True,
    })


@staff_member_required
def receipt_edit(request, pk):
    receipt = get_object_or_404(
        DevelopmentReceipt.objects.select_related('website', 'website__client'), pk=pk)

    if request.method == 'POST':
        new_site = (request.POST.get('website') or '').strip()
        if not new_site:
            receipt.website = None
        elif str(new_site) != str(receipt.website_id):
            receipt.website = get_object_or_404(ManagedWebsite, pk=new_site)
        _apply_post(receipt, request)
        receipt.save()
        messages.success(request, f'{receipt.receipt_number} saved.')
        return redirect('receipt_edit', pk=receipt.pk)

    return render(request, 'management/receipt_form.html', {
        'title': receipt.receipt_number or 'Receipt',
        'receipt': receipt,
        'website': receipt.website,
        'websites': ManagedWebsite.objects.select_related('client').order_by('name'),
        'clients': Client.objects.order_by('name'),
        'is_new': False,
    })


@staff_member_required
@require_POST
def receipt_delete(request, pk):
    receipt = get_object_or_404(DevelopmentReceipt, pk=pk)
    number = receipt.receipt_number
    receipt.delete()
    messages.success(request, f'{number} deleted.')
    return redirect('receipt_list')


@staff_member_required
def receipt_pdf_staff(request, pk):
    receipt = get_object_or_404(
        DevelopmentReceipt.objects.select_related('website', 'website__client'), pk=pk)
    return _render_pdf(request, 'receipts/receipt_doc.html',
                       _doc_ctx(receipt), receipt.filename)


# ══════════════════════════════════════════════════════════════
# CLIENT PORTAL
# ══════════════════════════════════════════════════════════════
def _client_receipt(request, pk):
    # Risiti inaonekana kwa mteja ikiwa imeambatanishwa na tovuti yake AU
    # naye moja kwa moja. Awali ilikuwa website__client pekee, kwa hiyo
    # risiti ya mradi usio na tovuti haikuonekana kabisa portal.
    return get_object_or_404(
        DevelopmentReceipt.objects.select_related('website', 'website__client', 'client')
        .filter(Q(website__client=request.client_profile)
                | Q(client=request.client_profile)),
        pk=pk, is_published=True)


@client_required
def portal_receipt_pdf(request, pk):
    """Download. Scoped to the logged-in client so nobody can guess IDs."""
    receipt = _client_receipt(request, pk)

    # An unsigned receipt goes through the signature step first.
    if receipt.needs_signature:
        return redirect('portal_receipt_sign', pk=receipt.pk)

    return _render_pdf(request, 'receipts/receipt_doc.html',
                       _doc_ctx(receipt), receipt.filename)


@client_required
def portal_receipt_sign(request, pk):
    """Client draws or types their signature, then the PDF downloads."""
    receipt = _client_receipt(request, pk)

    if request.method == 'POST':
        drawn = (request.POST.get('signature_data') or '').strip()
        typed = (request.POST.get('signature_name') or '').strip()

        if not drawn and not typed:
            messages.error(request, 'Please sign or type your name before continuing.')
            return redirect('portal_receipt_sign', pk=receipt.pk)

        # Only accept a PNG data URI, and cap the size so nobody can post a novel.
        if drawn.startswith('data:image/png;base64,') and len(drawn) <= 400_000:
            receipt.signature_data = drawn
        receipt.signature_name = typed[:160]
        receipt.signed_at = timezone.now()
        receipt.signed_ip = _client_ip(request)
        receipt.save(update_fields=[
            'signature_data', 'signature_name', 'signed_at', 'signed_ip', 'updated_at'])

        return redirect('portal_receipt_pdf', pk=receipt.pk)

    return render(request, 'portal/receipt_sign.html', {
        'title': f'Sign {receipt.receipt_number}',
        'client': request.client_profile,
        'r': receipt,
    })


@client_required
def portal_receipt_list(request):
    receipts = DevelopmentReceipt.objects.filter(
        Q(website__client=request.client_profile)
        | Q(client=request.client_profile),
        is_published=True,
    ).select_related('website', 'client').distinct()
    return render(request, 'portal/receipt_list.html', {
        'title': 'My Receipts',
        'client': request.client_profile,
        'receipts': receipts,
        'total_paid': receipts.aggregate(t=Sum('amount_paid'))['t'] or 0,
    })


# ══════════════════════════════════════════════════════════════
# PUBLIC LINK (shareable, unguessable token)
# ══════════════════════════════════════════════════════════════
def receipt_public(request, token):
    """
    A receipt link may be shared by WhatsApp and outlive the receipt itself.
    A deleted or withdrawn one shows the verification page rather than a 404 —
    the person holding the link deserves an explanation, not a stack trace.
    """
    receipt = DevelopmentReceipt.objects.select_related(
        'website', 'website__client').filter(token=token).first()

    if receipt is None or (not receipt.is_published and not request.user.is_staff):
        return render(request, 'receipts/receipt_verify.html',
                      {'r': receipt, 'valid': False}, status=404)

    if request.GET.get('pdf'):
        return _render_pdf(request, 'receipts/receipt_doc.html',
                           _doc_ctx(receipt), receipt.filename)

    return render(request, 'receipts/receipt_doc.html', _doc_ctx(receipt, pdf=False))


def receipt_verify(request, token):
    """
    Where the QR code points. Confirms a receipt is genuine without
    requiring a login — the token itself is the proof.
    """
    receipt = DevelopmentReceipt.objects.select_related(
        'website', 'website__client').filter(token=token).first()

    valid = receipt is not None and receipt.is_published
    return render(request, 'receipts/receipt_verify.html',
                  {'r': receipt, 'valid': valid},
                  status=200 if valid else 404)