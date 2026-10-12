"""
Supabase Storage — mahali image zote za JamiiTek zinakaa.

FUNGUO: S3, SI service_role

`service_role` inafungua DATABASE YOTE — wateja, mazungumzo, invoice
— pamoja na Auth na Edge Functions. Inapitiliza Row Level Security
kabisa.

S3 access keys zinafungua STORAGE PEKEE. Ikivuja, mtu anapata image.
Haiwezi kugusa database.

Kwa funguo inayokaa Render ikiwa na kazi moja ya kupakia picha, S3
ndizo sahihi. Hiyo ni kanuni ya ruhusa ya chini kabisa.

Zinapatikana: Supabase > Storage > S3 Access Keys > New access key.

KWA NINI KUPITIA DJANGO NA SI MOJA KWA MOJA

Browser ingeweza kupakia moja kwa moja Supabase kwa signed URL, na
ingekuwa haraka zaidi. Lakini ingemaanisha funguo ikae kwenye JS, au
tuongeze hatua ya kuomba signed URL kila upload.

Kwa image za biashara ndogo (logo, picha za huduma, portfolio), file
inapita Django mara moja tu wakati wa kupakia. Baada ya hapo mteja
anasoma moja kwa moja kutoka CDN ya Supabase. Server yako haiguswi
tena.

Funguo ya `service_role` INABAKI SERVER. Kamwe isipelekwe browser —
inaweza kusoma na kufuta kila kitu kwenye storage yako.

MUUNDO WA MAJINA

    <folda>/<mwaka>/<mwezi>/<uuid>.<ext>

Mfano: services/2026/09/3f8a2b1c.jpg

UUID inazuia file mbili zenye jina moja kugongana, na inazuia mtu
kukisia URL za file za wengine. Mwaka/mwezi inarahisisha kusafisha
baadaye.
"""
import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from django.conf import settings

logger = logging.getLogger('jamiitek.storage')

TIMEOUT = 30

_client = None

# Aina zinazokubalika. Orodha ni fupi kwa makusudi — SVG haimo kwa
# sababu inaweza kubeba JavaScript, na image ya mteja inaonyeshwa
# kwenye tovuti ya mteja mwingine.
ALLOWED = {
    'image/jpeg': 'jpg',
    'image/png':  'png',
    'image/webp': 'webp',
    'image/gif':  'gif',
    'application/pdf': 'pdf',
}

MAX_BYTES = 10 * 1024 * 1024   # 10MB

# Saini ya bytes za mwanzo kwa kila aina — file la HTML lililopewa jina
# 'picha.png' halipiti, na halihifadhiwi kama text/html kwenye bucket.
_MAGIC = {
    'jpg':  (b'\xff\xd8\xff',),
    'png':  (b'\x89PNG\r\n\x1a\n',),
    'gif':  (b'GIF87a', b'GIF89a'),
    'pdf':  (b'%PDF-',),
}


def _content_matches(ext, data):
    if ext == 'webp':
        return data[:4] == b'RIFF' and data[8:12] == b'WEBP'
    sigs = _MAGIC.get(ext)
    return bool(sigs) and any(data.startswith(s) for s in sigs)


def _base():
    return (getattr(settings, 'SUPABASE_URL', '') or '').rstrip('/')


def _bucket():
    return getattr(settings, 'SUPABASE_BUCKET', 'media') or 'media'


def _access_key():
    return getattr(settings, 'SUPABASE_S3_ACCESS_KEY', '') or ''


def _secret_key():
    return getattr(settings, 'SUPABASE_S3_SECRET_KEY', '') or ''


def _region():
    return getattr(settings, 'SUPABASE_S3_REGION', 'us-east-1') or 'us-east-1'


def is_configured():
    return bool(_base() and _access_key() and _secret_key())


def _s3():
    """
    Mteja mmoja unaotumika tena. Kuunda mpya kwa kila upload ni
    gharama isiyo na sababu — boto3 inafungua muunganisho.
    """
    global _client
    if _client is not None:
        return _client
    _client = boto3.client(
        's3',
        endpoint_url=f"{_base()}/storage/v1/s3",
        aws_access_key_id=_access_key(),
        aws_secret_access_key=_secret_key(),
        region_name=_region(),
        config=Config(
            signature_version='s3v4',
            connect_timeout=10,
            read_timeout=TIMEOUT,
            retries={'max_attempts': 2},
        ),
    )
    return _client


def public_url(path):
    """URL ya kusoma. Bucket lazima iwe public."""
    if not path:
        return ''
    if path.startswith('http'):
        return path          # tayari ni URL kamili
    return f"{_base()}/storage/v1/object/public/{_bucket()}/{path.lstrip('/')}"


def _safe_ext(filename, content_type):
    """Kiendelezi kinachoaminika — kutoka content type, si jina la file."""
    ext = ALLOWED.get((content_type or '').lower().split(';')[0].strip())
    if ext:
        return ext
    guessed = mimetypes.guess_type(filename or '')[0]
    return ALLOWED.get(guessed or '', '')


