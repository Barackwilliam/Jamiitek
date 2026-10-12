# apps/receipt_confirm.py
"""
Mteja anathibitisha kupokea risiti — MARA MOJA tu, kupitia link ya risiti.

Njia kuu: alama ya kidole / Face ID / PIN ya simu (WebAuthn, kama passkeys).

  - Alama ya kidole HAITUFIKII kamwe. Browser inamwomba mteja afungue simu
    yake; simu inatutumia uthibitisho uliosainiwa kwamba mwenye kifaa
    amekifungua (flag ya "user verified"), pamoja na kitambulisho cha ufunguo.
  - Tunahifadhi: saa, IP, aina ya kifaa, na credential id. Hakuna biometric.
  - Inathibitisha KIFAA, si mtu. Ndiyo maana risiti inaandika
    "Confirmed on client's device", si "fingerprint verified".

Njia mbadala (simu ya zamani, au browser ya ndani ya WhatsApp isiyo na
WebAuthn): kuchora sahihi au kuandika jina — sawa na portal.

"Mara moja tu": uthibitisho unaandikwa kwa UPDATE yenye sharti
`signed_at IS NULL`. Maombi mawili kwa wakati mmoja — moja tu linashinda.
"""

import json
import secrets

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .receipt_models import DevelopmentReceipt

CHALLENGE_SECONDS = 300
MAX_DRAWN_BYTES = 400_000


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _receipt(token):
    return get_object_or_404(DevelopmentReceipt, token=token, is_published=True)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def device_label(user_agent):
    """'Android · Chrome', 'iPhone · Safari' … kwa kumbukumbu ya mwanadamu."""
    ua = user_agent or ''
    if 'iPhone' in ua:
        os_name = 'iPhone'
    elif 'iPad' in ua:
        os_name = 'iPad'
    elif 'Android' in ua:
        os_name = 'Android'
    elif 'Windows' in ua:
        os_name = 'Windows'
    elif 'Mac OS X' in ua or 'Macintosh' in ua:
        os_name = 'Mac'
    elif 'Linux' in ua:
        os_name = 'Linux'
    else:
        os_name = 'Device'

    if 'SamsungBrowser' in ua:
        browser = 'Samsung Internet'
    elif 'Edg/' in ua:
        browser = 'Edge'
    elif 'OPR/' in ua or 'Opera' in ua:
        browser = 'Opera'
    elif 'Firefox/' in ua or 'FxiOS' in ua:
        browser = 'Firefox'
    elif 'CriOS' in ua or 'Chrome/' in ua:
        browser = 'Chrome'
    elif 'Safari/' in ua:
        browser = 'Safari'
    else:
        browser = 'Browser'
    return f'{os_name} · {browser}'


def _rp(request):
    """Domain (rp_id) na origin vinavyotarajiwa — vinatoka kwenye ombi lenyewe,
    kwa hiyo vinafanya kazi kwa jamiitek.com, www.jamiitek.com na localhost."""
    host = request.get_host()
    return host.split(':')[0], f'{request.scheme}://{host}'


def _challenge_key(receipt):
    return f'receipt-confirm-challenge:{receipt.pk}'


def _mark_signed(receipt, request, **fields):
    """Andika uthibitisho MARA MOJA. Inarudisha False kama tayari umeshafanyika."""
    now = timezone.now()
    updated = DevelopmentReceipt.objects.filter(
        pk=receipt.pk, signed_at__isnull=True,
    ).update(
        signed_at=now,
        signed_ip=_client_ip(request),
        updated_at=now,           # toleo jipya la PDF — sasa ina uthibitisho
        **fields,
    )
    return updated == 1


def _done(receipt):
    from .receipt_views import receipt_pdf_url
    receipt.refresh_from_db()
    return JsonResponse({
        'ok': True,
        'pdf_url': receipt_pdf_url(receipt),
        'filename': receipt.filename,
        'label': receipt.signed_label,
        'when': timezone.localtime(receipt.signed_at).strftime('%d %b %Y, %H:%M'),
    })


