"""Company Profile + Invoice: public views, PDF, staff builders, AI endpoints."""
import json
from datetime import datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, Http404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect

from .models import CompanyProfile, Invoice
from .management_views import staff_member_required


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _lang(request):
    lang = request.GET.get('lang', 'en')
    return lang if lang in ('en', 'sw') else 'en'


PDF_CACHE_SECONDS = 60 * 60 * 24


def _pdf_bytes(html):
    """
    HTML → PDF (xhtml2pdf), ikihifadhiwa kwenye cache kwa hash ya HTML yenyewe.
    Ankara ikibadilika (kiasi, malipo, lugha…) HTML inabadilika → hash mpya → PDF mpya;
    isipobadilika, PDF ileile inatolewa papo hapo bila kuitengeneza tena.
    """
    import hashlib
    from django.core.cache import cache
    key = 'pdf:' + hashlib.sha1(html.encode('utf-8')).hexdigest()
    try:
        data = cache.get(key)
    except Exception:
        data = None
    if data:
        return data
    from xhtml2pdf import pisa
    from io import BytesIO
    buf = BytesIO()
    status = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
    if status.err:
        raise Exception('PDF error')
    data = buf.getvalue()
    try:
        cache.set(key, data, PDF_CACHE_SECONDS)
    except Exception:
        pass
    return data


def _render_pdf(request, template, ctx, filename):
    from django.template.loader import render_to_string
    html = render_to_string(template, ctx, request=request)
    try:
        resp = HttpResponse(_pdf_bytes(html), content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
    except Exception:
        return HttpResponse(html)


# ============================================================
# COMPANY PROFILE
# ============================================================

def company_profile_view(request):
    """Ukurasa wa umma wa company profile."""
    profile = CompanyProfile.objects.filter(is_active=True).first()
    if profile is None:
        raise Http404('No active company profile')
    return render(request, 'docs/profile_view.html',
                  {'profile': profile, 'lang': _lang(request)})


def company_profile_pdf(request):
    profile = CompanyProfile.objects.filter(is_active=True).first()
    if profile is None:
        raise Http404('No active company profile')
    lang = _lang(request)
    fname = f'{profile.short_name}-company-profile-{lang}.pdf'.replace(' ', '_')
    return _render_pdf(request, 'docs/profile_pdf.html',
                       {'profile': profile, 'lang': lang}, fname)


@staff_member_required
def profile_builder(request):
    """Editor ya company profile (staff)."""
    profile = CompanyProfile.objects.filter(is_active=True).first()
    if profile is None:
        profile = CompanyProfile.objects.create()
    if request.method == 'POST':
        _save_profile_form(request, profile)
        return redirect('profile_builder')
    return render(request, 'docs/profile_edit.html', {
        'profile': profile,
        'services_json': json.dumps(profile.services),
        'why_json': json.dumps(profile.why_us),
        'projects_json': json.dumps(profile.projects),
        'facts_json': json.dumps(profile.facts),
        'sections_json': json.dumps(profile.sections),
    })


def _save_profile_form(request, p):
    d = request.POST
    for f in ('company_name', 'short_name', 'tagline_en', 'tagline_sw',
              'subtitle_en', 'subtitle_sw', 'period', 'about_en', 'about_sw',
              'mission_en', 'mission_sw', 'vision_en', 'vision_sw',
              'pricing_note_en', 'pricing_note_sw', 'email', 'phone',
              'website', 'address', 'logo_url'):
        if f in d:
            setattr(p, f, d.get(f, '').strip())
    for field, default in (('services', []), ('why_us', []), ('projects', []),
                           ('facts', []), ('sections', [])):
        raw = d.get(field, '')
        try:
            setattr(p, field, json.loads(raw) if raw else default)
        except (json.JSONDecodeError, TypeError):
            pass
    p.is_active = True
    p.save()


@staff_member_required
@require_POST
def profile_ai_assist(request):
    from apps import docs_ai
    ok, result = docs_ai.assist_field(
        request.POST.get('field_type', 'about'),
        request.POST.get('context', ''),
        request.POST.get('language', 'en'),
        kind='profile')
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)
    return JsonResponse({'ok': True, 'text': result})


@staff_member_required
@require_POST
def profile_ai_full(request):
    from apps import docs_ai
    profile = CompanyProfile.objects.filter(is_active=True).first()
    if profile is None:
        return JsonResponse({'ok': False, 'error': 'No profile'}, status=404)
    ok, result = docs_ai.generate_profile({
        'company_name': profile.company_name,
        'tagline': profile.tagline_en,
        'address': profile.address,
    })
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)
    for k, v in result.items():
        setattr(profile, k, v)
    profile.save()
    return JsonResponse({'ok': True, **result})


