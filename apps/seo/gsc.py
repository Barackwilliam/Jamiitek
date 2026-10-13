"""
Google Search Console — data halisi ya jinsi watu wanavyoipata JamiiTek Google.

Uthibitisho ni kwa SERVICE ACCOUNT (ufunguo wa JSON), bila maktaba ya Google:
tunasaini JWT kwa `cryptography` (ipo tayari) na kuibadilisha kuwa access token.
Ruhusa ni ya KUSOMA tu (webmasters.readonly).

Mipangilio (Render → Environment):
  GSC_SERVICE_ACCOUNT_JSON  JSON nzima ya service account (au base64 yake)
  GSC_SITE_URL              property kama ilivyo kwenye Search Console, mfano
                            'sc-domain:jamiitek.com' au 'https://www.jamiitek.com/'

Hatua za kuweka:
  1. console.cloud.google.com → wezesha "Google Search Console API"
  2. IAM → Service accounts → Create → Keys → Add key → JSON
  3. search.google.com/search-console → Settings → Users and permissions →
     Add user: email ya service account (…@….iam.gserviceaccount.com), ruhusa "Restricted"
  4. Weka JSON kwenye Render kama GSC_SERVICE_ACCOUNT_JSON — USIIWEKE kwenye GitHub.
"""
import base64
import json
import logging
import os
import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly'
API = 'https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query'
TOKEN_CACHE = 'seo:gsc:token'


class GSCError(Exception):
    pass


def _setting(name, default=''):
    return (getattr(settings, name, '') or os.getenv(name, '') or default).strip()


def site_url():
    return _setting('GSC_SITE_URL', 'sc-domain:jamiitek.com')


def credentials():
    """JSON ya service account kama dict, au None. Inakubali JSON ghafi au base64."""
    raw = _setting('GSC_SERVICE_ACCOUNT_JSON')
    if not raw:
        return None
    if not raw.startswith('{'):
        try:
            raw = base64.b64decode(raw).decode()
        except Exception:
            return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get('client_email') or not data.get('private_key'):
        return None
    return data


def is_configured():
    return credentials() is not None


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _signed_jwt(creds, now=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(now or time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    if creds.get('private_key_id'):
        header['kid'] = creds['private_key_id']
    claims = {'iss': creds['client_email'], 'scope': SCOPE, 'aud': TOKEN_URL,
              'iat': now, 'exp': now + 3600}
    unsigned = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    key = serialization.load_pem_private_key(creds['private_key'].encode(), password=None)
    signature = key.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f'{unsigned}.{_b64(signature)}'


def _token():
    token = cache.get(TOKEN_CACHE)
    if token:
        return token
    creds = credentials()
    if not creds:
        raise GSCError('GSC_SERVICE_ACCOUNT_JSON haijawekwa au si sahihi.')
    try:
        r = requests.post(TOKEN_URL, timeout=15, data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': _signed_jwt(creds)})
    except requests.RequestException as exc:
        raise GSCError(f'Google haipatikani: {exc}') from exc
    if r.status_code != 200:
        raise GSCError(f'Google imekataa ufunguo ({r.status_code}): {r.text[:200]}')
    data = r.json()
    cache.set(TOKEN_CACHE, data['access_token'], max(60, int(data.get('expires_in', 3600)) - 300))
    return data['access_token']


def query(start, end, dimensions=('query', 'page'), row_limit=5000, page=None):
    """
    Safu za Search Analytics kati ya tarehe `start` na `end` (date).
    Kila safu: {'keys': [...], 'clicks', 'impressions', 'ctr', 'position'}.
    `page` — URL kamili: data ya ukurasa huo mmoja tu (kupima mabadiliko).
    """
    url = API.format(site=quote(site_url(), safe=''))
    body = {'startDate': start.isoformat(), 'endDate': end.isoformat(),
            'dimensions': list(dimensions), 'rowLimit': row_limit, 'dataState': 'final'}
    if page:
        body['dimensionFilterGroups'] = [{'filters': [
            {'dimension': 'page', 'operator': 'equals', 'expression': page}]}]
    try:
        r = requests.post(url, json=body, timeout=30,
                          headers={'Authorization': f'Bearer {_token()}'})
    except requests.RequestException as exc:
        raise GSCError(f'Search Console haipatikani: {exc}') from exc
    if r.status_code == 403:
        raise GSCError(
            f'Hakuna ruhusa kwa "{site_url()}". Ongeza email ya service account kwenye '
            'Search Console → Settings → Users and permissions, na hakikisha GSC_SITE_URL '
            'imeandikwa kama ilivyo kwenye Search Console.')
    if r.status_code != 200:
        raise GSCError(f'Search Console ({r.status_code}): {r.text[:200]}')
    return r.json().get('rows', [])
