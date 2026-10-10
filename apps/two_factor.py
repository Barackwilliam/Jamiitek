"""
2FA kwa akaunti za STAFF (apps/two_factor.py).

Nywila peke yake ikivuja (phishing, kifaa kilichoambukizwa, nywila
iliyotumika tovuti nyingine), mshambulizi angeingia /manage/ na /admin/ na
kudhibiti malipo, tovuti na bots za wateja wote. Sasa staff anahitaji pia
code ya tarakimu 6 kutoka app ya simu (Google Authenticator, Microsoft
Authenticator, Authy, 1Password...).

• TOTP (RFC 6238) — imeandikwa kwa stdlib, hakuna dependency mpya.
• Siri imesimbwa kwenye database (Fernet, key kutoka SECRET_KEY).
• Code moja haitumiki mara mbili (replay), makosa 5 → anatolewa nje.
• Recovery codes 8 za matumizi moja, zinahifadhiwa kama sha256 tu.
• Simu ikipotea na recovery codes hazipo:
      python manage.py reset_staff_2fa <username>   (Render → Shell)

Middleware inamlazimisha kila staff aliyeingia kupitia 2FA kabla ya
ukurasa wowote (si /manage/ tu — staff anaweza kuingia kupitia login yoyote).
Zima kwa dharura kwa env STAFF_2FA_REQUIRED=False.
"""
import base64
import hashlib
import hmac
import io
import logging
import os
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in
from django.core.cache import cache
from django.dispatch import receiver
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

log = logging.getLogger('apps.security')

SESSION_FLAG = 'staff_2fa_ok'
ISSUER = 'JamiiTek'
STEP = 30
DIGITS = 6
MAX_FAILS = 5
RECOVERY_COUNT = 8


# ── TOTP ─────────────────────────────────────────────────────────
def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def _b32(secret):
    s = secret.upper().replace(' ', '')
    return base64.b32decode(s + '=' * (-len(s) % 8))


