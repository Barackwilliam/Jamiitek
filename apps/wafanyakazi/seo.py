"""
Grace — ukaguzi wa SEO wa kila wiki (Google Search Console).

Mara moja kwa wiki (Jumatatu kuanzia saa 12 asubuhi) Grace:

  1. Anavuta data ya siku 28 (query × ukurasa) na ya siku 28 zilizotangulia.
  2. Anatafuta FURSA: maneno yanayoonekana Google mara nyingi lakini
     yanabofywa kidogo kuliko inavyotarajiwa kwa nafasi yake, na maneno
     yaliyo karibu na ukurasa wa kwanza (nafasi 8–20).
  3. Kwa kila ukurasa wenye fursa kubwa anaangalia kama maneno hayo yapo
     kwenye kichwa, maelezo na maandishi ya ukurasa (mapengo).
  4. Anaandaa kichwa na maelezo mapya (AI) — yanakuja "Mezani kwako".
     Ukikubali, yanatumika papo hapo kwa templates na makala za blog,
     na Bing/ChatGPT search zinajulishwa (IndexNow).

Hakuna kinachobadilika kwenye tovuti bila idhini yako. Kurasa zenye kichwa
kwenye code (home, services…) zinakuja kama mapendekezo ya kufanyia kazi.
"""
import hashlib
import logging
import re
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlparse

import requests

from apps.seo import gsc

from . import ai
from .board import found, site
from .models import Alama, Kazi, SeoRipoti
from .team import member

logger = logging.getLogger(__name__)

SLUG = 'grace'
START_HOUR = 6
DAYS = 28
LAG_DAYS = 3                 # data ya Search Console inachelewa siku 2–3
MIN_IMPRESSIONS = 30         # kwa siku 28 — chini ya hapo ni kelele
MAX_POSITION = 20
PAGES_PER_WEEK = 5
COOLDOWN_DAYS = 28           # Google inahitaji muda kuona mabadiliko

# CTR ya wastani kwa kila nafasi ya matokeo ya Google (makadirio ya tasnia)
CTR_CURVE = {1: .28, 2: .15, 3: .10, 4: .07, 5: .055, 6: .045, 7: .035, 8: .03, 9: .025, 10: .02}


def expected_ctr(position):
    pos = max(1, round(position or 99))
    return CTR_CURVE.get(pos, .01 if pos <= 20 else .003)


def week_label(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


# ── Kurasa ───────────────────────────────────────────────────

def _path(url):
    path = urlparse(url).path or '/'
    return path if path.endswith('/') or '.' in path.rsplit('/', 1)[-1] else path + '/'


def target(url):
    """('template'|'blog'|'page', kitu_au_None) kwa URL ya Search Console."""
    from apps.models import BlogPost, WebsiteTemplate

    parts = [p for p in _path(url).split('/') if p]
    if len(parts) == 2 and parts[0] == 'templates' and parts[1] not in ('c', 'preview'):
        tpl = WebsiteTemplate.objects.filter(slug=parts[1], is_active=True).first()
        if tpl:
            return 'template', tpl
    if len(parts) == 2 and parts[0] == 'blog':
        post = BlogPost.objects.filter(slug=parts[1], status='published').first()
        if post:
            return 'blog', post
    return 'page', None


def _plain(html):
    html = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', html or '')
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


def snapshot(url, kind, obj):
    """Kichwa, maelezo na maandishi ya ukurasa kama Google inavyoviona."""
    if kind == 'template':
        from apps import template_seo as ts
        return {'title': ts.title(obj), 'description': ts.description(obj),
                'text': ' '.join([obj.name, obj.description or '', obj.long_description or '',
                                  *ts.article(obj)])}
    if kind == 'blog':
        return {'title': obj.meta_title or obj.title,
                'description': obj.meta_description or obj.excerpt or '',
                'text': f'{obj.title} {obj.excerpt or ""} {_plain(obj.body)}'}
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'JamiiTek-SEO-Audit/1.0'})
        html = r.text if r.status_code == 200 else ''
    except requests.RequestException:
        html = ''
    title = re.search(r'(?is)<title[^>]*>(.*?)</title>', html)
    desc = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html)
    return {'title': _plain(title.group(1)) if title else '',
            'description': _plain(desc.group(1)) if desc else '',
            'text': _plain(html)}