# ============================================================
# INVOICES
# ============================================================

def _site_url(path):
    """Link za kumtumia mteja zitumie domain rasmi, si host ya ombi."""
    from django.conf import settings
    return (getattr(settings, 'SITE_URL', '') or 'https://www.jamiitek.com').rstrip('/') + path


def _default_payment_methods():
    return [dict(m) for m in Invoice.DEFAULT_PAYMENT_METHODS]


def _invoice_qr(request, invoice):
    """QR (SVG data URI) inayompeleka mteja kwenye ankara yake mtandaoni."""
    try:
        import base64
        import qrcode
        import qrcode.image.svg
        url = _site_url(invoice.public_url)
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
        return 'data:image/svg+xml;base64,' + base64.b64encode(img.to_string()).decode()
    except Exception:
        return ''


def _invoice_qr_png(request, invoice):
    """xhtml2pdf haisomi SVG — PDF inatumia PNG."""
    try:
        import base64
        from io import BytesIO
        import qrcode
        buf = BytesIO()
        qrcode.make(_site_url(invoice.public_url), box_size=6, border=1).save(buf, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ''


def _invoice_pdf_ctx(request, invoice, base=None):
    ctx = dict(base) if base is not None else _public_ctx(request, invoice)
    ctx['flash'] = []          # PDF haionyeshi ujumbe — usiyale messages za ukurasa
    ctx['qr'] = _invoice_qr_png(request, invoice)
    return ctx


def _warm_invoice_pdf(request, invoice, page_ctx):
    """
    Mteja akifungua ankara, PDF yake inaandaliwa nyuma (thread) na kuwekwa kwenye
    cache — akibonyeza "PDF" inapakuliwa papo hapo badala ya kusubiri xhtml2pdf.
    """
    from django.conf import settings
    if not getattr(settings, 'PDF_PREWARM', True):
        return
    import threading
    from django.db import connection
    from django.template.loader import render_to_string
    ctx = _invoice_pdf_ctx(request, invoice, page_ctx)
    ctx.pop('preview', None)

    def work():
        try:
            _pdf_bytes(render_to_string('docs/invoice_pdf.html', ctx))
        except Exception:
            pass
        finally:
            connection.close()
    threading.Thread(target=work, daemon=True).start()


def _public_ctx(request, invoice):
    from apps.contact import contact
    from django.contrib.messages import get_messages
    c = contact()
    # Ankara na risiti zote ni kwa Kiingereza (uamuzi wa mmiliki) — ?lang=sw haibadilishi kitu
    return {'invoice': invoice, 'lang': 'en', 'contact': c,
            'items': invoice.items, 'history': invoice.payment_history,
            'flash': list(get_messages(request))}


def invoice_view(request, token):
    invoice = get_object_or_404(Invoice, token=token)
    if invoice.status in ('draft', 'cancelled'):
        is_staff = request.user.is_authenticated and request.user.is_staff
        if not is_staff:
            return render(request, 'docs/invoice_unavailable.html',
                          {'invoice': invoice}, status=404)
    # Mfanyakazi akifungua "Preview" isihesabike kama mteja ameiona
    if invoice.status == 'sent' and not (request.user.is_authenticated and request.user.is_staff):
        invoice.status = 'viewed'
        invoice.viewed_at = timezone.now()
        invoice.save(update_fields=['status', 'viewed_at'])
    ctx = _public_ctx(request, invoice)
    ctx['qr'] = _invoice_qr(request, invoice)
    ctx['preview'] = invoice.status in ('draft', 'cancelled')
    proofs = list(invoice.proofs.all()[:5])
    ctx['proofs'] = proofs
    ctx['pending_proof'] = any(p.status == 'pending' for p in proofs)
    from apps.renewals import pay_ahead_options
    ctx['pay_ahead'] = pay_ahead_options(invoice)
    _warm_invoice_pdf(request, invoice, ctx)
    return render(request, 'docs/invoice_view.html', ctx)


def invoice_pdf(request, token):
    invoice = get_object_or_404(Invoice, token=token)
    is_staff = request.user.is_authenticated and request.user.is_staff
    if invoice.status in ('draft', 'cancelled') and not is_staff:
        return HttpResponse('Not available', status=404)
    ctx = _invoice_pdf_ctx(request, invoice)
    fname = f'{invoice.invoice_number or "invoice"}-{ctx["lang"]}.pdf'.replace(' ', '_')
    return _render_pdf(request, 'docs/invoice_pdf.html', ctx, fname)


INVOICE_FILTERS = (
    ('all', 'All'), ('open', 'Unpaid'), ('overdue', 'Overdue'),
    ('partial', 'Part-paid'), ('paid', 'Paid'), ('draft', 'Drafts'), ('cancelled', 'Cancelled'),
)


@staff_member_required
def invoice_list(request):
    from django.db.models import Q

    q = request.GET.get('q', '').strip()
    show = request.GET.get('show', 'all')
    if show not in dict(INVOICE_FILTERS):
        show = 'all'

    from django.db.models import Count
    qs = Invoice.objects.select_related('client').annotate(
        pending_proofs=Count('proofs', filter=Q(proofs__status='pending')))
    if q:
        qs = qs.filter(Q(invoice_number__icontains=q) | Q(client_name__icontains=q)
                       | Q(client_company__icontains=q) | Q(client_email__icontains=q)
                       | Q(title__icontains=q) | Q(project_name__icontains=q)
                       | Q(client__name__icontains=q))
    every = list(qs[:500])

    # Takwimu kwa kila sarafu — TZS na USD hazijumlishwi pamoja
    by_cur = {}
    for i in every:
        cur = i.currency or 'TZS'
        row = by_cur.setdefault(cur, {'currency': cur, 'outstanding': 0, 'overdue': 0, 'collected': 0})
        if i.status != 'cancelled':
            row['collected'] += i.paid_total
        if i.is_open:
            row['outstanding'] += i.balance_due
            if i.is_overdue:
                row['overdue'] += i.balance_due
    totals = sorted(by_cur.values(), key=lambda r: (r['currency'] != 'TZS', r['currency']))

    counts = {key: 0 for key, _ in INVOICE_FILTERS}
    for i in every:
        st = i.display_status
        counts['all'] += 1
        if i.is_open:
            counts['open'] += 1
        if st in counts and st != 'all':
            counts[st] += 1

    def keep(i):
        st = i.display_status
        return (show == 'all' or (show == 'open' and i.is_open) or st == show)
    invoices = [i for i in every if keep(i)]

    return render(request, 'docs/invoice_list.html', {
        'invoices': invoices, 'totals': totals, 'counts': counts, 'q': q, 'show': show,
        'filters': [(k, label, counts[k]) for k, label in INVOICE_FILTERS],
        'unpaid': counts['open'], 'paid_count': counts['paid'], 'overdue_count': counts['overdue'],
    })


@staff_member_required
def invoice_new(request):
    from datetime import timedelta
    today = timezone.localdate()
    inv = Invoice.objects.create(
        title='Invoice',
        issue_date=today,
        due_date=today + timedelta(days=14),
        payment_terms='Payment due within 14 days of the invoice date.',
        provider_rep=request.user.get_full_name() or request.user.username or 'W. Chipindi',
        payment_methods=_default_payment_methods(),
    )
    return redirect('invoice_edit', pk=inv.pk)


@staff_member_required
def _pay_ahead(inv):
    from apps.renewals import pay_ahead_options
    try:
        return pay_ahead_options(inv)
    except Exception:
        return []


def invoice_edit(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        errors = _save_invoice_form(request, inv)
        if request.headers.get('x-requested-with') == 'fetch':
            return JsonResponse({
                'ok': not errors, 'errors': errors, 'status': inv.status,
                'display_status': inv.display_status,
                'invoice_number': inv.invoice_number,
                'grand_total': inv.grand_total, 'balance_due': inv.balance_due,
            }, status=200 if not errors else 400)
        return redirect('invoice_edit', pk=inv.pk)
    from urllib.parse import quote
    link = _site_url(inv.public_url)
    phone = ''.join(ch for ch in (inv.client_phone or (inv.client.phone if inv.client else '') or '')
                    if ch.isdigit())
    if phone.startswith('0') and len(phone) == 10:
        phone = '255' + phone[1:]
    wa_text = (f"Habari {inv.display_client},\n\nAnkara yako {inv.invoice_number} ya "
               f"{inv.currency} {inv.balance_due:,.0f} kutoka JamiiTek iko tayari:\n{link}\n\n"
               f"Unaweza kuiona, kuipakua (PDF) na kulipa hapo. Asante!")
    proofs = list(inv.proofs.select_related('reviewed_by'))
    return render(request, 'docs/invoice_edit.html', {
        'invoice': inv,
        'proofs': proofs,
        'pending_count': sum(1 for p in proofs if p.status == 'pending'),
        'renewals': list(inv.renewals.all()),
        'month_choices': (1, 2, 3, 4, 6, 12),
        'month_totals': {1: inv.balance_due, **{o['months']: float(o['total']) for o in _pay_ahead(inv)}},
        'items_json': json.dumps(inv.items),
        'methods_json': json.dumps(inv.payment_methods),
        'history': inv.payment_history,
        'public_link': link,
        'wa_link': f"https://wa.me/{phone}?text={quote(wa_text)}" if phone else
                   f"https://wa.me/?text={quote(wa_text)}",
        'statuses': [s for s in Invoice.STATUS if s[0] != 'overdue'],
        'default_methods_json': json.dumps(Invoice.DEFAULT_PAYMENT_METHODS),
    })


def _decimal(raw, label, errors, minimum=0, maximum=None):
    """'' → None. Kiasi kisicho sahihi → kosa (si 500)."""
    from decimal import Decimal, InvalidOperation
    raw = (raw or '').replace(',', '').strip()
    if not raw:
        return None
    try:
        val = Decimal(raw)
    except InvalidOperation:
        errors.append(f'{label}: "{raw}" is not a number')
        return False
    if val < minimum or (maximum is not None and val > maximum):
        errors.append(f'{label} must be between {minimum} and {maximum}' if maximum is not None
                      else f'{label} cannot be negative')
        return False
    return val.quantize(Decimal('0.01'))


def _clean_items(raw_items):
    """Kiasi kinahesabiwa upya upande wa server: qty × bei."""
    rows = []
    for it in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(it, dict):
            continue
        desc = str(it.get('desc') or it.get('description') or '').strip()[:600]
        qty = Invoice._num(it.get('qty')) if str(it.get('qty', '')).strip() else 1
        price = Invoice._num(it.get('unit_price'))
        amount = Invoice._num(it.get('amount'))
        if qty and price:
            amount = qty * price
        if not desc and not amount:
            continue
        qty = int(qty) if qty == int(qty) else round(qty, 2)
        rows.append({'desc': desc, 'qty': qty, 'unit_price': round(price, 2),
                     'amount': round(amount, 2)})
    return rows


def _save_invoice_form(request, inv):
    """Hifadhi fomu. Rudisha orodha ya makosa (tupu = sawa)."""
    d = request.POST
    errors = []
    for f in ('client_name', 'client_email', 'client_company', 'client_phone',
              'client_address', 'title', 'project_name', 'payment_terms',
              'notes_en', 'notes_sw', 'provider_name', 'provider_rep',
              'logo_url', 'paid_reference'):
        if f in d:
            setattr(inv, f, d.get(f, '').strip()[:Invoice._meta.get_field(f).max_length or None])

    if 'client_email' in d and inv.client_email:
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        try:
            validate_email(inv.client_email)
        except ValidationError:
            errors.append(f'Client email "{inv.client_email}" is not valid')
            inv.client_email = Invoice.objects.filter(pk=inv.pk).values_list('client_email', flat=True).first() or ''

    number = d.get('invoice_number', '').strip()[:40]
    if number and number != inv.invoice_number:
        if Invoice.objects.filter(invoice_number__iexact=number).exclude(pk=inv.pk).exists():
            errors.append(f'Invoice number {number} is already used by another invoice')
        else:
            inv.invoice_number = number

    if 'currency' in d:
        inv.currency = (d.get('currency', '').strip() or 'TZS')[:8]
    itype = d.get('invoice_type')
    if itype in dict(Invoice.TYPES):
        inv.invoice_type = itype
    mode = d.get('payment_mode')
    if mode in dict(Invoice.PAYMENT_MODES):
        inv.payment_mode = mode

    # amount_paid haibadilishwi hapa: malipo yanarekodiwa kupitia "Record payment"
    # ili historia na jumla visitofautiane.
    for f, label, maximum in (('tax_percent', 'VAT %', 100), ('discount_amount', 'Discount', None)):
        if f in d:
            val = _decimal(d.get(f), label, errors, maximum=maximum)
            if val is not False:
                setattr(inv, f, val)

    for f in ('issue_date', 'due_date'):
        if f in d:
            val = d.get(f, '').strip()
            if not val:
                setattr(inv, f, None)
                continue
            try:
                setattr(inv, f, datetime.strptime(val, '%Y-%m-%d').date())
            except ValueError:
                errors.append(f'{f.replace("_", " ").title()} is not a valid date')
    if inv.issue_date and inv.due_date and inv.due_date < inv.issue_date:
        errors.append('Due date is before the issue date')

    for field in ('line_items', 'payment_methods'):
        raw = d.get(field)
        if raw is None:
            continue
        try:
            data = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            errors.append(f'Could not read {field.replace("_", " ")}')
            continue
        if field == 'line_items':
            inv.line_items = _clean_items(data)
        else:
            inv.payment_methods = [
                {'method': str(m.get('method', '')).strip()[:60], 'details': str(m.get('details', '')).strip()[:300]}
                for m in data if isinstance(m, dict) and (m.get('method') or m.get('details'))]

    if inv.discount_amount and inv.discount_amount > inv.subtotal:
        errors.append('Discount is larger than the subtotal')

    status = d.get('status')
    if status in ('sent', 'viewed', 'partial', 'paid') and inv.grand_total <= 0:
        # Ankara ya TZS 0 haina maana kwa mteja — ibaki ilivyo hadi vitu viongezwe
        errors.append('Add at least one item with a price — the invoice total is 0')
        if inv.status == 'draft':
            status = 'draft'
    if status in dict(Invoice.STATUS) and status != 'overdue':
        if status in ('sent', 'viewed') and not inv.sent_at:
            inv.sent_at = timezone.now()
        if status == 'paid' and inv.balance_due > 0 and inv.grand_total > 0:
            # "Paid" kwenye dropdown = salio lote limepokelewa: liandikwe kwenye historia
            if inv.status == 'cancelled':
                inv.status = 'sent'
            inv.record_payment(inv.balance_due, method='Manual', reference=inv.paid_reference,
                               by=request.user.get_username(), source='manual')
        else:
            inv.status = status
    inv.sync_payment_status()
    inv.save()
    return errors


@staff_member_required
@require_POST
def invoice_mark_paid(request, pk):
    """Rekodi malipo yaliyopokelewa (yanaongezwa — hayafuti ya awali)."""
    inv = get_object_or_404(Invoice, pk=pk)
    if inv.status == 'cancelled':
        return JsonResponse({'ok': False, 'error': 'This invoice is cancelled'}, status=400)
    if inv.grand_total <= 0:
        return JsonResponse({'ok': False, 'error': 'Add the invoice items first — the total is 0'}, status=400)
    raw = request.POST.get('amount', '').replace(',', '').strip()
    amount = raw or inv.balance_due
    try:
        if float(amount) > inv.balance_due + 0.005:
            return JsonResponse({'ok': False, 'error': (
                f'That is more than the balance due ({inv.currency} {inv.balance_due:,.0f})')}, status=400)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Invalid amount'}, status=400)
    try:
        inv.record_payment(amount,
                           method=request.POST.get('method', '').strip() or 'Manual',
                           reference=request.POST.get('reference', '').strip(),
                           by=request.user.get_username(), source='manual')
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    inv.save()
    # Risiti (inahitaji mteja athibitishe kwanza) + link ya kuthibitisha kwa email/WhatsApp,
    # na ankara ya renewal ikilipwa yote: tarehe za hosting/domain zinasogezwa mbele.
    from apps.renewals import after_payment
    done = after_payment(inv, inv.payments[-1]['amount'], method=request.POST.get('method', ''),
                         reference=request.POST.get('reference', '').strip(),
                         by=request.user.get_full_name() or request.user.get_username(), user=request.user)
    r = done['receipt']
    return JsonResponse({'ok': True, 'status': inv.status,
                         'balance_due': inv.balance_due, 'paid_total': inv.paid_total,
                         'receipt': r.receipt_number if r else '',
                         'receipt_sent': {'email': done['email'], 'whatsapp': done['whatsapp']},
                         'renewed': done['renewed']})


@staff_member_required
@require_POST
def invoice_remove_payment(request, pk, index):
    """Futa malipo yaliyorekodiwa kimakosa (si ya Pesapal)."""
    from decimal import Decimal
    inv = get_object_or_404(Invoice, pk=pk)
    payments = list(inv.payments or [])
    if not (0 <= index < len(payments)) or payments[index].get('source') == 'pesapal':
        return JsonResponse({'ok': False, 'error': 'Payment not found or cannot be removed'}, status=400)
    removed = payments.pop(index)
    inv.payments = payments
    inv.amount_paid = max(Decimal('0'), Decimal(str(inv.amount_paid or 0))
                          - Decimal(str(removed.get('amount') or 0))) or None
    if inv.status == 'paid':
        inv.status = 'sent'
    inv.sync_payment_status()
    inv.save()
    return JsonResponse({'ok': True, 'status': inv.status, 'balance_due': inv.balance_due})


@staff_member_required
@require_POST
def invoice_clear_earlier_payment(request, pk):
    """Ondoa kiasi cha 'Earlier payment' (kilichowekwa kwenye 'Amount paid' ya zamani
    bila historia) — mfano kiasi cha deposit kiliandikwa kama kimelipwa."""
    from decimal import Decimal
    inv = get_object_or_404(Invoice, pk=pk)
    earlier = Decimal(str(inv.unlogged_paid))
    if earlier <= 0:
        return JsonResponse({'ok': False, 'error': 'Nothing to remove'}, status=400)
    inv.amount_paid = (Decimal(str(inv.amount_paid or 0)) - earlier) or None
    if inv.status == 'paid':
        inv.status = 'sent'
    inv.sync_payment_status()
    inv.save()
    return JsonResponse({'ok': True, 'status': inv.status, 'balance_due': inv.balance_due})


@staff_member_required
@require_POST
def invoice_send(request, pk):
    """Tuma ankara kwa email ya mteja (link + muhtasari), na uiweke 'sent'."""
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    inv = get_object_or_404(Invoice, pk=pk)
    to = (request.POST.get('to') or inv.display_email or '').strip()
    if not to:
        return JsonResponse({'ok': False, 'error': 'Add the client email first'}, status=400)
    if inv.status == 'cancelled':
        return JsonResponse({'ok': False, 'error': 'This invoice is cancelled'}, status=400)
    if not inv.items or inv.grand_total <= 0:
        return JsonResponse({'ok': False, 'error': 'Add at least one item with a price first'}, status=400)
    if inv.status == 'draft':
        inv.status = 'sent'
    inv.sent_at = inv.sent_at or timezone.now()
    inv.save(update_fields=['status', 'sent_at'])

    lang = 'en'           # email zote za wateja ni kwa Kiingereza (ukurasa wa ankara bado una Kiswahili ukitaka)
    ctx = {'invoice': inv, 'items': inv.items, 'lang': lang,
           'link': _site_url(inv.public_url) + f'?lang={lang}',
           'pdf': _site_url(f'{inv.public_url}pdf/') + f'?lang={lang}'}
    subject = (f'Ankara {inv.invoice_number} — {inv.currency} {inv.balance_due:,.0f}' if lang == 'sw'
               else f'Invoice {inv.invoice_number} — {inv.currency} {inv.balance_due:,.0f}')
    msg = EmailMultiAlternatives(subject, render_to_string('docs/invoice_email.txt', ctx),
                                 to=[to], reply_to=['info@jamiitek.com'])
    msg.attach_alternative(render_to_string('docs/invoice_email.html', ctx), 'text/html')
    try:
        msg.send()
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Email failed: {exc}'[:200]}, status=502)
    return JsonResponse({'ok': True, 'to': to, 'status': inv.status})


@staff_member_required
@require_POST
def invoice_duplicate(request, pk):
    """Nakili ankara (mfano hosting ya mwezi ujao) kama rasimu mpya."""
    from datetime import timedelta
    src = get_object_or_404(Invoice, pk=pk)
    today = timezone.localdate()
    term = (src.due_date - src.issue_date) if (src.issue_date and src.due_date) else timedelta(days=14)
    copy = Invoice.objects.create(
        invoice_type=src.invoice_type, client=src.client, client_name=src.client_name,
        client_email=src.client_email, client_company=src.client_company,
        client_phone=src.client_phone, client_address=src.client_address,
        title=src.title, project_name=src.project_name, issue_date=today, due_date=today + term,
        line_items=src.items, currency=src.currency, payment_mode=src.payment_mode, tax_percent=src.tax_percent,
        discount_amount=src.discount_amount, payment_methods=src.payment_methods,
        payment_terms=src.payment_terms, notes_en=src.notes_en, notes_sw=src.notes_sw,
        logo_url=src.logo_url, provider_name=src.provider_name, provider_rep=src.provider_rep,
    )
    return JsonResponse({'ok': True, 'url': f'/manage/invoices/{copy.pk}/edit/'})


@staff_member_required
@require_POST
def invoice_ai_assist(request):
    from apps import docs_ai
    ok, result = docs_ai.assist_field(
        request.POST.get('field_type', 'notes'),
        request.POST.get('context', ''),
        request.POST.get('language', 'en'),
        kind='invoice')
    if not ok:
        return JsonResponse({'ok': False, 'error': result}, status=400)
    return JsonResponse({'ok': True, 'text': result})


# ============================================================
# UTHIBITISHO WA MALIPO (mteja amelipa M-Pesa / benki)
# ============================================================
PROOF_MAX_PENDING = 5


PROOF_METHODS = ['M-Pesa', 'Mixx by Yas', 'Airtel Money', 'HaloPesa', 'Bank transfer', 'Other']


def invoice_proof(request, token):
    """
    Ukurasa wa mteja wa kutuma uthibitisho wa malipo (Kiingereza):
    namba ya muamala, kiasi, na picha / screenshot / PDF ya ujumbe wa malipo.
    Wewe unahakiki kwenye /manage/invoices/<pk>/edit/#proofs.
    """
    from decimal import Decimal, InvalidOperation
    from django.core.cache import cache
    from .models import PaymentProof

    inv = get_object_or_404(Invoice, token=token)
    if inv.status in ('draft', 'cancelled') and not (request.user.is_authenticated and request.user.is_staff):
        return render(request, 'docs/invoice_unavailable.html', {'invoice': inv}, status=404)

    from apps.renewals import pay_ahead_options
    options = pay_ahead_options(inv)
    form = {'method': 'M-Pesa', 'reference': '', 'amount': f'{inv.balance_due:.0f}',
            'payer_phone': inv.client_phone or (inv.client.phone if inv.client else ''), 'note': '',
            'months': '1'}
    if request.GET.get('months', '').isdigit() and int(request.GET['months']) in {o['months'] for o in options}:
        form['months'] = request.GET['months']
    error = ''

    if request.method == 'POST' and not inv.is_paid and inv.status not in ('draft', 'cancelled'):
        for k in form:
            form[k] = request.POST.get(k, form[k] if k in ('method', 'months') else '').strip()
        allowed = {1} | {o['months'] for o in options}
        months = int(form['months']) if form['months'].isdigit() and int(form['months']) in allowed else 1
        form['months'] = str(months)
        upload = request.FILES.get('file')
        ip = _client_ip(request) or ''
        key = f'invproof:{ip}'
        hits = cache.get(key, 0)

        if hits >= 10 or inv.proofs.filter(status='pending').count() >= PROOF_MAX_PENDING:
            error = ('We already have several proofs for this invoice. Please wait while we check them, '
                     'or message us on WhatsApp.')
        elif not form['reference'] and not upload:
            error = 'Enter the transaction ID, or attach a screenshot or document of the payment.'
        else:
            amount = None
            try:
                amount = Decimal(form['amount'].replace(',', '')).quantize(Decimal('0.01')) if form['amount'] else None
                if amount is not None and amount <= 0:
                    amount = None
            except (InvalidOperation, ValueError):
                amount = None

            file_url = ''
            if upload:
                from . import storage
                res = storage.upload(upload, folder='payment-proofs')
                if res.get('success'):
                    file_url = res['url']
                elif not form['reference']:
                    error = ('We could not upload that file. Use a JPG, PNG or PDF under 10 MB, '
                             'or type the transaction ID instead.')

            if not error:
                cache.set(key, hits + 1, 3600)
                proof = PaymentProof.objects.create(
                    invoice=inv, method=form['method'][:60], reference=form['reference'][:120], amount=amount,
                    months=months,
                    payer_name=inv.display_client[:120], payer_phone=form['payer_phone'][:40],
                    note=form['note'][:1000], file_url=file_url, ip=ip or None)
                try:
                    from apps import activity
                    activity.record(
                        'payment_proof', f'Proof of payment — {inv.invoice_number} ({inv.display_client})',
                        rows=[('Method', proof.method or '-'), ('Reference', proof.reference or '-'),
                              ('Amount', f'{inv.currency} {proof.amount:,.0f}' if proof.amount else '-'),
                              ('Paid for', '1 month (as invoiced)' if months == 1 else f'{months} months (paid ahead)'),
                              ('Balance due', f'{inv.currency} {inv.balance_due:,.0f}'),
                              ('File', proof.file_url or 'none')],
                        link=f'/manage/invoices/{inv.pk}/edit/#proofs', level='warning',
                        actor='customer', amount=proof.amount)
                    from apps.notify import notify
                    notify(f'💰 {inv.display_client} says they paid invoice {inv.invoice_number} '
                           f'({inv.currency} {inv.balance_due:,.0f}). Ref: {proof.reference or "-"}. '
                           f'Check: {_site_url(f"/manage/invoices/{inv.pk}/edit/")}#proofs')
                except Exception:
                    pass
                return redirect(f'{inv.public_url}paid/?sent=1')

    proofs = list(inv.proofs.all()[:6])
    return render(request, 'docs/invoice_proof.html', {
        'invoice': inv, 'form': form, 'error': error, 'methods': PROOF_METHODS,
        'proofs': proofs, 'sent': request.GET.get('sent') == '1' and bool(proofs),
        'pending': any(p.status == 'pending' for p in proofs),
        'pay_methods': [m for m in (inv.payment_methods or []) if m.get('details')],
        'options': options,
        'days_left': (inv.due_date - timezone.localdate()).days if inv.due_date else None,
    }, status=400 if error else 200)


@staff_member_required
@require_POST
def invoice_proof_review(request, pk, proof_pk, action):
    """Idhinisha (rekodi malipo + risiti) au kataa uthibitisho wa mteja."""
    from django.contrib import messages
    from .models import PaymentProof

    inv = get_object_or_404(Invoice, pk=pk)
    proof = get_object_or_404(PaymentProof, pk=proof_pk, invoice=inv)
    edit = redirect(f'/manage/invoices/{inv.pk}/edit/#proofs')
    if proof.status != 'pending':
        messages.info(request, 'This proof was already handled.')
        return edit

    if action == 'reject':
        proof.status = 'rejected'
        proof.review_note = request.POST.get('note', '').strip()[:300]
        proof.reviewed_by, proof.reviewed_at = request.user, timezone.now()
        proof.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at'])
        messages.success(request, 'Proof rejected. Nothing was recorded.')
        return edit
    if action != 'approve':
        return edit

    # Mteja amelipa mapema (miezi 2,3,4,6,12): ankara inaandikwa upya kwa miezi hiyo kabla ya kurekodi
    months = request.POST.get('months', '') or str(proof.months or 1)
    months = int(months) if months.isdigit() else 1
    from apps import renewals
    if (months != 1 or proof.months != 1) and inv.paid_total == 0 and \
            inv.renewals.filter(kind__in=('hosting', 'email'), applied_at__isnull=True).exists():
        if months in (1,) + renewals.PAY_AHEAD_MONTHS:
            renewals.rebuild_lines(inv, months)
            inv.refresh_from_db()
            proof.months = months
            proof.save(update_fields=['months'])
    raw = request.POST.get('amount', '').replace(',', '').strip()
    # Miezi imebadilishwa lakini kiasi ni kile cha zamani cha mteja → tumia salio jipya la ankara
    if months != (proof_months_before := int(request.POST.get('proof_months', proof.months) or proof.months)) \
            and raw and proof.amount is not None and abs(float(raw) - float(proof.amount)) < 1:
        raw = ''
    amount = raw or (proof.amount if months == proof_months_before else None) or inv.balance_due
    try:
        if float(amount) > inv.balance_due + 0.005:
            messages.error(request, f'That is more than the balance due ({inv.currency} {inv.balance_due:,.0f}).')
            return edit
        inv.record_payment(amount, method=proof.method or 'Manual', reference=proof.reference,
                           by=request.user.get_username(), source='manual')
    except ValueError as exc:
        messages.error(request, str(exc))
        return edit
    inv.save()
    proof.status = 'approved'
    proof.amount = inv.payments[-1]['amount']
    proof.reviewed_by, proof.reviewed_at = request.user, timezone.now()
    proof.save(update_fields=['status', 'amount', 'reviewed_by', 'reviewed_at'])

    from apps.renewals import after_payment
    done = after_payment(inv, proof.amount, method=proof.method, reference=proof.reference,
                         by=request.user.get_full_name() or request.user.get_username(), user=request.user)
    r = done['receipt']
    sent = ' and '.join(x for x, ok in (('email', done['email']), ('WhatsApp', done['whatsapp'])) if ok)
    messages.success(request, (f'Payment recorded. Receipt {r.receipt_number} created'
                               + (f' — confirmation link sent by {sent}.' if sent else
                                  ' — the confirmation link could not be sent; share it yourself.')
                               if r else 'Payment recorded, but the receipt could not be created.')
                     + (' Renewed: ' + '; '.join(done['renewed']) if done['renewed'] else ''))
    return edit
