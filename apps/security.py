"""
Ulinzi wa jumla wa mfumo (apps/security.py).

1. Kuzuia kubahatisha nywila (brute force) — kwa logins ZOTE:
   Client Portal, JamiiBot, Web Builder, /manage/ na /admin/. Zote zinapitia
   `django.contrib.auth.authenticate(request, ...)`, kwa hiyo ulinzi uko
   kwenye authentication backend moja badala ya kila view.
     • Akaunti moja: makosa 5 ndani ya dakika 15 → imefungwa dakika 15
     • IP moja:      makosa 30 ndani ya dakika 15 → imefungwa dakika 15
     • Staff, kwa KIFAA: makosa 3 → login ya akaunti hiyo kwenye kifaa hicho
       inafungwa dakika 30 (vifaa vingine vya staff havifungwi). Inahusu
       /manage/login/ na /admin/login/ (username yoyote), na akaunti ya staff
       inapoingia popote pengine (mfano Client Portal). Kifaa = cookie
       `jt_device`; bila cookie, IP ndiyo kifaa.
   Hata nywila sahihi inakataliwa wakati imefungwa, kwa hiyo mshambulizi
   hawezi kujua kama amepata nywila.

2. Security headers za ziada (SecurityHeadersMiddleware): Permissions-Policy,
   CSP ya msingi isiyovunja inline styles,
   na `Cache-Control: no-store` kwa kurasa za mtu aliyeingia (ili kitufe cha
   "Back" kwenye kompyuta ya pamoja kisionyeshe data baada ya logout).
"""
import hashlib
import logging
import secrets
import time

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver

from apps.turnstile import get_client_ip

log = logging.getLogger('apps.security')

WINDOW_SECONDS = 15 * 60
MAX_PER_ACCOUNT = 5
MAX_PER_IP = 30

# Staff: makosa 3 kwenye kifaa kimoja → kifaa hicho kinafungwa dakika 30 kwa akaunti hiyo
STAFF_DEVICE_MAX = 3
STAFF_DEVICE_LOCK_SECONDS = 30 * 60
STAFF_LOGIN_PATHS = ('/manage/login/', '/admin/login/')
DEVICE_COOKIE = 'jt_device'
DEVICE_COOKIE_AGE = 2 * 365 * 24 * 3600
_LOGIN_PAGES = STAFF_LOGIN_PATHS + ('/portal/login/',)


def _key(kind, value):
    digest = hashlib.sha256(str(value or '').strip().lower().encode()).hexdigest()[:32]
    return f'sec:login:{kind}:{digest}'


def _keys(request, username):
    keys = []
    if username:
        keys.append((_key('user', username), MAX_PER_ACCOUNT))
    ip = get_client_ip(request) if request is not None else None
    if ip:
        keys.append((_key('ip', ip), MAX_PER_IP))
    return keys


# ── Staff: kufunga kwa kifaa ──────────────────────────────────────

def device_id(request):
    """Kitambulisho cha kifaa: cookie `jt_device`, au IP kama cookie haipo."""
    if request is None:
        return ''
    dev = (request.COOKIES.get(DEVICE_COOKIE) or '').strip()
    if dev:
        return 'c:' + dev[:64]
    ip = get_client_ip(request)
    return 'ip:' + ip if ip else ''


def _is_staff_username(username):
    if not username:
        return False
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()
    return User.objects.filter(**{f'{User.USERNAME_FIELD}__iexact': username.strip()}, is_active=True) \
        .filter(Q(is_staff=True) | Q(is_superuser=True)).exists()


def staff_device_rule_applies(request, username):
    """Sheria ya kifaa inahusu kurasa za login za staff (username yoyote — ili ujumbe usifichue
    kama akaunti ipo), na akaunti ya staff inapoingia kwenye login nyingine."""
    if request is None or not username:
        return False
    if request.path in STAFF_LOGIN_PATHS:
        return True
    return _is_staff_username(username)


