"""
Kuendesha kazi za ratiba BILA cron ya nje (Render FREE, bila GitHub Actions).

Jinsi inavyofanya kazi:
  Mtu yeyote akifungua tovuti, middleware inaangalia kama kuna kazi
  iliyofika muda wake. Kama ipo, inaanzisha thread ya nyuma
  inayoifanya — mtumiaji haoni ucheleweshaji hata kidogo.

RATIBA (kila kazi ina alama yake ya cache, hazitegemeani):

  | Kazi                       | Kila        |
  |----------------------------|-------------|
  | sync_integrations          | dakika 15   |
  | process_scheduled_actions  | dakika 15   |
  | check_alerts               | dakika 30   |
  | check_bot_sessions         | dakika 10   |
  | check_handoffs             | dakika 10   |
  | wafanyakazi (timu ya AI)   | dakika 30   |
  | auto_suspend               | siku        |
  | send_expiry_emails         | siku        |
  | send_digest                | siku        |
  | prune_site_imports         | siku        |
  | prune_snapshots            | siku 7      |
  | prune_baileys_keys         | siku 7      |
  | cluster_gaps               | siku 7      |
  | chatbot_digest             | siku 7      |
  | monthly_report --all       | siku 30     |

Usalama:
  • Kila kazi inaweka alama MARA MOJA kabla ya kuanza, kwa hiyo maombi 100
    yanayoingia pamoja hayatafungua kazi 100.
  • Kila kazi iko ndani ya try/except yake — moja ikishindwa, nyingine
    zinaendelea, na ombi la mtumiaji halivunjiki kamwe.
  • MPANGILIO NI WA MAKUSUDI kwenye kazi za kila siku: `auto_suspend`
    inatangulia kwa sababu ndiyo yenye ujumbe wa AI na maintenance mode.
    `send_bulk_expiry_warnings` inafuata — inakuta tovuti zilizokwisha
    simamishwa (haiziguse tena, inachuja status='active') na inashughulikia
    email hosting, domains, na onyo za siku 7/3/1.

MUHIMU: kwenye production hii inategemea cache ya pamoja (REDIS_URL).
Bila Redis, kila worker wa gunicorn ana LocMemCache yake — kazi zitarudiwa
mara moja kwa kila worker.
"""
import logging
import threading
import time
from datetime import date, datetime

from django.core.cache import cache
from django.db import connection

logger = logging.getLogger(__name__)

# Alama ya kazi za kila siku — jina la zamani limehifadhiwa kwa sababu
# management_views.daily_tasks_endpoint inaitumia.
CACHE_KEY = 'jamiitek:daily_tasks:last_run'
CACHE_TTL = 60 * 60 * 30          # saa 30 — inatosha siku moja

MINUTE = 60

# jina -> (funguo ya cache, sekunde kati ya mizunguko)
SCHEDULE = {
    'sync_integrations':         ('jamiitek:task:sync_integrations',   15 * MINUTE),
    'process_scheduled_actions': ('jamiitek:task:scheduled_actions',   15 * MINUTE),
    'check_alerts':              ('jamiitek:task:check_alerts',        30 * MINUTE),
    'check_bot_sessions':        ('jamiitek:task:bot_sessions',        10 * MINUTE),
    'check_handoffs':            ('jamiitek:task:handoffs',            10 * MINUTE),
    'check_custom_domains':      ('jamiitek:task:custom_domains',      15 * MINUTE),
    'wafanyakazi':               ('jamiitek:task:wafanyakazi',         30 * MINUTE),
    'send_digest':               ('jamiitek:task:send_digest',         24 * 60 * MINUTE),
    'prune_site_imports':        ('jamiitek:task:prune_site_imports',  24 * 60 * MINUTE),
    'prune_snapshots':           ('jamiitek:task:prune_snapshots',      7 * 24 * 60 * MINUTE),
    'prune_baileys_keys':        ('jamiitek:task:prune_baileys',        7 * 24 * 60 * MINUTE),
    'cluster_gaps':              ('jamiitek:task:cluster_gaps',         7 * 24 * 60 * MINUTE),
    'chatbot_digest':            ('jamiitek:task:chatbot_digest',       7 * 24 * 60 * MINUTE),
    'monthly_report':            ('jamiitek:task:monthly_report',      30 * 24 * 60 * MINUTE),
}

