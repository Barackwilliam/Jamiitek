"""
LiveConfig — inajifanya kama HostingConfiguration, ila inasoma live kwanza.

Sababu ya muundo huu: template `portal/hosting_config.html` inatumia
`{{ cfg.ssl_expiry_date }}`, `{{ cfg.uptime_percent }}` n.k. Badala ya
kuandika upya template nzima, tunabadilisha `cfg` peke yake kwenye view.
Template inabaki ilivyo; data inakuwa halisi.

MNYORORO:  live → snapshot → mkono → (kificha)

Fields za kubuni (`197.250.10.1`, `ftp.jamiitek.com`, n.k.) hazionyeshwi
kwa mteja isipokuwa umezibadilisha mwenyewe kuwa za kweli. Kuonyesha
FTP host isiyokuwepo kunamchanganya mteja na kunaharibu uaminifu.
"""
from functools import cached_property
import logging
from datetime import date, datetime

from django.utils import timezone

from . import integrations as _  # noqa: F401  (kuhakikisha registry imepakiwa)
from .integrations import base

logger = logging.getLogger(__name__)


# HostingConfiguration attr → canonical key
LIVE_MAP = {
    'server_location':  base.SERVER_REGION,
    'ssl_expiry_date':  base.SSL_EXPIRY,
    'ssl_issuer':       base.SSL_ISSUER,
    'monthly_visits':   base.MONTHLY_VISITS,
    'last_backup':      base.LAST_BACKUP,
    'db_engine':        'db_status',
}

# Thamani za kubuni zilizowekwa kama default kwenye model.
# Zikiwa bado hivi, hazijawahi kuwekwa data ya kweli → zifichwe.
FABRICATED = {
    'ip_address':      '197.250.10.1',
    'server_hostname': 'srv1.jamiitek.com',
    'ftp_host':        'ftp.jamiitek.com',
    'db_host':         'db.jamiitek.com',
    'server_location': 'Dar es Salaam, Tanzania',
}

# Render region code → jina la kuonyesha (bila kutaja Render)
REGIONS = {
    'oregon':    'US West',
    'ohio':      'US East',
    'virginia':  'US East',
    'frankfurt': 'Europe (Frankfurt)',
    'singapore': 'Asia (Singapore)',
}

STATUS_LABEL = {
    'online':    ('ONLINE',      '#00ff88'),
    'building':  ('UPDATING',    '#ffb800'),
    'failed':    ('ISSUE',       '#ff3b5c'),
    'suspended': ('SUSPENDED',   '#ff3b5c'),
}