def _words(text):
    return set(re.findall(r'[a-z0-9]+', (text or '').lower()))


def coverage(query, snap):
    """Ni maneno mangapi ya query yapo kwenye kichwa / maelezo / maandishi."""
    words = [w for w in re.findall(r'[a-z0-9]+', query.lower()) if len(w) > 2] or [query.lower()]

    def share(text):
        have = _words(text)
        return sum(1 for w in words if w in have) / len(words)

    return {'title': share(snap['title']), 'description': share(snap['description']),
            'text': share(snap['text'])}


# ── Uchambuzi ────────────────────────────────────────────────

def _totals(rows):
    clicks = sum(r['clicks'] for r in rows)
    impressions = sum(r['impressions'] for r in rows)
    pos = (sum(r['position'] * r['impressions'] for r in rows) / impressions) if impressions else 0
    return {'clicks': int(clicks), 'impressions': int(impressions),
            'ctr': round(clicks / impressions, 4) if impressions else 0, 'position': round(pos, 1)}


def opportunities(rows):
    """
    Panga kurasa kwa mibofyo inayopotea. Kila safu ya `rows` ina
    keys=[query, page]. Rudisha orodha ya {page, missed, queries:[...]}.
    """
    pages = defaultdict(list)
    for r in rows:
        query, page = r['keys'][0], r['keys'][1]
        impressions, clicks, pos = r['impressions'], r['clicks'], r['position']
        if impressions < MIN_IMPRESSIONS or pos > MAX_POSITION:
            continue
        ctr = clicks / impressions if impressions else 0
        exp = expected_ctr(pos)
        missed = impressions * max(0.0, exp - ctr)
        low_ctr = pos <= 10 and ctr < exp * 0.6
        near = 8 <= pos <= MAX_POSITION
        if not (low_ctr or near) or missed < 1:
            continue
        pages[page].append({'query': query, 'impressions': int(impressions), 'clicks': int(clicks),
                            'ctr': round(ctr, 4), 'position': round(pos, 1),
                            'expected_ctr': exp, 'missed': round(missed, 1),
                            'kind': 'ctr' if low_ctr else 'karibu'})
    out = []
    for page, queries in pages.items():
        queries.sort(key=lambda q: -q['missed'])
        out.append({'page': page, 'missed': round(sum(q['missed'] for q in queries), 1),
                    'queries': queries[:6]})
    out.sort(key=lambda p: -p['missed'])
    return out


def movers(now_rows, prev_rows, limit=5):
    """Kurasa zilizopanda / kushuka zaidi kwa clicks ukilinganisha vipindi viwili."""
    def by_page(rows):
        acc = defaultdict(lambda: {'clicks': 0, 'impressions': 0})
        for r in rows:
            acc[r['keys'][-1]]['clicks'] += r['clicks']
            acc[r['keys'][-1]]['impressions'] += r['impressions']
        return acc

    cur, old = by_page(now_rows), by_page(prev_rows)
    diffs = [{'page': p, 'clicks': int(cur.get(p, {}).get('clicks', 0)),
              'change': int(cur.get(p, {}).get('clicks', 0) - old.get(p, {}).get('clicks', 0))}
             for p in set(cur) | set(old)]
    up = sorted((d for d in diffs if d['change'] > 0), key=lambda d: -d['change'])[:limit]
    down = sorted((d for d in diffs if d['change'] < 0), key=lambda d: d['change'])[:limit]
    return {'up': up, 'down': down}


def top_queries(rows, limit=15):
    acc = defaultdict(lambda: {'clicks': 0, 'impressions': 0, 'pw': 0})
    for r in rows:
        q = acc[r['keys'][0]]
        q['clicks'] += r['clicks']
        q['impressions'] += r['impressions']
        q['pw'] += r['position'] * r['impressions']
    out = [{'query': k, 'clicks': int(v['clicks']), 'impressions': int(v['impressions']),
            'position': round(v['pw'] / v['impressions'], 1) if v['impressions'] else 0}
           for k, v in acc.items()]
    return sorted(out, key=lambda q: (-q['clicks'], -q['impressions']))[:limit]