PERIODIC = ('sync_integrations', 'process_scheduled_actions', 'check_alerts',
            'check_bot_sessions', 'check_handoffs', 'check_custom_domains', 'wafanyakazi')

_thread_lock = threading.Lock()
_running = False           # kazi za kila siku
_running_periodic = False  # kazi za mara kwa mara

# Ukaguzi wa ratiba unafanyika mara moja kwa dakika kwa kila process, si
# kila ombi. Bila Redis cache ni ya database (Supabase), kwa hiyo kila
# ukurasa ulikuwa ukilipa maswali 8 ya ziada kwa ukaguzi huu tu.
CHECK_EVERY_SECONDS = 60
_last_check = 0.0


# ══════════════════════════════════════════════════════════════════
#  KAZI ZA KILA SIKU
# ══════════════════════════════════════════════════════════════════

def _run_tasks_in_background():
    """Kazi halisi za kila siku. Inaendeshwa kwenye thread ya nyuma."""
    global _running
    try:
        # 1. Auto-suspend — hii inatangulia (ujumbe wa AI + maintenance mode)
        try:
            from . import hosting_service
            report = hosting_service.run_auto_suspend(notify=True)
            n, m = len(report['suspended']), len(report['maintenance'])
            if n or m:
                logger.info('[daily] auto-suspend: %d suspended, %d maintenance', n, m)
        except Exception:
            logger.exception('[daily] auto-suspend failed')

        # 2. Onyo za muda kuisha + email hosting + domains
        try:
            from .utils.email_notifications import send_bulk_expiry_warnings
            result = send_bulk_expiry_warnings()
            logger.info('[daily] expiry emails: sent=%s suspended=%s errors=%s',
                        result.get('sent'), result.get('suspended'), result.get('errors'))
        except Exception:
            logger.exception('[daily] expiry emails failed')

        # 3. Kazi za ratiba ndefu (kila moja ina alama yake — haitarudiwa)
        _run_command('send_digest')
        _run_command('prune_snapshots')
        _run_command('prune_baileys_keys', quiet=True)
        _run_command('prune_site_imports', quiet=True)

        # MPANGILIO: kuunganisha KABLA ya muhtasari, ili orodha
        # inayotumwa WhatsApp iwe imeshasafishwa.
        _run_command('cluster_gaps', quiet=True)
        _run_command('chatbot_digest', quiet=True)
        _run_command('monthly_report', all=True)

    finally:
        # Muhimu: funga muunganisho wa database wa thread hii
        _close_connection()
        with _thread_lock:
            _running = False


# ══════════════════════════════════════════════════════════════════
#  KAZI ZA MARA KWA MARA (dakika 15 / 30)
# ══════════════════════════════════════════════════════════════════

def _run_periodic_in_background():
    """sync_integrations, scheduled actions, alerts."""
    global _running_periodic
    try:
        _run_command('sync_integrations', quiet=True)
        _run_command('process_scheduled_actions')
        _run_command('check_alerts')

        # Afya ya sessions za WhatsApp. Hii ndiyo iliyokosekana tarehe
        # 15 Sep: session ilikufa, dashboard ikaonyesha kijani, na
        # hakuna aliyejua kwa saa kadhaa.
        _run_command('check_bot_sessions', quiet=True)

        # Wateja wanaosubiri binadamu. `remind_owner_if_stale` inaita tu
        # mteja anapoandika tena — lakini ameambiwa "subiri", kwa hiyo
        # anasubiri kimya. Hii inakimbia kwa saa, si kwa ujumbe.
        _run_command('check_handoffs', quiet=True)

        # Domain za wateja zinazosubiri DNS/SSL. Mteja anapoweka DNS
        # usiku, website inakuwa Live bila mtu kubonyeza "Kagua".
        _run_command('check_custom_domains', quiet=True)

        # Timu ya wafanyakazi wa AI (apps/wafanyakazi). Wa mwisho kwa
        # sababu inaweza kuita AI — kazi za afya zisisubiri.
        _run_command('wafanyakazi')
    finally:
        _close_connection()
        with _thread_lock:
            _running_periodic = False


