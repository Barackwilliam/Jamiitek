"""
Kanuni za alerts.

MSINGI: code ya kawaida ndiyo inayogundua matatizo, si AI. AI inatumika
kwa muhtasari tu. Alert lazima iwe ya uhakika, isiyo na ubashiri.

Kila alert ina `key` ya kipekee ili isirudiwe kila dakika 15. Dedup
inatumia IntegrationAuditLog — hakuna table mpya inayohitajika.
"""
import logging
from datetime import date, timedelta

from django.utils import timezone

from .integrations import base
from .live_config import live_config
from .models import IntegrationAuditLog, ManagedWebsite
from .notify import notify

logger = logging.getLogger(__name__)

# Muda wa kutorudia alert ileile
COOLDOWN = {
    'critical': timedelta(hours=6),
    'warning': timedelta(days=1),
    'info': timedelta(days=7),
}

DOMAIN_WARN_DAYS = 45
SSL_WARN_DAYS = 14
SYNC_DEAD_HOURS = 6


class Alert:
    __slots__ = ('key', 'level', 'title', 'body', 'website')

    def __init__(self, key, level, title, body, website):
        self.key = key
        self.level = level
        self.title = title
        self.body = body
        self.website = website

    def as_message(self):
        icon = {'critical': '🔴', 'warning': '🟡', 'info': '🔵'}[self.level]
        return (f'{icon} <b>{self.title}</b>\n'
                f'{self.website.name} — {self.website.client.name}\n\n'
                f'{self.body}')


# ══════════════════════════════════════════════════════════════════
#  KANUNI
# ══════════════════════════════════════════════════════════════════

def _rule_hosting_down(w, cfg):
    status = cfg.live_status
    if status == 'failed':
        yield Alert(f'down:{w.pk}', 'critical', 'Site iko chini',
                    'Deploy ya mwisho imeshindwa. Angalia logs kwenye '
                    'JamiiTek → Infrastructure.', w)
    elif status == 'suspended' and w.status == 'active':
        yield Alert(f'susp:{w.pk}', 'critical', 'Service imesimamishwa',
                    'Hosting imesimamishwa ingawa bili bado ni hai. '
                    'Angalia malipo ya provider.', w)


def _rule_domain_expiry(w, cfg):
    r = w.resolve(base.DOMAIN_EXPIRY)
    expiry = _as_date(r.value)
    if not expiry:
        # hakuna RDAP — jaribu ya mkono
        dom = w.domains.first()
        expiry = dom.expiry_date if dom else None
    if not expiry:
        return

    days = (expiry - timezone.now().date()).days
    if days > DOMAIN_WARN_DAYS or days < -30:
        return

    auto = w.resolve(base.DOMAIN_AUTORENEW).value
    dom = w.domains.first()
    if auto is None and dom:
        auto = dom.auto_renew

    if days < 0:
        yield Alert(f'domexp:{w.pk}', 'critical', 'Domain IMEISHA',
                    f'Ilipitwa siku {abs(days)} zilizopita ({expiry}). '
                    'Site inaweza kuzimika wakati wowote.', w)
    elif not auto:
        level = 'critical' if days <= 7 else 'warning'
        yield Alert(f'domexp:{w.pk}', level, 'Domain inakaribia kuisha',
                    f'Siku {days} zimebaki ({expiry}) na auto-renew '
                    f'HAIJAWASHWA. Renew kwa registrar sasa.', w)


def _rule_ssl_expiry(w, cfg):
    days = cfg.ssl_days_left
    if days is None or days > SSL_WARN_DAYS:
        return
    level = 'critical' if days <= 3 else 'warning'
    yield Alert(f'ssl:{w.pk}', level, 'SSL inakaribia kuisha',
                f'Siku {days} zimebaki. Kama ni Cloudflare au Render, '
                'inajirenew yenyewe — thibitisha tu.', w)


def _rule_sync_dead(w, cfg):
    cutoff = timezone.now() - timedelta(hours=SYNC_DEAD_HOURS)
    for integ in w.integrations.filter(is_active=True):
        if integ.sync_error and (integ.last_synced_at or timezone.now()) < cutoff:
            yield Alert(f'sync:{integ.pk}', 'warning',
                        f'Sync imekufa — {integ.provider}',
                        f'Saa {SYNC_DEAD_HOURS}+ bila mafanikio.\n'
                        f'<code>{integ.sync_error[:120]}</code>', w)


def _rule_storage(w, cfg):
    used, limit = cfg.disk_used_gb, cfg.disk_total_gb
    if not used or not limit:
        return
    pct = float(used) / float(limit) * 100
    if pct >= 85:
        yield Alert(f'disk:{w.pk}', 'warning' if pct < 95 else 'critical',
                    'Storage inakaribia kikomo',
                    f'{used} GB kati ya {limit} GB ({pct:.0f}%). '
                    'Wakati wa kuzungumza na mteja kuhusu plan.', w)


def _rule_hosting_billing(w, cfg):
    days = (w.hosting_end_date - timezone.now().date()).days
    if 0 < days <= 7 and w.status == 'active':
        yield Alert(f'bill:{w.pk}', 'info', 'Hosting inaisha',
                    f'Siku {days} zimebaki. Tuma invoice kama '
                    'haujatuma bado.', w)


RULES = [
    _rule_hosting_down,
    _rule_domain_expiry,
    _rule_ssl_expiry,
    _rule_sync_dead,
    _rule_storage,
    _rule_hosting_billing,
]


# ══════════════════════════════════════════════════════════════════
#  ENDESHAJI
# ══════════════════════════════════════════════════════════════════

def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def collect(website=None):
    """Rudisha alerts zote zilizopo sasa hivi."""
    qs = ManagedWebsite.objects.select_related('client').prefetch_related(
        'integrations', 'domains')
    if website is not None:
        qs = qs.filter(pk=website.pk)
    else:
        qs = qs.exclude(status='terminated')

    alerts = []
    for w in qs:
        cfg = live_config(w)
        for rule in RULES:
            try:
                alerts.extend(rule(w, cfg))
            except Exception as e:
                logger.warning('Rule %s imeshindwa kwa %s: %s',
                               rule.__name__, w.pk, type(e).__name__)
    return alerts


def _recently_sent(alert):
    since = timezone.now() - COOLDOWN[alert.level]
    return IntegrationAuditLog.objects.filter(
        action='alert', created_at__gte=since,
        detail__key=alert.key).exists()


def dispatch(alerts, dry_run=False):
    """Tuma alerts ambazo hazijatumwa hivi karibuni.

    Alerts zote mpya za ukaguzi mmoja zinatumwa kwenye ujumbe MMOJA (email moja), si moja moja —
    tovuti tano zenye domain zilizoisha zilileta email tano mfululizo.
    """
    fresh = [a for a in alerts if not _recently_sent(a)]
    if fresh and not dry_run:
        notify(combined_message(fresh))
        for a in fresh:
            IntegrationAuditLog.record(
                'alert', website=a.website,
                detail={'key': a.key, 'level': a.level, 'title': a.title})
    return fresh


def combined_message(alerts):
    if len(alerts) == 1:
        return alerts[0].as_message()
    order = {'critical': 0, 'warning': 1, 'info': 2}
    alerts = sorted(alerts, key=lambda a: order[a.level])
    icon = {'critical': '🔴', 'warning': '🟡', 'info': '🔵'}[alerts[0].level]
    head = f'{icon} <b>{len(alerts)} alerts need attention</b>'
    return head + '\n\n' + '\n\n'.join(a.as_message() for a in alerts)