def _device_keys(request, username):
    pair = f'{(username or "").strip().lower()}|{device_id(request)}'
    return _key('sdev', pair), _key('sdevlock', pair)


def staff_device_locked_until(request, username):
    """Muda (timestamp) ambao kifaa hiki kitafunguliwa kwa akaunti hii, au None."""
    if not device_id(request):
        return None
    _, lock_key = _device_keys(request, username)
    until = cache.get(lock_key)
    if until and until > time.time():
        return until
    return None


def _count_staff_device_failure(request, username):
    count_key, lock_key = _device_keys(request, username)
    cache.add(count_key, 0, STAFF_DEVICE_LOCK_SECONDS)
    try:
        count = cache.incr(count_key)
    except ValueError:
        cache.set(count_key, 1, STAFF_DEVICE_LOCK_SECONDS)
        count = 1
    if request is not None:
        request.login_attempts_left = max(STAFF_DEVICE_MAX - count, 0)
    if count >= STAFF_DEVICE_MAX:
        until = time.time() + STAFF_DEVICE_LOCK_SECONDS
        cache.set(lock_key, until, STAFF_DEVICE_LOCK_SECONDS)
        cache.delete(count_key)
        if request is not None:
            request.login_locked = True
            request.login_locked_device = True
            request.login_locked_until = until
        log.warning('Staff device lockout started (30 min): user=%r device=%s ip=%s',
                    username, device_id(request)[:12], get_client_ip(request))


def clear_staff_device_lock(request, username):
    """Ondoa kufuli na hesabu ya kifaa hiki kwa akaunti hii (mfano baada ya kubadilisha nywila)."""
    if username and device_id(request):
        cache.delete_many(list(_device_keys(request, username)))


def login_locked(request, username):
    """True kama akaunti au IP hii imefungwa kwa muda kwa makosa mengi."""
    for key, limit in _keys(request, username):
        if (cache.get(key) or 0) >= limit:
            return True
    return False


