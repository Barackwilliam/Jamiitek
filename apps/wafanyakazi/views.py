"""
Panel ya timu (/manage/wafanyakazi/), endpoint ya cron na API ya wILife.
"""
import json
import os
import secrets
from datetime import datetime, timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.management_views import staff_required

from . import actions, mtihani, ofisi, runner, wilife
from .models import Alama, Kazi, Mtihani, Ripoti
from .team import TEAM, member
from .william import snapshot

def _when(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


ACTIONS = {'tuma': actions.approve, 'kamilisha': actions.complete, 'achana': actions.dismiss}


# ══════════════════════════════════════════════════════════════
#  PANEL
# ══════════════════════════════════════════════════════════════

@staff_required
def dashboard(request):
    worker = request.GET.get('w', '')
    if worker not in TEAM:
        worker = ''
    view = request.GET.get('hali', 'hai')

    qs = Kazi.objects.all()
    if worker:
        qs = qs.filter(worker=worker)
    if view == 'zilizofungwa':
        qs = qs.exclude(status__in=Kazi.LIVE).order_by('-closed_at')
    else:
        view = 'hai'
        # 'awaiting' < 'open' kialfabeti: zinazosubiri idhini zinakaa juu
        qs = qs.filter(status__in=Kazi.LIVE).order_by('status', 'priority', '-created_at')

    tasks = list(qs[:100])
    for kazi in tasks:
        kazi.who = member(kazi.worker)
        if kazi.channel == 'whatsapp' and kazi.recipient_phone:
            kazi.wa = actions.wa_link(kazi.recipient_phone, kazi.draft)

    team = ofisi.team(snapshot())
    says, says_report = ofisi.william_says()

    return render(request, 'wafanyakazi/dashboard.html', {
        'nav': 'wafanyakazi', 'title': 'Ofisi ya timu',
        'team': team, 'lead': team[0], 'staff': team[1:],
        'tasks': tasks, 'worker': worker, 'view': view,
        'current': next((w for w in team if w['slug'] == worker), None),
        'feed': ofisi.feed(), 'counts': ofisi.counts(),
        'william_says': says, 'william_report': says_report,
        'reports': Ripoti.objects.all()[:6],
        'last_run': _when(Alama.get('run:last')),
        'wilife_ready': wilife.is_configured(),
        'awaiting_total': Kazi.objects.filter(status=Kazi.AWAITING).count(),
    })


@staff_required
@require_POST
def task_action(request, pk, action):
    if action not in ACTIONS:
        return redirect('wafanyakazi_dashboard')
    kazi = get_object_or_404(Kazi, pk=pk)
    if action == 'tuma':
        ok, message = actions.approve(kazi.pk, draft=request.POST.get('draft'))
    else:
        ok, message = ACTIONS[action](kazi.pk)
    (messages.success if ok else messages.error)(request, message)
    back = request.POST.get('next') or ''
    return redirect(back if back.startswith('/manage/wafanyakazi/') else 'wafanyakazi_dashboard')


@staff_required
@require_POST
def run_now(request):
    report = request.POST.get('ripoti') or None
    if report not in (None, 'asubuhi', 'jioni'):
        report = None
    runner.run_in_background(force_report=report)
    messages.success(request, 'Timu imeanza kazi — onyesha ukurasa upya baada ya dakika moja.'
                     + (' Ripoti itatumwa ikikamilika.' if report else ''))
    return redirect('wafanyakazi_dashboard')


@staff_required
def exam(request):
    """Mtihani wa umahiri: rasimu za mfano kwenye data halisi, bila kuhifadhi wala kutuma."""
    if request.method == 'POST':
        if Mtihani.objects.filter(status=Mtihani.RUNNING,
                                  created_at__gte=timezone.now() - timedelta(minutes=10)).exists():
            messages.error(request, 'Mtihani mmoja tayari unaendelea.')
        else:
            mtihani.run_in_background()
            messages.success(request, 'Mtihani umeanza — utachukua dakika 1–2. Ukurasa utajisasisha.')
        return redirect('wafanyakazi_exam')
    latest = Mtihani.objects.first()
    return render(request, 'wafanyakazi/mtihani.html', {
        'nav': 'wafanyakazi', 'title': 'Mtihani wa umahiri',
        'exam': latest, 'r': latest.result if latest else {},
        'history': Mtihani.objects.exclude(pk=getattr(latest, 'pk', None))[:5],
    })


def _trend(history):
    weeks = [{'week': h.week[5:], 'clicks': (h.totals or {}).get('clicks', 0)} for h in reversed(history)]
    top = max([w['clicks'] for w in weeks] + [1])
    for w in weeks:
        w['h'] = max(4, round(w['clicks'] / top * 76))   # px — nguzo ndefu zaidi = 76px
    return weeks


@staff_required
def seo_report(request):
    """Ripoti ya SEO ya Grace (Google Search Console) — /manage/seo/."""
    from apps.seo import gsc

    from . import seo
    from .models import SeoRipoti

    if request.method == 'POST':
        if not gsc.is_configured():
            messages.error(request, 'Search Console bado haijaunganishwa — angalia hatua hapa chini.')
        else:
            import threading

            from django.db import connection

            def target():
                try:
                    seo.audit(timezone.localtime(), force=True)
                except Exception:
                    seo.logger.exception('[seo] ukaguzi wa mkono')
                finally:
                    connection.close()

            threading.Thread(target=target, name='jamiitek-seo', daemon=True).start()
            messages.success(request, 'Grace ameanza ukaguzi — onyesha ukurasa upya baada ya dakika moja.')
        return redirect('wafanyakazi_seo')

    history = list(SeoRipoti.objects.all()[:8])
    latest = history[0] if history else None
    change = {}
    if latest and latest.totals and latest.previous:
        for k in ('clicks', 'impressions', 'ctr', 'position'):
            now_v, old_v = latest.totals.get(k, 0), latest.previous.get(k, 0)
            change[k] = {'diff': round(now_v - old_v, 4 if k == 'ctr' else 1),
                         'pct': round((now_v - old_v) / old_v * 100) if old_v else None}
        change['ctr']['pts'] = round(change['ctr']['diff'] * 100, 1)
    pending = (Kazi.objects.filter(channel='seo', status__in=Kazi.LIVE)
               .order_by('priority', '-created_at'))
    applied = (Kazi.objects.filter(channel='seo', status=Kazi.DONE).order_by('-closed_at')[:8])
    return render(request, 'wafanyakazi/seo.html', {
        'nav': 'seo', 'title': 'SEO — Google Search Console',
        'configured': gsc.is_configured(), 'site_url': gsc.site_url(),
        'service_email': (gsc.credentials() or {}).get('client_email', ''),
        'r': latest, 'change': change, 'trend': _trend(history),
        'ctr_pct': round((latest.totals or {}).get('ctr', 0) * 100, 1) if latest else 0,
        'pending': pending, 'applied': applied,
        'grace': member('grace'), 'min_impressions': seo.MIN_IMPRESSIONS, 'days': seo.DAYS,
    })


# ══════════════════════════════════════════════════════════════
#  CRON  — /tasks/wafanyakazi/?token=TASKS_TOKEN
# ══════════════════════════════════════════════════════════════

@require_GET
def cron(request):
    expected = os.getenv('TASKS_TOKEN', '')
    if not expected:
        return JsonResponse({'ok': False, 'error': 'TASKS_TOKEN is not set.'}, status=503)
    given = request.GET.get('token') or request.headers.get('X-Tasks-Token', '')
    if not secrets.compare_digest(str(given), str(expected)):
        return JsonResponse({'ok': False, 'error': 'Invalid token.'}, status=403)
    runner.run_in_background()
    return JsonResponse({'ok': True, 'status': 'started'})


# ══════════════════════════════════════════════════════════════
#  API YA wILife  — header X-Workers-Token
# ══════════════════════════════════════════════════════════════

def _api_auth(request):
    expected = wilife.token()
    if not expected:
        return JsonResponse({'ok': False, 'error': 'WORKERS_API_TOKEN is not set.'}, status=503)
    given = request.headers.get('X-Workers-Token', '')
    if not secrets.compare_digest(str(given), str(expected)):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    return None


def _task_json(kazi):
    return {
        'id': kazi.pk, 'worker': kazi.worker, 'worker_name': member(kazi.worker)['name'],
        'title': kazi.title, 'status': kazi.status, 'priority': kazi.priority,
        'channel': kazi.channel, 'recipient': kazi.recipient_email or kazi.recipient_phone,
        'recipient_name': kazi.recipient_name, 'draft': kazi.draft, 'link': kazi.link,
        'created_at': kazi.created_at.isoformat(timespec='minutes'),
        'wilife_code': kazi.wilife_code,
    }


@csrf_exempt
@require_GET
def api_status(request):
    denied = _api_auth(request)
    if denied:
        return denied
    latest = Ripoti.objects.first()
    awaiting = Kazi.objects.filter(status=Kazi.AWAITING).order_by('priority', 'created_at')[:20]
    return JsonResponse({
        'ok': True,
        'last_run': _when(Alama.get('run:last')),
        'team': [{k: w[k] for k in ('slug', 'name', 'role', 'open', 'awaiting', 'stale')}
                 for w in snapshot()],
        'awaiting': [_task_json(k) for k in awaiting],
        'report': {'kind': latest.kind, 'date': latest.date.isoformat(), 'text': latest.text}
        if latest else None,
    })


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


@csrf_exempt
@require_POST
def api_approve(request, pk):
    denied = _api_auth(request)
    if denied:
        return denied
    ok, message = actions.approve(pk, draft=_body(request).get('draft'))
    return JsonResponse({'ok': ok, 'message': message})


@csrf_exempt
@require_POST
def api_reject(request, pk):
    denied = _api_auth(request)
    if denied:
        return denied
    ok, message = actions.dismiss(pk, 'Umekataa kupitia wILife.')
    return JsonResponse({'ok': ok, 'message': message})


@csrf_exempt
@require_POST
def api_run(request):
    denied = _api_auth(request)
    if denied:
        return denied
    report = _body(request).get('ripoti')
    runner.run_in_background(force_report=report if report in ('asubuhi', 'jioni') else None)
    return JsonResponse({'ok': True, 'status': 'started'})
