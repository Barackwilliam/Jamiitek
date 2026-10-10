"""
Upande wa JamiiTek — kusimamia infrastructure ya kila project.

Tofauti kubwa na portal ya mteja:
  • hapa unaona majina halisi ya providers
  • hapa kuna vitendo: deploy, restart, rollback, suspend
  • kila kitendo kinaingia IntegrationAuditLog

Client portal HAINA route yoyote inayoita run_action(). Si kwa kuficha
kitufe — code yenyewe haipo upande ule.
"""
import json
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .crypto import encryption_available
from .integrations import ADAPTERS, AdapterError, get_adapter, get_adapter_class
from .live_config import live_config
from .management_views import staff_required
from .models import Integration, IntegrationAuditLog, ManagedWebsite

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  ORODHA
# ══════════════════════════════════════════════════════════════════

@staff_required
def infra_overview(request):
    """Projects zote na afya ya providers wao kwa mtazamo mmoja."""
    websites = (ManagedWebsite.objects
                .select_related('client', 'hosting_config')
                .prefetch_related('integrations')
                .order_by('name'))

    rows, total_cost = [], 0
    for w in websites:
        integs = [i for i in w.integrations.all() if i.is_active]
        cost = sum(float(i.monthly_cost_usd or 0) for i in integs)
        total_cost += cost
        rows.append({
            'website': w,
            'cfg': live_config(w),
            'integrations': integs,
            'cost': cost,
        })

    return render(request, 'management/infra_overview.html', {
        'title': 'Infrastructure',
        'rows': rows,
        'total_cost': round(total_cost, 2),
        'encryption_ok': encryption_available(),
        'providers': ADAPTERS,
    })


@staff_required
def infra_detail(request, pk):
    """Project moja — tabs za providers wote."""
    website = get_object_or_404(
        ManagedWebsite.objects.select_related('client'), pk=pk)

    panels = []
    for integ in website.integrations.filter(is_active=True):
        adapter = integ.adapter
        panels.append({
            'integration': integ,
            'label': adapter.label,
            'client_label': adapter.client_label,
            'summary': integ.cached_summary or {},
            'actions': adapter.actions(),
            'error': integ.sync_error,
        })

    missing = [(k, c.label) for k, c in ADAPTERS.items()
               if not website.integrations.filter(provider=k).exists()]

    return render(request, 'management/infra_detail.html', {
        'title': f'Infrastructure — {website.name}',
        'website': website,
        'cfg': live_config(website),
        'panels': panels,
        'missing': missing,
        'uptime': website.uptime_percent(30),
        'recent_logs': IntegrationAuditLog.objects.filter(
            website=website)[:15],
    })


@staff_required
def infra_sections(request, integration_id):
    """Logs / DNS / files — zinapakiwa kwa HTMX pale unapozihitaji."""
    integ = get_object_or_404(Integration, pk=integration_id)
    try:
        sections = integ.adapter.sections()
        error = ''
    except AdapterError as e:
        sections, error = [], str(e)

    return render(request, 'management/_infra_sections.html',
                  {'sections': sections, 'error': error, 'integration': integ})


# ══════════════════════════════════════════════════════════════════
#  VITENDO
# ══════════════════════════════════════════════════════════════════

@staff_required
@require_POST
def infra_action(request, integration_id):
    integ = get_object_or_404(Integration, pk=integration_id)
    key = request.POST.get('action', '')

    allowed = {a['key'] for a in integ.adapter.actions()}
    if key not in allowed:
        return JsonResponse({'ok': False, 'message': 'Kitendo hakiruhusiwi.'},
                            status=400)

    try:
        result = integ.adapter.run_action(key)
    except AdapterError as e:
        IntegrationAuditLog.record(f'{key}_failed', user=request.user,
                                   integration=integ, request=request,
                                   detail={'error': str(e)})
        return JsonResponse({'ok': False, 'message': str(e)}, status=502)

    IntegrationAuditLog.record(key, user=request.user, integration=integ,
                               request=request, detail=result)
    integ.sync()
    return JsonResponse({'ok': True, **result})


@staff_required
def infra_job_status(request, integration_id, job_id):
    """Polling ya deploy inayoendelea."""
    integ = get_object_or_404(Integration, pk=integration_id)
    adapter = integ.adapter
    if not hasattr(adapter, 'deploy_status'):
        return JsonResponse({'done': True, 'status': 'unknown'})
    try:
        return JsonResponse(adapter.deploy_status(job_id))
    except AdapterError as e:
        return JsonResponse({'done': True, 'status': 'error',
                             'message': str(e)})


@staff_required
@require_POST
def infra_sync(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk)
    ok = sum(1 for i in website.integrations.filter(is_active=True) if i.sync())
    IntegrationAuditLog.record('sync_manual', user=request.user,
                               website=website, request=request)
    messages.success(request, f'Sync imekamilika ({ok}).')
    return redirect('infra_detail', pk=pk)