def lockout_message(request=None):
    if request is not None and getattr(request, 'login_locked_device', False):
        mins = 30
        until = getattr(request, 'login_locked_until', None)
        if until:
            mins = max(1, int((until - time.time() + 59) // 60))
        return (f'Too many incorrect attempts on this device. For your security, signing in '
                f'from this device is locked for {mins} minute{"s" if mins != 1 else ""}. '
                'Try again later, or reset your password at /account/password-reset/.')
    return ('Too many failed sign-in attempts. For your security this account '
            'is locked for 15 minutes. Try again later, or reset your password at '
            '/account/password-reset/ to unlock it now.')


def attempts_left_message(request):
    """Onyo la kabla ya kufungwa (staff): "1 attempt left …". None kama halihitajiki."""
    left = getattr(request, 'login_attempts_left', None)
    if left is None or left <= 0 or left >= STAFF_DEVICE_MAX:
        return None
    return (f'{left} attempt{"s" if left != 1 else ""} left before sign-in from this device '
            'is locked for 30 minutes.')


class ThrottledModelBackend(ModelBackend):
    """ModelBackend ya kawaida + kufunga baada ya makosa mengi."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('username')
        if request is not None and staff_device_rule_applies(request, username):
            until = staff_device_locked_until(request, username)
            if until:
                request.login_locked = True
                request.login_locked_device = True
                request.login_locked_until = until
                log.warning('Login blocked (staff device locked): user=%r ip=%s',
                            username, get_client_ip(request))
                raise PermissionDenied
        if login_locked(request, username):
            if request is not None:
                request.login_locked = True
            log.warning('Login blocked (locked out): user=%r ip=%s',
                        username, get_client_ip(request))
            # PermissionDenied inasimamisha backends zote — hata nywila sahihi
            raise PermissionDenied
        return super().authenticate(request, username=username, password=password, **kwargs)


@receiver(user_login_failed)
def _count_failure(sender, credentials, request=None, **kwargs):
    if request is not None and getattr(request, 'login_locked', False):
        return
    username = (credentials or {}).get('username')
    if request is not None and staff_device_rule_applies(request, username):
        _count_staff_device_failure(request, username)
    for key, limit in _keys(request, username):
        # add() haiandiki juu ya kilichopo, kwa hiyo dirisha halirefushwi
        cache.add(key, 0, WINDOW_SECONDS)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, WINDOW_SECONDS)
            count = 1
        if count == limit:
            log.warning('Login lockout started: %s (user=%r ip=%s)',
                        key.split(':')[2], username, get_client_ip(request))


@receiver(user_logged_in)
def _reset_on_success(sender, request=None, user=None, **kwargs):
    if user is not None:
        cache.delete(_key('user', user.get_username()))
        if request is not None:
            cache.delete(_device_keys(request, user.get_username())[0])


# ── Security headers ─────────────────────────────────────────────
PERMISSIONS_POLICY = ', '.join([
    'accelerometer=()', 'autoplay=()', 'camera=()', 'display-capture=()',
    'geolocation=()', 'gyroscope=()', 'magnetometer=()', 'microphone=()',
    'midi=()', 'payment=(self)', 'usb=()', 'interest-cohort=()',
])

# CSP ya msingi: haizuii inline <style>/<script> (kurasa nyingi zinazitumia),
# lakini inazuia mbinu hatari zaidi za XSS: <base> ya kigeni, plugins
# (<object>/<embed>), na kutuma form kwenda http au javascript:.
CONTENT_SECURITY_POLICY = '; '.join([
    "base-uri 'self'",
    "object-src 'none'",
    "form-action 'self' https:",
    'upgrade-insecure-requests',
])

_PRIVATE_PREFIXES = ('/portal/', '/chatbot/', '/builder/', '/manage/', '/admin/')


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        response.headers.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        response.headers.setdefault('Content-Security-Policy', CONTENT_SECURITY_POLICY)

        # Kitambulisho cha kifaa kwa kufunga login ya staff kwa kifaa (si kwa akaunti nzima)
        if request.path in _LOGIN_PAGES and not request.COOKIES.get(DEVICE_COOKIE):
            response.set_cookie(DEVICE_COOKIE, secrets.token_urlsafe(18), max_age=DEVICE_COOKIE_AGE,
                                httponly=True, samesite='Lax', secure=request.is_secure())

        user = getattr(request, 'user', None)
        ctype = response.headers.get('Content-Type', '')
        if (user is not None and user.is_authenticated
                and request.path.startswith(_PRIVATE_PREFIXES)
                and ctype.startswith('text/html')):
            response.headers['Cache-Control'] = 'no-store, private'
        return response


def password_problems(password, username='', email='', full_name=''):
    """
    Makosa ya nywila kwa mujibu wa AUTH_PASSWORD_VALIDATORS (urefu, nywila
    za kawaida kama 'password123', namba tupu, kufanana na jina/email).
    Fomu za usajili za portal na JamiiBot hazikuyatumia — '12345678' ilikubaliwa.
    """
    from django.contrib.auth.models import User
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    parts = (full_name or '').split()
    probe = User(username=username or '', email=email or '',
                 first_name=parts[0] if parts else '',
                 last_name=' '.join(parts[1:]))
    try:
        validate_password(password or '', user=probe)
    except ValidationError as e:
        return list(e.messages)
    return []


def same_site_logout(view):
    """
    Logout kwa link (GET) inabaki kwa urahisi wa sidebar, lakini tovuti ya
    nje haiwezi tena kumtoa mtu kwa <img src=".../logout/"> (login-CSRF /
    phishing). Browsers zote za kisasa zinatuma `Sec-Fetch-Site`.
    """
    from functools import wraps
    from django.shortcuts import redirect

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method != 'POST' and request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return redirect('/')
        return view(request, *args, **kwargs)
    return wrapper
