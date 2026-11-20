"""Manage → Company Documents: kuhifadhi na kufungua nyaraka rasmi za kampuni."""
import re
from datetime import date

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .management_views import staff_required
from .models import CompanyDocument

MAX_BYTES = 10 * 1024 * 1024
# Aina zinazoruhusiwa, zinakaguliwa kwa bytes za mwanzo (si jina la file)
SIGNATURES = [
    (b'%PDF-', 'application/pdf', 'pdf'),
    (b'\x89PNG\r\n\x1a\n', 'image/png', 'png'),
    (b'\xff\xd8\xff', 'image/jpeg', 'jpg'),
]


def _sniff(data):
    for sig, ctype, ext in SIGNATURES:
        if data.startswith(sig):
            return ctype, ext
    return None, None


def _date(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


@staff_required
def company_docs(request):
    if request.method == 'POST':
        f = request.FILES.get('file')
        title = (request.POST.get('title') or '').strip()
        if not f or not title:
            messages.error(request, 'Weka jina la hati na uchague file.')
            return redirect('company_docs')
        if f.size > MAX_BYTES:
            messages.error(request, 'File ni kubwa mno. Kikomo ni 10MB.')
            return redirect('company_docs')
        data = f.read()
        ctype, ext = _sniff(data)
        if not ctype:
            messages.error(request, 'Tumia PDF, JPG au PNG pekee.')
            return redirect('company_docs')
        base = re.sub(r'[^A-Za-z0-9._-]+', '-', title).strip('-')[:80] or 'document'
        category = request.POST.get('category') or 'other'
        if category not in dict(CompanyDocument.CATEGORIES):
            category = 'other'
        CompanyDocument.objects.create(
            title=title[:160], category=category,
            number=(request.POST.get('number') or '').strip()[:80],
            issued_on=_date(request.POST.get('issued_on')),
            expires_on=_date(request.POST.get('expires_on')),
            notes=(request.POST.get('notes') or '').strip(),
            file_name=f'{base}.{ext}', content_type=ctype, size=len(data), data=data,
            uploaded_by=request.user,
        )
        messages.success(request, f'"{title}" imehifadhiwa.')
        return redirect('company_docs')

    docs = CompanyDocument.objects.defer('data').select_related('uploaded_by')
    return render(request, 'management/company_docs.html', {
        'nav': 'company_docs', 'docs': docs, 'categories': CompanyDocument.CATEGORIES,
        'today': date.today(),
    })


@staff_required
def company_doc_file(request, pk):
    doc = get_object_or_404(CompanyDocument, pk=pk)
    resp = HttpResponse(bytes(doc.data), content_type=doc.content_type)
    mode = 'attachment' if request.GET.get('download') else 'inline'
    resp['Content-Disposition'] = f'{mode}; filename="{doc.file_name}"'
    resp['Cache-Control'] = 'private, no-store'
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return resp


@staff_required
@require_POST
def company_doc_delete(request, pk):
    doc = get_object_or_404(CompanyDocument, pk=pk)
    messages.success(request, f'"{doc.title}" imefutwa.')
    doc.delete()
    return redirect('company_docs')