# ══════════════════════════════════════════════════════════════════
#  CONNECT WIZARD
# ══════════════════════════════════════════════════════════════════

@staff_required
@require_POST
def infra_discover(request, pk):
    """Hatua 1 — thibitisha credentials, onyesha resources zilizopo."""
    website = get_object_or_404(ManagedWebsite, pk=pk)
    provider = request.POST.get('provider', '')

    try:
        adapter_cls = get_adapter_class(provider)
    except AdapterError as e:
        return render(request, 'management/_infra_discover.html', {'error': str(e)})

    creds = {}
    for field in adapter_cls.credential_fields:
        val = (request.POST.get(field['key']) or '').strip()
        if val:
            creds[field['key']] = val

    try:
        resources = adapter_cls.discover(creds)
    except AdapterError as e:
        return render(request, 'management/_infra_discover.html',
                      {'error': str(e), 'provider': provider,
                       'website': website, 'fields': adapter_cls.credential_fields})

    request.session[f'pending_{website.pk}_{provider}'] = creds
    request.session.set_expiry(900)

    return render(request, 'management/_infra_discover.html', {
        'website': website, 'provider': provider,
        'label': adapter_cls.label, 'resources': resources,
    })


@staff_required
@require_POST
def infra_attach(request, pk):
    """Hatua 2 — chagua resource, hifadhi."""
    website = get_object_or_404(ManagedWebsite, pk=pk)
    provider = request.POST.get('provider', '')
    external_id = request.POST.get('external_id', '')
    name = request.POST.get('name', '')

    creds = request.session.pop(f'pending_{website.pk}_{provider}', None)
    if not creds:
        messages.error(request, 'Muda umeisha — anza upya.')
        return redirect('infra_detail', pk=pk)

    integ, created = Integration.objects.update_or_create(
        website=website, provider=provider, external_id=external_id,
        defaults={'credentials': creds, 'display_name': name},
    )
    IntegrationAuditLog.record('connect' if created else 'reconnect',
                               user=request.user, integration=integ,
                               request=request, detail={'provider': provider})
    integ.sync()
    messages.success(request, f'{provider} imeunganishwa.')
    return redirect('infra_detail', pk=pk)


@staff_required
@require_POST
def infra_disconnect(request, integration_id):
    integ = get_object_or_404(Integration, pk=integration_id)
    pk = integ.website_id
    IntegrationAuditLog.record('disconnect', user=request.user,
                               website=integ.website, request=request,
                               detail={'provider': integ.provider,
                                       'external_id': integ.external_id})
    integ.delete()
    messages.success(request, 'Imetenganishwa.')
    return redirect('infra_detail', pk=pk)


@staff_required
def infra_credential_fields(request):
    """Fields za form zinabadilika kutegemea provider."""
    provider = request.GET.get('provider', '')
    try:
        fields = get_adapter_class(provider).credential_fields
    except AdapterError:
        fields = []
    return render(request, 'management/_infra_cred_fields.html',
                  {'fields': fields, 'provider': provider})


# ══════════════════════════════════════════════════════════════════
#  AUDIT
# ══════════════════════════════════════════════════════════════════

@staff_required
def infra_audit(request):
    logs = (IntegrationAuditLog.objects
            .select_related('user', 'website')[:200])
    return render(request, 'management/infra_audit.html',
                  {'title': 'Audit log', 'logs': logs})


# ══════════════════════════════════════════════════════════════════
#  CRON (bure — cron-job.org au GitHub Actions)
# ══════════════════════════════════════════════════════════════════

import os

from django.core.management import call_command
from django.http import HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def cron_sync(request):
    """
    Endpoint ya kupigwa kutoka nje kila dakika 15.

    Weka CRON_TOKEN kwenye environment, kisha cron-job.org iite:
        POST https://jamiitek.co.tz/cron/sync/
        Header: X-Cron-Token: <token>
    """
    token = os.getenv('CRON_TOKEN', '')
    import secrets
    if not token or not secrets.compare_digest(request.headers.get('X-Cron-Token', ''), token):
        return HttpResponseForbidden('nope')

    call_command('sync_integrations', quiet=True)
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════
#  RIPOTI YA PDF
# ══════════════════════════════════════════════════════════════════

from django.http import HttpResponse


@staff_required
def infra_report(request, pk):
    """Staff — ripoti ya project yoyote."""
    from . import reports
    website = get_object_or_404(ManagedWebsite, pk=pk)
    pdf = reports.build_pdf(website)
    IntegrationAuditLog.record('report', user=request.user,
                               website=website, request=request)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{reports.filename(website)}"'
    return resp