# ── Rasimu ───────────────────────────────────────────────────

def parse_draft(text):
    """'Title: …' na 'Description: …' (au Kichwa/Maelezo) kutoka kwenye rasimu."""
    title = desc = ''
    for line in (text or '').splitlines():
        m = re.match(r'\s*(title|kichwa)\s*[:：]\s*(.+)', line, re.I)
        if m:
            title = m.group(2).strip()
            continue
        m = re.match(r'\s*(description|maelezo)\s*[:：]\s*(.+)', line, re.I)
        if m:
            desc = m.group(2).strip()
    return title.strip(' "\'')[:70], desc.strip(' "\'')[:170]


def _fallback(snap, queries):
    q = queries[0]['query']
    lead = q[:1].upper() + q[1:]
    title = snap['title'] or 'JamiiTek'
    if q.lower() not in title.lower():
        title = f'{lead} — {title}'
    title = title[:60].rsplit(' ', 1)[0] if len(title) > 60 else title
    desc = snap['description'] or ''
    if q.lower() not in desc.lower():
        desc = f'{lead}: {desc}' if desc else f'{lead} — JamiiTek, Dar es Salaam, Tanzania.'
    return title, desc[:155]


def draft_for(snap, queries):
    who = member(SLUG)
    lines = '\n'.join(f"- \"{q['query']}\": impressions {q['impressions']}, clicks {q['clicks']}, "
                      f"nafasi {q['position']}" for q in queries[:5])
    text = ai.write(
        ai.persona(who['name'], who['role']) + ' Wewe pia ni mtaalamu wa SEO wa Google.',
        f"Ukurasa wa JamiiTek una kichwa: \"{snap['title']}\"\nna maelezo: \"{snap['description']}\".\n"
        f"Watu wanautafuta Google kwa maneno haya lakini hawabofyi vya kutosha:\n{lines}\n\n"
        "Andika kichwa kipya (herufi 50–60) na maelezo mapya (herufi 140–155) yanayotumia "
        "kwa kawaida maneno muhimu zaidi hapo juu, kwa lugha ileile ambayo watu wanatafutia "
        "(Kiingereza au Kiswahili), yanayomshawishi mtu abofye, bila kudanganya wala bei za "
        "kubuni. Jibu kwa mistari miwili tu, hasa hivi:\n"
        "Title: …\nDescription: …",
        max_tokens=200, temperature=0.4)
    title, desc = parse_draft(text)
    if not title or not desc:
        title, desc = _fallback(snap, queries)
    return f'Title: {title}\nDescription: {desc}'


def _detail(snap, queries):
    out = [f"Sasa hivi — kichwa: \"{snap['title']}\"", f"maelezo: \"{snap['description'][:160]}\"", '']
    for q in queries[:5]:
        cov = q['coverage']
        gaps = [name for name, key in (('kichwa', 'title'), ('maelezo', 'description'),
                                       ('maandishi', 'text')) if cov[key] < 0.5]
        tip = 'haionekani kwenye ' + ', '.join(gaps) if gaps else 'ipo kila mahali'
        kind = 'CTR ndogo' if q['kind'] == 'ctr' else 'karibu ukurasa wa 1'
        out.append(f"• \"{q['query']}\" — impressions {q['impressions']}, clicks {q['clicks']} "
                   f"({q['ctr']:.1%}), nafasi {q['position']} · {kind} · {tip}")
    return '\n'.join(out)


def _key(path, week):
    raw = f'seo:{week}:{path}'
    return raw if len(raw) <= 120 else f'seo:{week}:{hashlib.sha1(path.encode()).hexdigest()}'


def _recently_handled(ref, now):
    return (Kazi.objects.filter(worker=SLUG, channel='seo', ref=ref)
            .filter(status__in=Kazi.LIVE).exists()
            or Kazi.objects.filter(worker=SLUG, channel='seo', ref=ref, status=Kazi.DONE,
                                   closed_at__gte=now - timedelta(days=COOLDOWN_DAYS)).exists())