def _already():
    return JsonResponse(
        {'ok': False, 'error': 'already',
         'message': 'This receipt has already been confirmed.'}, status=409)


# ══════════════════════════════════════════════════════════════
# 1. Alama ya kidole / Face ID — WebAuthn
# ══════════════════════════════════════════════════════════════
@require_POST
def confirm_options(request, token):
    """Hatua ya kwanza: server inatoa 'challenge' ya mara moja."""
    receipt = _receipt(token)
    if receipt.is_signed:
        return _already()

    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AttestationConveyancePreference, AuthenticatorAttachment,
        AuthenticatorSelectionCriteria, ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    rp_id, _origin = _rp(request)
    name = (receipt.client_name or receipt.subject_name or 'Client')[:64]
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name='JamiiTek',
        user_id=secrets.token_bytes(16),
        user_name=f'{receipt.receipt_number} · {name}'[:64],
        user_display_name=name,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Kifaa chenyewe (kidole/uso/PIN ya simu), si USB key
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            # LAZIMA mtu afungue simu — kugusa tu hakutoshi
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        timeout=90_000,
    )
    cache.set(_challenge_key(receipt), options.challenge, CHALLENGE_SECONDS)
    return JsonResponse(json.loads(options_to_json(options)))


@require_POST
def confirm_device(request, token):
    """Hatua ya pili: hakiki jibu la simu, kisha andika uthibitisho."""
    receipt = _receipt(token)
    if receipt.is_signed:
        return _already()

    challenge = cache.get(_challenge_key(receipt))
    if not challenge:
        return JsonResponse({'ok': False, 'error': 'expired',
                             'message': 'That took too long. Please try again.'}, status=400)

    from webauthn import verify_registration_response
    from webauthn.helpers import bytes_to_base64url

    rp_id, origin = _rp(request)
    try:
        verification = verify_registration_response(
            credential=request.body.decode('utf-8'),
            expected_challenge=challenge,
            expected_origin=origin,
            expected_rp_id=rp_id,
            require_user_verification=True,
        )
    except Exception:
        return JsonResponse({'ok': False, 'error': 'invalid',
                             'message': 'We could not confirm this device. '
                                        'Please try again or sign instead.'}, status=400)
    finally:
        cache.delete(_challenge_key(receipt))      # challenge ni ya mara moja

    if not verification.user_verified:
        return JsonResponse({'ok': False, 'error': 'not_verified',
                             'message': 'Your phone did not confirm it was you.'}, status=400)

    if not _mark_signed(
        receipt, request,
        signature_method='device',
        signature_device=device_label(request.META.get('HTTP_USER_AGENT'))[:160],
        signature_credential=bytes_to_base64url(verification.credential_id)[:255],
        signature_name=(receipt.client_name or '')[:160],
    ):
        return _already()
    return _done(receipt)


# ══════════════════════════════════════════════════════════════
# 2. Njia mbadala — kuchora sahihi au kuandika jina
# ══════════════════════════════════════════════════════════════
@require_POST
def confirm_sign(request, token):
    receipt = _receipt(token)
    if receipt.is_signed:
        return _already()

    drawn = (request.POST.get('signature_data') or '').strip()
    typed = (request.POST.get('signature_name') or '').strip()[:160]

    if drawn and not (drawn.startswith('data:image/png;base64,') and len(drawn) <= MAX_DRAWN_BYTES):
        drawn = ''
    if not drawn and len(typed) < 2:
        return JsonResponse({'ok': False, 'error': 'empty',
                             'message': 'Please sign or type your full name.'}, status=400)

    if not _mark_signed(
        receipt, request,
        signature_method='drawn' if drawn else 'typed',
        signature_data=drawn,
        signature_name=typed,
        signature_device=device_label(request.META.get('HTTP_USER_AGENT'))[:160],
    ):
        return _already()
    return _done(receipt)