def totp_at(secret, step):
    digest = hmac.new(_b32(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = (struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def match_step(secret, code, now=None, window=1):
    """Hatua ya muda ambayo code inalingana nayo (±30s kwa saa za simu), au None."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = int((now if now is not None else time.time()) // STEP)
    for step in range(now_step - window, now_step + window + 1):
        if hmac.compare_digest(totp_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret, account):
    label = quote(f'{ISSUER}:{account}')
    return (f'otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}'
            f'&algorithm=SHA1&digits={DIGITS}&period={STEP}')


def qr_svg(data):
    """QR kama SVG (inline) — qrcode iko tayari kwenye requirements."""
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.find('<svg'):]


# ── Usimbaji wa siri ─────────────────────────────────────────────
def _fernet():
    from cryptography.fernet import Fernet
    key = hashlib.sha256((settings.SECRET_KEY + ':staff-2fa').encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(secret):
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token):
    try:
        return _fernet().decrypt((token or '').encode()).decode()
    except Exception:
        return None


# ── Recovery codes ───────────────────────────────────────────────
def _hash_code(code):
    clean = ''.join(ch for ch in str(code).lower() if ch.isalnum())
    return hashlib.sha256(('jt2fa:' + clean).encode()).hexdigest()


def new_recovery_codes():
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = ''.join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f'{raw[:5]}-{raw[5:]}')
    return codes


# ── Msaada ───────────────────────────────────────────────────────
def required_for(user):
    on = os.getenv('STAFF_2FA_REQUIRED', 'True').lower() not in ('0', 'false', 'no')
    return bool(on and user.is_authenticated and (user.is_staff or user.is_superuser))


def _record(user):
    from apps.security_models import StaffTwoFactor
    return StaffTwoFactor.objects.filter(user=user).first()


NEXT_KEY = 'staff_2fa_next'


def _safe_next(request, default='/manage/'):
    """Ukurasa wa kurudi baada ya 2FA. Unakaa kwenye session, si kwenye URL,
    ili anwani ya ukurasa isionyeshe akaunti inaelekea wapi."""
    nxt = request.session.get(NEXT_KEY) or ''
    if nxt.startswith('/') and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default


def _already_verified_elsewhere(request):
    """Je ombi jingine (la wakati huo huo) limeshaweka alama ya 2FA kwenye session hii?"""
    from importlib import import_module
    from django.conf import settings as dj
    key = request.session.session_key
    if not key:
        return False
    fresh = import_module(dj.SESSION_ENGINE).SessionStore(session_key=key)
    return fresh.get(SESSION_FLAG) == request.user.pk


def _go_next(request):
    nxt = _safe_next(request)
    request.session.pop(NEXT_KEY, None)
    return redirect(nxt)


def _fail_key(user):
    return f'sec:2fa:fail:{user.pk}'


def _register_failure(request):
    """True kama makosa yamefika kikomo (mtumiaji ametolewa nje)."""
    key = _fail_key(request.user)
    cache.add(key, 0, 300)
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 300)
        n = 1
    if n >= MAX_FAILS:
        log.warning('2FA: makosa %d kwa %s — ametolewa nje', n, request.user)
        cache.delete(key)
        logout(request)
        from django.contrib import messages
        messages.error(request, 'Too many wrong verification codes. You have been signed out for '
                                'security — sign in again to retry.')
        return True
    return False


def _pass(request, rec):
    rec.last_used_at = timezone.now()
    rec.save(update_fields=['last_step', 'recovery_hashes', 'last_used_at'])
    cache.delete(_fail_key(request.user))
    # HAKUNA cycle_key hapa: login() ilishabadilisha session kwenye hatua ya
    # nywila. Kubadilisha tena kulifuta session ya zamani — code ikitumwa mara
    # mbili (auto-submit + Enter), ombi la pili lilikuta session imefutwa,
    # likamtoa mtumiaji nje, na akarudishwa login → 2FA → login bila mwisho.
    request.session[SESSION_FLAG] = request.user.pk


@receiver(user_logged_in)
def _reset_flag_on_login(sender, request=None, user=None, **kwargs):
    if request is not None and hasattr(request, 'session'):
        request.session.pop(SESSION_FLAG, None)


# ── Middleware ───────────────────────────────────────────────────
_EXEMPT_PREFIXES = (
    '/account/2fa/', '/account/password-reset/', '/account/sign-out/', '/account/help/',
    '/chatbot/privacy-policy/', '/static/', '/media/', '/favicon',
    '/manage/logout/', '/portal/logout/', '/chatbot/logout/', '/builder/logout/',
    '/admin/logout/', '/robots.txt', '/manifest.json', '/sw.js',
)


class StaffTwoFactorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (user is not None and required_for(user)
                and request.session.get(SESSION_FLAG) != user.pk
                and not request.path.startswith(_EXEMPT_PREFIXES)):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' \
                    or request.content_type == 'application/json':
                from django.http import JsonResponse
                return JsonResponse({'error': 'Two-factor verification required.'}, status=401)
            rec = _record(user)
            target = '/account/2fa/' if (rec and rec.confirmed) else '/account/2fa/setup/'
            request.session[NEXT_KEY] = request.get_full_path() if request.method == 'GET' else '/manage/'
            return redirect(target)
        return self.get_response(request)


# ── Views ────────────────────────────────────────────────────────
def _staff_or_login(request):
    if not request.user.is_authenticated:
        return redirect('/manage/login/')
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('/')
    return None


def verify(request):
    """Hatua ya pili baada ya nywila."""
    bounce = _staff_or_login(request)
    if bounce:
        return bounce
    rec = _record(request.user)
    secret = decrypt(rec.secret_encrypted) if rec and rec.confirmed else None
    if not secret:
        return redirect('/account/2fa/setup/')
    if request.session.get(SESSION_FLAG) == request.user.pk:
        return _go_next(request)

    error = None
    mode = 'recovery' if request.GET.get('recovery') or request.POST.get('mode') == 'recovery' else 'code'
    if request.method == 'POST':
        ok = False
        if mode == 'recovery':
            h = _hash_code(request.POST.get('code', ''))
            if h in rec.recovery_hashes:
                rec.recovery_hashes = [x for x in rec.recovery_hashes if x != h]
                ok = True
                log.warning('2FA: recovery code imetumika na %s (zimebaki %d)',
                            request.user, len(rec.recovery_hashes))
        else:
            step = match_step(secret, request.POST.get('code'))
            if step is not None and step > rec.last_step:
                rec.last_step = step
                ok = True
            elif step is not None and _already_verified_elsewhere(request):
                # Ombi la pili la code ile ile (double submit) — la kwanza
                # limeshafaulu kwenye session hii; endelea bila kosa
                return _go_next(request)
        if ok:
            _pass(request, rec)
            return _go_next(request)
        if _register_failure(request):
            return redirect('/manage/login/')
        error = ('That recovery code is not valid or was already used.' if mode == 'recovery'
                 else 'That code is not valid. Check the time on your phone and try again.')

    return render(request, 'account/two_factor_verify.html', {
        'mode': mode, 'error': error, 'remaining': len(rec.recovery_hashes),
    })


def setup(request):
    """Kuunganisha app ya authenticator (mara ya kwanza, au baada ya reset)."""
    bounce = _staff_or_login(request)
    if bounce:
        return bounce
    from apps.security_models import StaffTwoFactor
    rec = _record(request.user)
    already = bool(rec and rec.confirmed and decrypt(rec.secret_encrypted))
    if already and request.session.get(SESSION_FLAG) != request.user.pk:
        # Kubadilisha simu kunahitaji kwanza kuthibitisha kwa code ya sasa
        request.session[NEXT_KEY] = '/account/2fa/setup/'
        return redirect('/account/2fa/')

    # Siri ya muda inakaa kwenye session mpaka code ya kwanza ithibitishwe
    pending = request.session.get('staff_2fa_pending')
    if not pending or request.GET.get('new'):
        pending = new_secret()
        request.session['staff_2fa_pending'] = pending

    error = None
    if request.method == 'POST':
        step = match_step(pending, request.POST.get('code'))
        if step is None:
            if _register_failure(request):
                return redirect('/manage/login/')
            error = 'That code does not match. Scan the QR again and enter the newest 6-digit code.'
        else:
            codes = new_recovery_codes()
            rec = rec or StaffTwoFactor(user=request.user)
            rec.secret_encrypted = encrypt(pending)
            rec.confirmed = True
            rec.confirmed_at = timezone.now()
            rec.last_step = step
            rec.recovery_hashes = [_hash_code(c) for c in codes]
            rec.save()
            request.session.pop('staff_2fa_pending', None)
            _pass(request, rec)
            log.warning('2FA: imewashwa kwa %s', request.user)
            nxt = _safe_next(request)
            request.session.pop(NEXT_KEY, None)
            if nxt.startswith('/account/2fa/'):
                nxt = '/manage/'
            return render(request, 'account/two_factor_codes.html', {
                'codes': codes, 'next': nxt, 'fresh_setup': True,
            })

    account = request.user.email or request.user.username
    uri = provisioning_uri(pending, account)
    groups = [pending[i:i + 4] for i in range(0, len(pending), 4)]
    return render(request, 'account/two_factor_setup.html', {
        'qr': qr_svg(uri), 'secret_groups': groups, 'error': error, 'replacing': already,
    })


def recovery_codes(request):
    """Tengeneza recovery codes mpya (za zamani zinabatilika)."""
    bounce = _staff_or_login(request)
    if bounce:
        return bounce
    rec = _record(request.user)
    if not rec or not rec.confirmed:
        return redirect('/account/2fa/setup/')
    if request.method != 'POST':
        return render(request, 'account/two_factor_codes.html', {
            'codes': None, 'remaining': len(rec.recovery_hashes), 'next': '/manage/',
        })
    codes = new_recovery_codes()
    rec.recovery_hashes = [_hash_code(c) for c in codes]
    rec.save(update_fields=['recovery_hashes'])
    log.warning('2FA: recovery codes mpya kwa %s', request.user)
    return render(request, 'account/two_factor_codes.html', {'codes': codes, 'next': '/manage/'})


def sign_out(request):
    """Kutoka bila kufichua ni sehemu gani ya mfumo (inatumiwa na kurasa za 2FA)."""
    from django.http import HttpResponseNotAllowed
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    logout(request)
    return redirect('/')