# ══════════════════════════════════════════════════════════════════
#  VISAIDIZI
# ══════════════════════════════════════════════════════════════════

def _close_connection():
    try:
        connection.close()
    except Exception:
        pass


def _due(name):
    """Je, kazi hii imefika muda? Ikiwa ndiyo, inaweka alama mara moja."""
    key, every = SCHEDULE[name]
    try:
        if cache.get(key):
            return False
        # TTL yenyewe ndiyo ratiba — funguo ikiisha, kazi inastahili tena
        cache.set(key, datetime.utcnow().isoformat(timespec='seconds'), every)
        return True
    except Exception:
        # Cache haipatikani — usifanye kitu badala ya kurudia kazi bila kikomo
        return False


def _run_command(name, **opts):
    """Endesha management command. Kamwe isivunje kazi nyingine."""
    if not _due(name):
        return False
    try:
        from django.core.management import call_command
        call_command(name, **opts)
        logger.info('[tasks] %s imekamilika', name)
        return True
    except Exception:
        logger.exception('[tasks] %s imeshindwa', name)
        return False


# ══════════════════════════════════════════════════════════════════
#  MIDDLEWARE
# ══════════════════════════════════════════════════════════════════

class DailyTasksMiddleware:
    """
    Inaendesha kazi za ratiba kwenye thread ya nyuma.

    Weka MWISHONI mwa MIDDLEWARE kwenye settings.py.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _last_check
        response = self.get_response(request)
        now = time.monotonic()
        if now - _last_check < CHECK_EVERY_SECONDS:
            return response
        _last_check = now
        try:
            self._maybe_run_daily()
            self._maybe_run_periodic()
        except Exception:
            # Kamwe isivunje ombi la mtumiaji
            logger.exception('[tasks] middleware check failed')
        return response

    # ── kila siku ──
    def _maybe_run_daily(self):
        global _running

        today = date.today().isoformat()

        try:
            last = cache.get(CACHE_KEY)
        except Exception:
            # Cache haipatikani (Redis imelala) — usifanye kitu leo
            return

        if last == today:
            return

        with _thread_lock:
            if _running:
                return
            _running = True

        # Weka alama KABLA ya kuanza — kuzuia maombi mengine kuanzisha kazi ile ile
        try:
            cache.set(CACHE_KEY, today, CACHE_TTL)
        except Exception:
            with _thread_lock:
                _running = False
            return

        threading.Thread(target=_run_tasks_in_background,
                         name='jamiitek-daily-tasks', daemon=True).start()
        logger.info('[daily] tasks started in background for %s', today)

    # ── dakika 15 / 30 ──
    def _maybe_run_periodic(self):
        global _running_periodic

        # Ruka kabisa kama hakuna kazi iliyofika muda — swali MOJA kwa zote
        try:
            keys = [SCHEDULE[n][0] for n in PERIODIC]
            found = cache.get_many(keys)
            pending = any(k not in found for k in keys)
        except Exception:
            return

        if not pending:
            return

        with _thread_lock:
            if _running_periodic:
                return
            _running_periodic = True

        threading.Thread(target=_run_periodic_in_background,
                         name='jamiitek-periodic-tasks', daemon=True).start()


def force_run_now():
    """Lazimisha kazi zote zifanyike sasa (kwa ajili ya kitufe cha 'Run now')."""
    global _last_check
    _last_check = 0.0   # ombi linalofuata likague mara moja
    for k in [CACHE_KEY] + [key for key, _ in SCHEDULE.values()]:
        try:
            cache.delete(k)
        except Exception:
            pass
