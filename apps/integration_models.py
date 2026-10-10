"""
Models za kuunganisha ManagedWebsite na providers halisi.

Hakuna model ya website inayoundwa upya — hii inaambatana na
ManagedWebsite iliyopo.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .crypto import EncryptedJSONField

STALE_AFTER = timedelta(minutes=30)


class Integration(models.Model):
    """Mlango mmoja wa provider kwa website moja."""

    website = models.ForeignKey(
        'apps.ManagedWebsite',
        on_delete=models.CASCADE,
        related_name='integrations',
    )

    provider = models.CharField(max_length=32)
    display_name = models.CharField(max_length=150, blank=True)
    external_id = models.CharField(
        max_length=200,
        help_text="srv-xxx (Render), zone id (Cloudflare), domain (RDAP)",
    )

    credentials = EncryptedJSONField(
        help_text='Imefichwa kwa Fernet. Haionekani baada ya kuhifadhi.'
    )

    # Metadata ya kibiashara
    account_email = models.EmailField(blank=True)
    plan = models.CharField(max_length=60, blank=True)
    monthly_cost_usd = models.DecimalField(
        max_digits=8, decimal_places=2, default=0)
    renews_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    # Hali ya sync
    cached_summary = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'apps'
        unique_together = ('website', 'provider', 'external_id')
        ordering = ['website', 'provider']
        verbose_name = 'Integration'
        verbose_name_plural = 'Integrations'

    def __str__(self):
        return f'{self.website.name} — {self.provider}'

    def clean(self):
        from .integrations import ADAPTERS
        if self.provider not in ADAPTERS:
            raise ValidationError({'provider': f'Provider haijulikani: {self.provider}'})

    @property
    def adapter(self):
        from .integrations import get_adapter
        return get_adapter(self)

    @property
    def is_stale(self):
        if not self.last_synced_at:
            return True
        return timezone.now() - self.last_synced_at > STALE_AFTER

    @property
    def health(self):
        if not self.is_active:
            return 'disabled'
        if self.sync_error:
            return 'error'
        if self.is_stale:
            return 'stale'
        return 'ok'

    def sync(self):
        """Vuta data mpya. Kamwe isitupe exception."""
        try:
            summary = self.adapter.summary() or {}
            self.cached_summary = summary
            self.sync_error = ''
            ok = True
        except Exception as e:
            self.sync_error = f'{type(e).__name__}: {e}'[:500]
            ok = False
            summary = {}

        self.last_synced_at = timezone.now()
        self.save(update_fields=['cached_summary', 'sync_error', 'last_synced_at'])

        if ok and summary:
            IntegrationSnapshot.objects.create(
                integration=self, checked_at=self.last_synced_at, metrics=summary)
        return ok


class IntegrationSnapshot(models.Model):
    """
    Historia. Ndiyo inayotoa uptime, na ndiyo fallback ya kwanza
    kabla ya kurudi kwenye data ya mkono.
    """

    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name='snapshots')
    checked_at = models.DateTimeField(db_index=True)
    metrics = models.JSONField(default=dict)

    class Meta:
        app_label = 'apps'
        ordering = ['-checked_at']
        indexes = [models.Index(fields=['integration', '-checked_at'])]

    def __str__(self):
        return f'{self.integration_id} @ {self.checked_at:%Y-%m-%d %H:%M}'


class IntegrationAuditLog(models.Model):
    """Kila kitendo. Bila ubaguzi."""

    user = models.ForeignKey(User, on_delete=models.PROTECT,
                            null=True, blank=True)
    integration = models.ForeignKey(Integration, on_delete=models.SET_NULL,
                                    null=True, blank=True)
    website = models.ForeignKey('apps.ManagedWebsite', on_delete=models.SET_NULL,
                                null=True, blank=True)

    action = models.CharField(max_length=60)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = 'apps'
        ordering = ['-created_at']
        verbose_name = 'Integration audit log'
        verbose_name_plural = 'Integration audit logs'

    def __str__(self):
        who = self.user.username if self.user else 'system'
        return f'{who} · {self.action} · {self.created_at:%Y-%m-%d %H:%M}'

    @classmethod
    def record(cls, action, user=None, integration=None, website=None,
               detail=None, request=None):
        ip = None
        if request is not None:
            fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
            ip = fwd.split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        return cls.objects.create(
            action=action, user=user if (user and user.is_authenticated) else None,
            integration=integration,
            website=website or (integration.website if integration else None),
            detail=detail or {}, ip_address=ip or None,
        )


# ══════════════════════════════════════════════════════════════════
#  RESOLVER
# ══════════════════════════════════════════════════════════════════

class Resolved:
    """
    Thamani moja pamoja na chanzo chake.

    source: live | cached | manual | unknown
    """

    __slots__ = ('value', 'source', 'as_of')

    def __init__(self, value=None, source='unknown', as_of=None):
        self.value = value
        self.source = source
        self.as_of = as_of

    def __bool__(self):
        return self.value is not None and self.value != ''

    def __str__(self):
        return '' if self.value is None else str(self.value)

    @property
    def is_live(self):
        return self.source in ('live', 'cached')

    @property
    def is_manual(self):
        return self.source == 'manual'

    @property
    def age_label(self):
        if not self.as_of:
            return ''
        secs = (timezone.now() - self.as_of).total_seconds()
        if secs < 120:
            return 'sasa hivi'
        if secs < 3600:
            return f'dakika {int(secs // 60)} zilizopita'
        if secs < 86400:
            return f'saa {int(secs // 3600)} zilizopita'
        return f'siku {int(secs // 86400)} zilizopita'


class ResolverMixin:
    """
    Inaongezwa kwenye ManagedWebsite.

    Mnyororo:  live → cached (snapshot) → manual → unknown

    Data ya mkono HAIPOTEI. Inabaki kama ngazi ya mwisho, na kila
    thamani inabeba chanzo chake ili UI ionyeshe ukweli.
    """

    # canonical key → mahali pa kupata data ya mkono
    MANUAL_SOURCES = {
        'hosting_status':   ('self', 'status'),
        'server_region':    ('hosting_config', 'server_location'),
        'ssl_expiry_date':  ('hosting_config', 'ssl_expiry_date'),
        'ssl_issuer':       ('hosting_config', 'ssl_issuer'),
        'monthly_visits':   ('hosting_config', 'monthly_visits'),
        'last_backup':      ('hosting_config', 'last_backup'),
        'db_size_bytes':    ('hosting_config', None),
        'domain_expiry':    ('domain', 'expiry_date'),
        'domain_registrar': ('domain', 'registrar'),
        'domain_auto_renew': ('domain', 'auto_renew'),
    }

    def active_integrations(self):
        """Integrations hai. Inatumia prefetch_related('integrations') ikiwepo —
        orodha ya /manage/infra/ ilikuwa ikiuliza database kwa kila tovuti."""
        pre = getattr(self, '_prefetched_objects_cache', {}).get('integrations')
        if pre is not None:
            return [i for i in pre if i.is_active]
        return list(self.integrations.filter(is_active=True))

    def resolve(self, field):
        from .integration_models import STALE_AFTER  # self-import kwa uwazi

        # 1 & 2 — live au snapshot
        for integ in self.active_integrations():
            if integ.cached_summary and not integ.sync_error:
                val = integ.cached_summary.get(field)
                if val is not None and val != '':
                    age = timezone.now() - (integ.last_synced_at or timezone.now())
                    src = 'cached' if age > STALE_AFTER else 'live'
                    return Resolved(val, src, integ.last_synced_at)

            snap = (integ.snapshots
                    .filter(metrics__has_key=field)
                    .order_by('-checked_at').first())
            if snap:
                val = snap.metrics.get(field)
                if val is not None and val != '':
                    return Resolved(val, 'cached', snap.checked_at)

        # 3 — ya mkono
        return self._manual(field)

    def _manual(self, field):
        where, attr = self.MANUAL_SOURCES.get(field, (None, None))
        if not where or not attr:
            return Resolved(None, 'unknown', None)

        obj = None
        if where == 'self':
            obj = self
        elif where == 'hosting_config':
            obj = getattr(self, 'hosting_config', None)
        elif where == 'domain':
            obj = self.domains.first()

        if obj is None:
            return Resolved(None, 'unknown', None)

        val = getattr(obj, attr, None)
        if val in (None, ''):
            return Resolved(None, 'unknown', None)

        return Resolved(val, 'manual', getattr(obj, 'updated_at', None))

    def resolve_all(self, *fields):
        return {f: self.resolve(f) for f in fields}

    @property
    def integration_health(self):
        """ok | stale | error | none — kwa nukta ya rangi kwenye orodha."""
        rows = self.active_integrations()
        if not rows:
            return 'none'
        states = {r.health for r in rows}
        for bad in ('error', 'stale'):
            if bad in states:
                return bad
        return 'ok'

    def uptime_percent(self, days=30):
        """Kutoka snapshots halisi. None kama hakuna data ya kutosha."""
        since = timezone.now() - timedelta(days=days)
        snaps = IntegrationSnapshot.objects.filter(
            integration__website=self,
            integration__provider='render',
            checked_at__gte=since,
        ).values_list('metrics', flat=True)

        total = up = 0
        for m in snaps:
            status = (m or {}).get('hosting_status')
            if status in (None, ''):
                continue
            total += 1
            if status in ('online', 'building'):
                up += 1

        if total < 10:
            return None
        return round(up * 100.0 / total, 2)