def _safe_folder(folder):
    """
    Slash INARUHUSIWA — Builder inatumia `sites/<id>` ili kila tovuti
    iwe na folda yake. Lakini kila sehemu inasafishwa peke yake, kwa
    hiyo '..' haiwezi kupita na kutoka nje ya bucket.
    """
    parts = []
    for seg in (folder or 'media').lower().split('/'):
        seg = re.sub(r'[^a-z0-9_-]', '', seg)[:40]
        if seg and seg not in ('.', '..'):
            parts.append(seg)
        if len(parts) >= 3:          # kina cha kutosha; kinazuia kuzama
            break
    return '/'.join(parts) or 'media'


def build_path(folder, filename, content_type):
    ext = _safe_ext(filename, content_type)
    if not ext:
        return ''
    now = datetime.utcnow()
    return f"{_safe_folder(folder)}/{now:%Y/%m}/{uuid.uuid4().hex[:16]}.{ext}"


# ══════════════════════════════════════════════════════════════
#  KUBORESHA PICHA KABLA YA KUPAKIA
# ══════════════════════════════════════════════════════════════
#
# Picha za simu/kamera ni 3-8MB, 4000px. Supabase ya bure haibadilishi
# ukubwa (transformation ni ya plan ya kulipia), kwa hiyo picha ilifika
# kwa mteja ikiwa kubwa vilevile — kwenye data ya simu, ukurasa ulisubiri
# sekunde kadhaa. Sasa kila picha inapunguzwa MARA MOJA wakati wa kupakia:
#
#   - upande mrefu zaidi ≤ 2000px (inatosha hata hero ya skrini pana)
#   - inageuzwa WebP (ndogo kwa ~30-70% kuliko JPG/PNG kwa ubora uleule)
#   - EXIF inaondolewa — pamoja na GPS ya mahali picha ilipigwa
#   - mzunguko wa simu (EXIF orientation) unaheshimiwa
#
# Toleo jipya linatumika TU likiwa dogo kweli; vinginevyo la asili linabaki.
# GIF (inaweza kuwa na mwendo) na PDF haziguswi.
OPTIMIZE_MAX_SIDE = 2000
OPTIMIZE_QUALITY = 82
_OPTIMIZABLE = {'jpg', 'png', 'webp'}


def optimize_image(data, ext):
    """Inarudisha (data, ext). Haitupi kosa — ikishindwa, inarudisha ya asili."""
    if ext not in _OPTIMIZABLE or not data:
        return data, ext
    try:
        from io import BytesIO
        from PIL import Image, ImageOps

        img = Image.open(BytesIO(data))
        if getattr(img, 'is_animated', False) and getattr(img, 'n_frames', 1) > 1:
            return data, ext                        # mwendo — usiharibu
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA' if 'A' in img.getbands() or img.mode == 'P' else 'RGB')
        if max(img.size) > OPTIMIZE_MAX_SIDE:
            img.thumbnail((OPTIMIZE_MAX_SIDE, OPTIMIZE_MAX_SIDE), Image.LANCZOS)

        out = BytesIO()
        # Logo/picha zenye uwazi: ubora juu kidogo ili kingo zibaki safi
        quality = 90 if img.mode == 'RGBA' else OPTIMIZE_QUALITY
        img.save(out, format='WEBP', quality=quality, method=5)
        new = out.getvalue()
        if len(new) < len(data) * 0.9:
            return new, 'webp'
    except Exception:
        logger.warning('optimize_image failed; keeping original', exc_info=True)
    return data, ext


# ══════════════════════════════════════════════════════════════
#  KUPAKIA
# ══════════════════════════════════════════════════════════════

def upload(file_obj, folder='media', filename=None, content_type=None):
    """
    Inapakia file kwenda Supabase.

    Inarudisha dict: {'success': bool, 'url': str, 'path': str, 'error': str}
    Kamwe haitupi exception — inayeyusha kila kosa kuwa jibu.
    """
    if not is_configured():
        return {'success': False, 'error': 'SUPABASE_URL au funguo za S3 hazijawekwa'}

    filename = filename or getattr(file_obj, 'name', '') or 'file'
    content_type = content_type or getattr(file_obj, 'content_type', '') or ''

    size = getattr(file_obj, 'size', None)
    if size is not None and size > MAX_BYTES:
        return {'success': False,
                'error': f'File ni kubwa mno ({size // 1024 // 1024}MB). Kikomo ni 10MB.'}

    path = build_path(folder, filename, content_type)
    if not path:
        return {'success': False,
                'error': 'Aina ya file hairuhusiwi. Tumia JPG, PNG, WEBP, GIF au PDF.'}

    try:
        file_obj.seek(0)
    except Exception:
        pass

    try:
        data = file_obj.read()
    except Exception as e:
        return {'success': False, 'error': f'kusoma file kumeshindwa: {e}'}

    if len(data) > MAX_BYTES:
        return {'success': False,
                'error': f'File ni kubwa mno ({len(data) // 1024 // 1024}MB). Kikomo ni 10MB.'}

    ext = path.rsplit('.', 1)[-1]
    if not _content_matches(ext, data):
        return {'success': False,
                'error': 'File hili si picha/PDF halisi. Tumia JPG, PNG, WEBP, GIF au PDF.'}

    data, new_ext = optimize_image(data, ext)
    if new_ext != ext:
        path = path.rsplit('.', 1)[0] + '.' + new_ext
        ext = new_ext
    # Content-Type inatoka kwenye aina tuliyoithibitisha, si kwa browser
    canonical = {v: k for k, v in ALLOWED.items()}[ext]
    return _put(path, data, canonical)


