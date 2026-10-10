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


def _render_pdf(request, template, ctx, filename):
    html = render(request, template, ctx).content.decode('utf-8')
    try:
        from xhtml2pdf import pisa
        from io import BytesIO
        buf = BytesIO()
        status = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
        if status.err:
            raise Exception('PDF error')
        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/pdf')
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


def _public_ctx(request, invoice):
    from apps.contact import contact
    from django.contrib.messages import get_messages
    c = contact()
    return {'invoice': invoice, 'lang': _lang(request), 'contact': c,
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
    return render(request, 'docs/invoice_view.html', ctx)


def invoice_pdf(request, token):
    invoice = get_object_or_404(Invoice, token=token)
    is_staff = request.user.is_authenticated and request.user.is_staff
    if invoice.status in ('draft', 'cancelled') and not is_staff:
        return HttpResponse('Not available', status=404)
    ctx = _public_ctx(request, invoice)
    ctx['qr'] = _invoice_qr_png(request, invoice)
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

    qs = Invoice.objects.select_related('client')
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
    return render(request, 'docs/invoice_edit.html', {
        'invoice': inv,
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
    raw = request.POST.get('amount', '').replace(',', '').strip()
    amount = raw or inv.balance_due
    try:
        inv.record_payment(amount,
                           method=request.POST.get('method', '').strip() or 'Manual',
                           reference=request.POST.get('reference', '').strip(),
                           by=request.user.get_username(), source='manual')
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    inv.save()
    return JsonResponse({'ok': True, 'status': inv.status,
                         'balance_due': inv.balance_due, 'paid_total': inv.paid_total})


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
    if not inv.items:
        return JsonResponse({'ok': False, 'error': 'Add at least one item first'}, status=400)
    if inv.status == 'draft':
        inv.status = 'sent'
    inv.sent_at = inv.sent_at or timezone.now()
    inv.save(update_fields=['status', 'sent_at'])

    lang = request.POST.get('lang') if request.POST.get('lang') in ('en', 'sw') else 'sw'
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
