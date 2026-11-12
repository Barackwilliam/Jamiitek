# apps/domain_checker.py
"""
Domain availability checker for the JamiiTek public site.

Strategy (first confident answer wins):
    1. Local DomainRecord table  -> domains JamiiTek already manages
    2. RDAP (rdap.org)           -> authoritative for .com/.net/.org/etc.
    3. DNS (NS / SOA / A)        -> fallback, covers .tz / .co.tz

Returns a plain dict so the view can hand it straight to JsonResponse.
No new dependencies: `requests` and `dnspython` are already in requirements.txt.
"""

import re
import logging

import requests
import dns.resolver
import dns.exception

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Pricing (TZS / year). Edit here — the homepage reads from this.
# ──────────────────────────────────────────────────────────────
TLD_PRICES = {
    '.com':   36000,
    '.co.tz': 25000,
    '.tz':    22000,
    '.org':   30000,
    '.net':   30000,
    '.or.tz': 25000,
    '.ac.tz': 25000,
    '.io':    95000,
    '.africa': 45000,
}
DEFAULT_PRICE = 40000

# TLDs RDAP does not serve well — DNS is the primary signal there.
DNS_ONLY_TLDS = ('.tz',)

# TLDs offered as alternatives when the searched name is taken
SUGGEST_TLDS = ['.com', '.co.tz', '.tz', '.net', '.org']

RESOLVER_TIMEOUT = 4
RDAP_TIMEOUT = 6

DOMAIN_RE = re.compile(
    r'^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$'
)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def normalize(raw):
    """'HTTPS://WWW.Example.com/page?x=1' -> 'example.com'. Returns '' if unusable."""
    if not raw:
        return ''
    name = str(raw).strip().lower()
    name = re.sub(r'^[a-z][a-z0-9+.-]*://', '', name)   # scheme
    name = name.split('/')[0].split('?')[0].split('#')[0]
    name = name.split('@')[-1]                          # pasted an email
    name = name.split(':')[0]                           # port
    name = name.strip('.')
    if name.startswith('www.'):
        name = name[4:]
    return name


def is_valid(name):
    return bool(name) and bool(DOMAIN_RE.match(name))


def tld_of(name):
    """Longest known suffix, so 'shop.co.tz' -> '.co.tz' not '.tz'."""
    for suffix in sorted(TLD_PRICES, key=len, reverse=True):
        if name.endswith(suffix):
            return suffix
    return '.' + name.rsplit('.', 1)[-1]


def sld_of(name):
    """'mysite.co.tz' -> 'mysite'"""
    suffix = tld_of(name)
    return name[: -len(suffix)] if name.endswith(suffix) else name.split('.')[0]


def price_for(name):
    return TLD_PRICES.get(tld_of(name), DEFAULT_PRICE)


# ──────────────────────────────────────────────────────────────
# Individual probes — each returns True / False / None (unknown)
# ──────────────────────────────────────────────────────────────
def _check_local(name):
    """True if this domain is already in JamiiTek's own records."""
    try:
        from .models import DomainRecord
        return DomainRecord.objects.filter(domain_name__iexact=name).exists()
    except Exception as exc:                       # DB down, model moved, etc.
        logger.warning('Local domain lookup failed for %s: %s', name, exc)
        return None


def _check_rdap(name):
    """True = registered, False = available, None = no usable answer."""
    try:
        resp = requests.get(
            f'https://rdap.org/domain/{name}',
            headers={'Accept': 'application/rdap+json'},
            timeout=RDAP_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.info('RDAP lookup failed for %s: %s', name, exc)
        return None

    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    return None


def _check_dns(name):
    """True = something is published for this name, False = NXDOMAIN, None = unclear."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = RESOLVER_TIMEOUT
    resolver.timeout = RESOLVER_TIMEOUT

    nxdomain_seen = False
    for record_type in ('NS', 'SOA', 'A'):
        try:
            answer = resolver.resolve(name, record_type)
            if len(answer):
                return True
        except dns.resolver.NXDOMAIN:
            nxdomain_seen = True
        except dns.resolver.NoAnswer:
            continue                                # name exists, wrong type
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as exc:
            logger.info('DNS %s lookup inconclusive for %s: %s', record_type, name, exc)
            continue

    return False if nxdomain_seen else None


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────
def check_domain(raw, with_suggestions=True):
    """
    Returns:
        {
          'query':      'Mysite.CO.TZ',
          'domain':     'mysite.co.tz',
          'tld':        '.co.tz',
          'status':     'taken' | 'available' | 'unknown' | 'invalid',
          'confidence': 'high' | 'low',
          'price':      25000,
          'source':     'jamiitek' | 'rdap' | 'dns',
          'suggestions': [{'domain': ..., 'price': ..., 'status': 'available'}, ...]
        }
    """
    domain = normalize(raw)
    result = {
        'query': (raw or '').strip(),
        'domain': domain,
        'tld': tld_of(domain) if domain else '',
        'status': 'invalid',
        'confidence': 'high',
        'price': None,
        'source': None,
        'suggestions': [],
    }

    if not is_valid(domain):
        return result

    result['price'] = price_for(domain)
    dns_only = domain.endswith(DNS_ONLY_TLDS)

    # 1. Ours already?
    if _check_local(domain) is True:
        result.update(status='taken', source='jamiitek', confidence='high')
        if with_suggestions:
            result['suggestions'] = _suggest(domain)
        return result

    # 2. RDAP (skip for TLDs it doesn't serve)
    if not dns_only:
        rdap = _check_rdap(domain)
        if rdap is True:
            result.update(status='taken', source='rdap', confidence='high')
            if with_suggestions:
                result['suggestions'] = _suggest(domain)
            return result
        if rdap is False:
            result.update(status='available', source='rdap', confidence='high')
            return result

    # 3. DNS fallback
    resolved = _check_dns(domain)
    if resolved is True:
        result.update(status='taken', source='dns', confidence='high')
        if with_suggestions:
            result['suggestions'] = _suggest(domain)
    elif resolved is False:
        # NXDOMAIN is a strong hint but a registered-and-unconfigured domain
        # looks identical, so .tz answers stay 'low' confidence.
        result.update(
            status='available',
            source='dns',
            confidence='low' if dns_only else 'high',
        )
    else:
        result.update(status='unknown', source='dns', confidence='low')

    return result


def _suggest(domain, limit=4):
    """Same name on other TLDs, only returning ones that look free."""
    base = sld_of(domain)
    current = tld_of(domain)
    out = []

    for suffix in SUGGEST_TLDS:
        if len(out) >= limit:
            break
        if suffix == current:
            continue

        candidate = f'{base}{suffix}'
        if not is_valid(candidate):
            continue

        probe = _check_rdap(candidate) if not candidate.endswith(DNS_ONLY_TLDS) else None
        if probe is None:
            probe = _check_dns(candidate)

        if probe is False:
            out.append({
                'domain': candidate,
                'price': price_for(candidate),
                'status': 'available',
            })

    return out