def upload_bytes(data, folder, ext, content_type):
    """
    Pakia bytes ambazo aina yake IMESHAKAGULIWA na anayeita.

    Inatumiwa na ZIP import ya Builder, inayohitaji CSS, JS na fonts —
    aina ambazo `ALLOWED` haiziruhusu kwa upload za kawaida. Anayeita
    ndiye mwenye orodha yake ya aina salama (builder/site_import.py).
    """
    if not is_configured():
        return {'success': False, 'error': 'SUPABASE_URL au funguo za S3 hazijawekwa'}
    ext = re.sub(r'[^a-z0-9]', '', (ext or '').lower())[:8]
    if not ext:
        return {'success': False, 'error': 'Aina ya file haijulikani'}
    if len(data) > MAX_BYTES:
        return {'success': False,
                'error': f'File ni kubwa mno ({len(data) // 1024 // 1024}MB). Kikomo ni 10MB.'}
    # Picha za ZIP ya website nazo zinapunguzwa (zinarejelewa kwa URL
    # tunayorudisha, kwa hiyo kubadilika kwa kiendelezi ni salama)
    norm = 'jpg' if ext == 'jpeg' else ext
    if norm in _OPTIMIZABLE and _content_matches(norm, data):
        data, new_ext = optimize_image(data, norm)
        if new_ext != norm:
            ext, content_type = new_ext, 'image/webp'
    now = datetime.utcnow()
    path = f"{_safe_folder(folder)}/{now:%Y/%m}/{uuid.uuid4().hex[:16]}.{ext}"
    return _put(path, data, content_type)


def _put(path, data, content_type):
    try:
        _s3().put_object(
            Bucket=_bucket(),
            Key=path,
            Body=data,
            ContentType=content_type or 'application/octet-stream',
            # Image za tovuti hazibadiliki — URL ina UUID, kwa hiyo
            # file mpya inapata URL mpya. Cache ndefu ni salama.
            CacheControl='public, max-age=31536000, immutable',
        )
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code', '')
        detail = e.response.get('Error', {}).get('Message', str(e))
        logger.error('S3 %s: %s', code, detail)
        if code in ('NoSuchBucket', '404'):
            detail = f"Bucket '{_bucket()}' haipo kwenye Supabase."
        elif code in ('InvalidAccessKeyId', 'SignatureDoesNotMatch', 'AccessDenied', '403'):
            detail = 'SUPABASE_S3_ACCESS_KEY au SECRET si sahihi.'
        return {'success': False, 'error': detail}
    except BotoCoreError as e:
        logger.exception('upload imeshindwa')
        return {'success': False, 'error': str(e)}

    return {'success': True, 'path': path, 'url': public_url(path), 'error': ''}


def delete(path):
    """Futa file. Inarudisha True/False; kamwe haitupi exception."""
    if not is_configured() or not path:
        return False
    # Ikiwa tumepewa URL kamili, toa path yake
    marker = f"/public/{_bucket()}/"
    if marker in path:
        path = path.split(marker, 1)[1]
    try:
        _s3().delete_object(Bucket=_bucket(), Key=path.lstrip('/'))
        return True
    except (ClientError, BotoCoreError):
        logger.exception('delete imeshindwa')
        return False


def health():
    """Je, bucket ipo na funguo inafanya kazi?"""
    if not is_configured():
        return {'success': False, 'error': 'haijasanidiwa'}
    try:
        _s3().list_objects_v2(Bucket=_bucket(), MaxKeys=1)
        return {'success': True, 'bucket': _bucket(), 'region': _region()}
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code', '')
        if code in ('NoSuchBucket', '404'):
            return {'success': False, 'error': f"Bucket '{_bucket()}' haipo"}
        if code in ('InvalidAccessKeyId', 'SignatureDoesNotMatch', 'AccessDenied', '403'):
            return {'success': False, 'error': 'Funguo za S3 si sahihi'}
        return {'success': False,
                'error': f"{code}: {e.response.get('Error', {}).get('Message', '')}"}
    except BotoCoreError as e:
        return {'success': False, 'error': str(e)}