# ── Mzunguko ─────────────────────────────────────────────────

def due(now):
    return now.hour >= START_HOUR and Alama.get('seo:week') != week_label(now.date())


def audit(now, force=False):
    """Ukaguzi mmoja. Rudisha muhtasari (dict)."""
    if not gsc.is_configured():
        return {'seo': 'Search Console haijaunganishwa'}
    if not force and not due(now):
        return {'seo': 'tayari wiki hii'}

    week = week_label(now.date())
    end = now.date() - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=DAYS - 1)
    prev_end, prev_start = start - timedelta(days=1), start - timedelta(days=DAYS)
    report, _ = SeoRipoti.objects.update_or_create(week=week, defaults={'start': start, 'end': end})
    Alama.put('seo:week', week)
    try:
        rows = gsc.query(start, end)
        prev = gsc.query(prev_start, prev_end)
    except gsc.GSCError as exc:
        report.error = str(exc)[:400]
        report.save(update_fields=['error'])
        return {'seo': f'kosa: {exc}'}

    found_pages = opportunities(rows)
    report.totals, report.previous = _totals(rows), _totals(prev)
    report.movers, report.top_queries = movers(rows, prev), top_queries(rows)
    report.error = ''

    created = 0
    for opp in found_pages:
        if created >= PAGES_PER_WEEK:
            break
        url = opp['page']
        path = _path(url)
        kind, obj = target(url)
        ref = f'{kind}:{obj.pk}' if obj else f'page:{path}'[:60]
        opp.update({'path': path, 'kind': kind})
        if _recently_handled(ref, now):
            opp['status'] = 'inasubiri'
            continue
        snap = snapshot(url, kind, obj)
        for q in opp['queries']:
            q['coverage'] = coverage(q['query'], snap)
        top = opp['queries'][0]['query']
        if kind == 'page':
            title = f'SEO: "{top}" — {path} inapoteza mibofyo ~{opp["missed"]:.0f}'
        else:
            title = f'SEO: kichwa kipya kwa {obj} ("{top}")'
        found(SLUG, _key(path, week), title[:200],
              draft=(lambda s=snap, q=opp['queries']: draft_for(s, q)),
              ref=ref, priority=1 if opp['missed'] >= 20 else 2,
              detail=_detail(snap, opp['queries']), link=site(path), channel='seo')
        opp['status'] = 'mezani'
        created += 1

    report.opportunities = found_pages[:20]
    report.save()
    return {'seo': f"fursa {len(found_pages)}, rasimu mpya {created}",
            'clicks': report.totals['clicks'], 'impressions': report.totals['impressions']}


def run(now):
    try:
        return audit(now)
    except Exception as exc:     # SEO isizuie post ya Grace wala timu nzima
        logger.exception('[seo] ukaguzi umeshindwa')
        return {'seo': f'kosa: {type(exc).__name__}: {exc}'[:200]}


# ── Kutekeleza idhini ────────────────────────────────────────

def apply(kazi):
    """Tumia kichwa/maelezo yaliyokubaliwa. Rudisha ujumbe; ValueError kama haiwezekani."""
    from apps.indexnow import ping
    from apps.models import BlogPost, WebsiteTemplate

    title, desc = parse_draft(kazi.draft)
    if not title and not desc:
        raise ValueError('Rasimu haina "Title:" wala "Description:".')
    kind, _, pk = kazi.ref.partition(':')
    if kind == 'template':
        obj = WebsiteTemplate.objects.filter(pk=pk).first()
        if not obj:
            raise ValueError('template hiyo haipo tena')
        fields = {'seo_title': title, 'seo_description': desc}
    elif kind == 'blog':
        obj = BlogPost.objects.filter(pk=pk).first()
        if not obj:
            raise ValueError('makala hiyo haipo tena')
        fields = {'meta_title': title, 'meta_description': desc}
    else:
        return None
    for name, value in fields.items():
        if value:
            setattr(obj, name, value)
    obj.save()
    path = urlparse(kazi.link).path if kazi.link else ''
    if path:
        ping([path])
    return f'Kichwa na maelezo mapya yametumika kwenye {obj} — Google itayaona ikipita tena.'