def _as_date(value):
    """Kubadilisha ISO string kuwa date ili `|date:` ifanye kazi."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _human_bytes(n):
    """1234567 → '1.2 MB'"""
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit in ('B', 'KB') else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


class LiveConfig:
    """
    Wrapper juu ya HostingConfiguration.

    Kila attribute inapitia `resolve()` kwanza. Isiyopatikana live
    inarudi kwenye ya mkono. Ya kubuni inafichwa.
    """

    DATE_FIELDS = {'ssl_expiry_date', 'last_backup'}

    def __init__(self, website, cfg=None):
        self._website = website
        self._cfg = cfg
        self._cache = {}
        self._sources = {}

    # ── kiini ──
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self._cache:
            return self._cache[name]

        value = self._compute(name)
        self._cache[name] = value
        return value

    def _compute(self, name):
        # 0. hali ya hosting — ina njia yake kwa sababu ya live_status
        if name == 'hosting_status':
            r = self._website.resolve(base.HOSTING_STATUS)
            self._sources[name] = r.source
            return r.value

        # 1. uptime — kutoka snapshots halisi pekee
        if name == 'uptime_percent':
            real = self._website.uptime_percent(30)
            self._sources[name] = 'live' if real is not None else 'unknown'
            return real   # None → template inaficha

        # 2. fields zenye chanzo live
        key = LIVE_MAP.get(name)
        if key:
            r = self._website.resolve(key)
            # thamani ya mkono inayotoka kwenye resolver bado inaweza kuwa
            # ya kubuni — lazima ipite kwenye filter ileile
            if r.source == 'manual' and self._is_fabricated(name, r.value):
                r = None
            if r is not None:
                self._sources[name] = r.source
                if r.value not in (None, ''):
                    val = r.value
                    if name == 'server_location':
                        val = REGIONS.get(str(val).lower(), val)
                    if name in self.DATE_FIELDS:
                        val = _as_date(val)
                    if val not in (None, ''):
                        return val

        # 3. ya mkono kutoka HostingConfiguration
        if self._cfg is None:
            self._sources.setdefault(name, 'unknown')
            return None

        try:
            val = getattr(self._cfg, name)
        except AttributeError:
            self._sources.setdefault(name, 'unknown')
            return None

        # 4. ficha za kubuni ambazo hazijaguswa
        if self._is_fabricated(name, val):
            self._sources[name] = 'unknown'
            return None

        self._sources.setdefault(name, 'manual')
        return val

    @staticmethod
    def _is_fabricated(name, value):
        return name in FABRICATED and value == FABRICATED[name]

    # ── hali halisi ya hosting (si ya bili) ──
    @cached_property
    def live_status(self):
        """
        online | building | failed | suspended | unknown

        MUHIMU: hii ni tofauti na `website.status`, ambayo ni hali ya
        MALIPO. Site inaweza kuwa 'active' kwenye bili huku ikiwa chini.
        """
        r = self._website.resolve(base.HOSTING_STATUS)
        if r.source in ('live', 'cached') and r.value in STATUS_LABEL:
            return r.value
        if self._website.status in ('suspended', 'terminated'):
            return 'suspended'
        return 'unknown'

    @property
    def status_label(self):
        return STATUS_LABEL.get(self.live_status, ('CHECKING…', '#8e8e93'))[0]

    @property
    def status_color(self):
        return STATUS_LABEL.get(self.live_status, ('CHECKING…', '#8e8e93'))[1]

    @property
    def is_monitored(self):
        """Je kuna integration inayofanya kazi? Kwa kuonyesha 'live' badge."""
        return any(not i.sync_error for i in self._website.active_integrations())

    @property
    def last_synced_label(self):
        synced = [i for i in self._website.active_integrations() if i.last_synced_at]
        last = max(synced, key=lambda i: i.last_synced_at, default=None)
        if not last:
            return ''
        secs = (timezone.now() - last.last_synced_at).total_seconds()
        if secs < 120:
            return 'updated just now'
        if secs < 3600:
            return f'updated {int(secs // 60)} min ago'
        if secs < 86400:
            return f'updated {int(secs // 3600)}h ago'
        return f'updated {int(secs // 86400)}d ago'

    def source_of(self, name):
        getattr(self, name, None)
        return self._sources.get(name, 'unknown')

    # ── properties zilizokuwa kwenye model ──
    @property
    def _live_bytes(self):
        """Jumla halisi: database + media. None kama hakuna chanzo."""
        total, found = 0, False
        for key in (base.DB_SIZE_BYTES, base.MEDIA_BYTES):
            r = self._website.resolve(key)
            if r.source in ('live', 'cached') and r.value:
                total += int(r.value)
                found = True
        return total if found else None

    @property
    def disk_used_gb(self):
        real = self._live_bytes
        if real is not None:
            return round(real / 1_000_000_000, 2)
        return getattr(self._cfg, 'disk_used_gb', None) if self._cfg else None

    @property
    def db_size_display(self):
        r = self._website.resolve(base.DB_SIZE_BYTES)
        if r.source in ('live', 'cached') and r.value:
            return _human_bytes(int(r.value))
        return ''

    @property
    def media_display(self):
        files = self._website.resolve(base.MEDIA_FILES)
        size = self._website.resolve(base.MEDIA_BYTES)
        if not files and not size:
            return ''
        parts = []
        if files.value:
            parts.append(f'{int(files.value):,} files')
        if size.value:
            parts.append(_human_bytes(int(size.value)))
        return ' · '.join(parts)

    @property
    def ssl_days_left(self):
        d = self.ssl_expiry_date
        if isinstance(d, date):
            return (d - timezone.now().date()).days
        return None

    @property
    def disk_percent(self):
        used, limit = self.disk_used_gb, self.disk_total_gb
        if used is None or not limit:
            return 0
        try:
            return round(float(used) / float(limit) * 100, 1)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0

    @property
    def bandwidth_percent(self):
        if self._cfg is None:
            return 0
        try:
            return self._cfg.bandwidth_percent
        except (TypeError, ValueError):
            return 0

    def __bool__(self):
        return self._cfg is not None or self.is_monitored


def live_config(website):
    """Rudisha LiveConfig, hata kama HostingConfiguration haipo."""
    cfg = getattr(website, 'hosting_config', None)
    return LiveConfig(website, cfg)
