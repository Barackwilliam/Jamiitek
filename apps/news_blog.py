"""
AI Newsroom — kila siku inakagua habari za TEKNOLOJIA NA BIASHARA (Tanzania,
Afrika Mashariki, dunia), inachagua chache muhimu zaidi (default 5), kisha
inaandika RASIMU (status='draft'). Mhariri LAZIMA aandike sehemu ya
"What this means for Tanzanian businesses" kabla ya kuchapisha — hiyo ndiyo
thamani ya kipekee (original insight) ambayo Google Discover na sera ya Google
dhidi ya "scaled content" zinahitaji. Makala yenye alama EDITOR_MARKER
haiwezi kuchapishwa.

Njia:
  1. fetch_headlines()  — kusanya vichwa vya habari kutoka RSS (TZ + dunia)
  2. select_top()       — Groq inachagua matukio N makubwa kutoka kwenye orodha
  3. write_article()    — Groq inaandika makala asili (original), SEO kamili
  4. unsplash_cover()   — picha inayohusiana kutoka Unsplash
  5. run()              — inaunganisha yote na kutengeneza BlogPost drafts

Usalama:
  • AI inaandika RASIMU tu — hakuna kinachochapishwa bila mmiliki kuthibitisha.
  • Anti-hallucination: makala zinategemea vichwa/muhtasari vilivyotolewa,
    zinataja chanzo, hazibuni nukuu/takwimu.
  • Kila hatua ina try/except — kushindwa kwa moja hakusimamishi vingine.
"""
import os
import re
import json
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.text import slugify as dj_slugify

logger = logging.getLogger(__name__)

TIMEOUT = 60
MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

# ── Vyanzo vya RSS ────────────────────────────────────────
# Dawati kuu: teknolojia + biashara (eneo ambalo JamiiTek ina utaalamu).
DESK_FEEDS = [
    'https://techcabal.com/feed/',                         # Africa tech & fintech
    'https://techpoint.africa/feed/',
    'https://disrupt-africa.com/feed/',                    # African startups
    'https://allafrica.com/tools/headlines/rdf/tanzania/headlines.rdf',
    'https://dailynews.co.tz/feed/',
    'https://feeds.bbci.co.uk/news/technology/rss.xml',
    'https://feeds.bbci.co.uk/news/business/rss.xml',
]
DAILY_COUNT = int(os.getenv('NEWSROOM_DAILY', '5') or 5)
DESK_LABEL = 'Tech & Business (Tanzania / East Africa focus)'

# (Feeds za zamani — bado zinapatikana kwa --tz/--world kama utazihitaji)
TZ_FEEDS = [
    'https://allafrica.com/tools/headlines/rdf/tanzania/headlines.rdf',
    'https://dailynews.co.tz/feed/',
    'https://www.mwananchi.co.tz/mw/rss',
    'https://feeds.bbci.co.uk/news/world/africa/rss.xml',
]
WORLD_FEEDS = [
    'https://feeds.bbci.co.uk/news/world/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
    'https://www.theguardian.com/world/rss',
    'https://rss.dw.com/rdf/rss-en-world',
]

MAX_PER_REGION_TO_AI = 40   # vichwa vingapi tunampa AI kuchagua


# ─────────────────────────────────────────────
# 1. FETCH HEADLINES (RSS)
# ─────────────────────────────────────────────
def fetch_headlines(feeds, hours=36, limit=MAX_PER_REGION_TO_AI):
    """Kusanya vichwa vya habari vya hivi karibuni kutoka RSS feeds."""
    try:
        import feedparser
    except ImportError:
        logger.error('feedparser haijafungwa — pip install feedparser')
        return []

    cutoff = timezone.now() - timedelta(hours=hours)
    items, seen = [], set()

    for url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception:
            logger.warning('RSS imeshindikana: %s', url)
            continue

        source = (parsed.feed.get('title') if getattr(parsed, 'feed', None) else '') or _domain(url)

        for e in getattr(parsed, 'entries', [])[:30]:
            title = (e.get('title') or '').strip()
            link = (e.get('link') or '').strip()
            if not title or not link or link in seen:
                continue

            # Chuja kwa muda kama tarehe ipo
            dt = None
            for k in ('published_parsed', 'updated_parsed'):
                if e.get(k):
                    try:
                        import calendar
                        from datetime import datetime, timezone as _tz
                        dt = datetime.fromtimestamp(calendar.timegm(e[k]), tz=_tz.utc)
                    except Exception:
                        dt = None
                    break
            if dt and dt < cutoff:
                continue

            summary = re.sub(r'<[^>]+>', '', e.get('summary', '') or '')[:400]
            seen.add(link)
            items.append({
                'title': title,
                'summary': summary.strip(),
                'link': link,
                'source': source[:120],
            })

    return items[:limit]


def _domain(url):
    m = re.search(r'https?://([^/]+)/', url + '/')
    return (m.group(1).replace('www.', '') if m else 'source')


# ─────────────────────────────────────────────
# 2. SELECT TOP N (Groq)
# ─────────────────────────────────────────────
_SELECT_SYS = """You are the senior editor of a Tanzanian technology & business
publication read by business owners and entrepreneurs. From a list of headlines
pick the N most important, distinct stories FOR THAT AUDIENCE: technology,
digital economy, mobile money & fintech, telecoms, startups & funding, e-commerce,
AI, cybersecurity, government policy/regulation or economic news that affects
businesses in Tanzania / East Africa. Strongly prefer Tanzania and East Africa;
include a global story only if it clearly affects local businesses.
Skip crime, celebrity, sport, and general politics without a business angle.
Avoid choosing two headlines about the same event.

Output ONLY valid JSON, no markdown, schema:
{"picks":[{"i": <index int>, "why": "<max 15 words why it's big>"}]}
Return exactly N picks, using the integer index shown for each headline."""


def select_top(headlines, n, region_label):
    """Groq inachagua matukio N makubwa. Rudisha orodha ya headlines dicts."""
    from apps.blog_ai import _client
    client = _client()
    if client is None or not headlines:
        # Fallback: chukua N za kwanza
        return headlines[:n]

    listing = '\n'.join(f'{i}. {h["title"]} — {h["source"]}' for i, h in enumerate(headlines))
    user = (f'Region: {region_label}\nN = {n}\n\nHeadlines:\n{listing}\n\n'
            f'Pick the {n} biggest distinct stories. Return ONLY the JSON.')
    try:
        raw = _chat(client, temperature=0.3, max_tokens=700,
                    messages=[{"role": "system", "content": _SELECT_SYS},
                              {"role": "user", "content": user}])
        data = _json(raw)
        picks = (data or {}).get('picks', [])
        chosen, used = [], set()
        for p in picks:
            i = p.get('i')
            if isinstance(i, int) and 0 <= i < len(headlines) and i not in used:
                used.add(i)
                item = dict(headlines[i])
                item['why'] = (p.get('why') or '')[:120]
                chosen.append(item)
            if len(chosen) >= n:
                break
        return chosen or headlines[:n]
    except Exception:
        logger.exception('select_top imeshindikana')
        return headlines[:n]


# ─────────────────────────────────────────────
# 3. WRITE ARTICLE (Groq)
# ─────────────────────────────────────────────
_WRITE_SYS = """You are a professional news writer for JamiiTek Insights, a
Tanzanian digital publication. Write an ORIGINAL, high-quality news article based
ONLY on the facts in the provided headline and summary. This is real journalism,
not marketing.

STRICT RULES:
1. Output ONLY valid JSON, no markdown fences. Schema:
   {"title","excerpt","body","meta_title","meta_description","focus_keyword","tags","editor_questions"}
2. "body" = clean HTML using ONLY <h2>,<h3>,<p>,<ul>,<li>,<strong>,<blockquote>.
   NO <html>,<head>,<style>,<script>,<img>, no inline styles. 450-800 words.
3. Base every claim on the provided facts. DO NOT invent quotes, statistics,
   names, dates or outcomes not implied by the source. Where detail is unknown,
   write generally ("reports indicate", "according to <source>"). Attribute to
   the source outlet by name in the body.
4. Write in clear, professional English. Neutral, factual news tone.
5. Structure: strong lead paragraph (who/what/where/why it matters), then
   context and analysis under <h2> subheadings, then what to watch next.
6. "title" = accurate, compelling headline, max 70 chars, include focus keyword.
7. "excerpt" = 1-2 sentence standfirst (max 300 chars).
8. "meta_title" max 60 chars. "meta_description" max 155 chars with keyword.
9. "focus_keyword" = the main search term for this story.
10. "tags" = array of 3-6 short topical tags.
11. Do NOT write analysis of what the story means for Tanzanian businesses —
    a human editor writes that section. Instead return "editor_questions":
    an array of 2-3 short, specific questions the editor could answer in that
    section (e.g. "Will this change mobile money fees for small shops?").
12. End the body with a short italic line noting readers should follow the
    original source for developing details.
"""


def write_article(event, region_label):
    """Rudisha (ok, dict). dict ina title/slug/excerpt/body/meta_*/focus_keyword/tags."""
    from apps.blog_ai import _client, _clean_html
    client = _client()
    if client is None:
        return False, 'No AI key (GEMINI_API_KEY or GROQ_API_KEY)'

    user = (
        f'Region focus: {region_label}\n'
        f'Source outlet: {event.get("source","")}\n'
        f'Headline: {event.get("title","")}\n'
        f'Summary from source: {event.get("summary","") or "(no summary provided)"}\n\n'
        f'Write the news article now. Return ONLY the JSON object.'
    )
    try:
        raw = _chat(client, temperature=0.6, max_tokens=2200,
                    messages=[{"role": "system", "content": _WRITE_SYS},
                              {"role": "user", "content": user}])
        data = _json(raw)
    except Exception as e:
        logger.exception('write_article imeshindikana')
        return False, f'AI error ({type(e).__name__}: {str(e)[:120]})'

    if not data:
        return False, 'AI did not return valid JSON'
    title = (data.get('title') or '').strip()[:200]
    body = (data.get('body') or '').strip()
    if not title or not body:
        return False, 'AI response missing title/body'

    tags = data.get('tags') or []
    if isinstance(tags, list):
        tags = ', '.join(str(t) for t in tags[:6])

    qs = data.get('editor_questions') or []
    if not isinstance(qs, list):
        qs = [str(qs)]
    body = _clean_html(body) + _editor_block([str(q)[:200] for q in qs[:3]])

    return True, {
        'title': title,
        'slug': _slug(title),
        'excerpt': (data.get('excerpt') or '').strip()[:320],
        'body': body,
        'meta_title': (data.get('meta_title') or '').strip()[:70],
        'meta_description': (data.get('meta_description') or '').strip()[:170],
        'focus_keyword': (data.get('focus_keyword') or title).strip()[:100],
        'tags': tags,
    }


# ─────────────────────────────────────────────
# 4. UNSPLASH COVER
# ─────────────────────────────────────────────
def unsplash_cover(query):
    """Rudisha URL ya picha kutoka Unsplash, au '' ikishindikana."""
    key = os.getenv('UNSPLASH_ACCESS_KEY', '')
    if not key or not query:
        return ''
    try:
        import requests
        r = requests.get(
            'https://api.unsplash.com/search/photos',
            params={'query': query, 'per_page': 1, 'orientation': 'landscape'},
            headers={'Authorization': f'Client-ID {key}'}, timeout=20)
        if r.status_code != 200:
            return ''
        results = r.json().get('results', [])
        if not results:
            return ''
        urls = results[0].get('urls', {})
        return urls.get('regular') or urls.get('full') or urls.get('small') or ''
    except Exception:
        logger.warning('Unsplash imeshindikana kwa: %s', query)
        return ''


# ─────────────────────────────────────────────
# 5. ORCHESTRATE
# ─────────────────────────────────────────────
def run(count=None, tz_count=None, world_count=None):
    """
    Tengeneza rasimu za habari. Rudisha dict:
      {'created': [BlogPost,...], 'skipped': int, 'errors': [str,...]}

    Default: dawati moja la Tech & Business, rasimu `NEWSROOM_DAILY` (5).
    tz_count/world_count (hiari) = mtindo wa zamani wa Tanzania + World News.
    """
    from apps.models import BlogPost, BlogCategory

    created, errors = [], []
    skipped = 0

    if tz_count or world_count:
        tz_cat, _ = BlogCategory.objects.get_or_create(
            slug='tanzania-news', defaults={'name': 'Tanzania News'})
        world_cat, _ = BlogCategory.objects.get_or_create(
            slug='world-news', defaults={'name': 'World News'})
        plan = [
            ('Tanzania', tz_count or 0, tz_cat, TZ_FEEDS),
            ('International', world_count or 0, world_cat, WORLD_FEEDS),
        ]
    else:
        desk_cat, _ = BlogCategory.objects.get_or_create(
            slug='tech-business', defaults={'name': 'Tech & Business'})
        plan = [(DESK_LABEL, count or DAILY_COUNT, desk_cat, DESK_FEEDS)]
    plan = [p for p in plan if p[1] > 0]

    recent_titles = set(
        BlogPost.objects.filter(created_at__gte=timezone.now() - timedelta(days=7))
        .values_list('title', flat=True))

    for label, count, cat, feeds in plan:
        headlines = fetch_headlines(feeds)
        if not headlines:
            errors.append(f'{label}: hakuna vichwa vilivyopatikana')
            continue
        events = select_top(headlines, count, label)

        for ev in events:
            link = ev.get('link', '')
            # Dedup: chanzo kileile au tayari kimeandikwa
            if link and BlogPost.objects.filter(source_url=link).exists():
                skipped += 1
                continue

            ok, art = write_article(ev, label)
            import time as _t; _t.sleep(2)   # pumzi fupi — kikomo cha Groq kwa dakika
            if not ok:
                errors.append(f'{label}: {art}')
                continue
            if art['title'] in recent_titles:
                skipped += 1
                continue

            slug = _unique_slug(BlogPost, art['slug'])
            cover = unsplash_cover(art['focus_keyword'] or art['title'])

            try:
                post = BlogPost.objects.create(
                    title=art['title'], slug=slug, category=cat,
                    excerpt=art['excerpt'], body=art['body'],
                    cover_image=cover,
                    meta_title=art['meta_title'], meta_description=art['meta_description'],
                    focus_keyword=art['focus_keyword'],
                    author_name='JamiiTek Newsroom',
                    status='draft', is_news=True,
                    source_url=link, source_name=ev.get('source', '')[:120],
                )
                created.append(post)
                recent_titles.add(art['title'])
            except Exception as e:
                errors.append(f'{label}: kuunda post kumeshindikana ({type(e).__name__})')

    return {'created': created, 'skipped': skipped, 'errors': errors}


def run_and_notify(count=None, tz_count=None, world_count=None):
    """
    Endesha newsroom kisha mjulishe mmiliki KWA VYOVYOTE:
      • zikiandaliwa → email ya kukagua rasimu
      • zisipoandaliwa → email ya ripoti yenye sababu (ili ujue kwa nini)
    Inatumiwa na cron endpoint, management command, na kitufe cha admin.
    """
    from apps.utils import email_notifications as en
    try:
        result = run(count=count, tz_count=tz_count, world_count=world_count)
    except Exception as e:
        logger.exception('AI newsroom run failed')
        result = {'created': [], 'skipped': 0, 'errors': [f'Crash: {type(e).__name__}: {e}']}

    try:
        if result['created']:
            en.send_blog_review_reminder(result['created'])
        else:
            en.send_news_run_report(result)
    except Exception:
        logger.exception('AI newsroom notification failed')

    logger.info('AI newsroom: created=%d skipped=%d errors=%d',
                len(result['created']), result['skipped'], len(result['errors']))
    return result


# ── helpers ───────────────────────────────────
def _editor_block(questions):
    """Sehemu ambayo mhariri LAZIMA aijaze kabla ya kuchapisha."""
    from django.utils.html import escape
    from apps.models import EDITOR_MARKER
    items = ''.join(f'<li>{escape(q)}</li>' for q in questions if q.strip())
    return (
        '<h2>What this means for Tanzanian businesses</h2>\n'
        f'<p>{EDITOR_MARKER} Replace this paragraph with your own analysis: the local '
        'impact, numbers you know, advice for business owners, or your expert view. '
        'Delete this note and the questions below when done.</p>\n'
        + (f'<ul>{items}</ul>\n' if items else '')
    )


FALLBACK_MODELS = ['llama-3.3-70b-versatile', 'openai/gpt-oss-120b', 'llama-3.1-8b-instant']


def _chat(client, messages, temperature=0.5, max_tokens=1500, attempts=4):
    """
    Groq chat yenye uimara:
      • 429 (kikomo cha tokens/dakika) → subiri kisha jaribu tena
      • model imeondolewa/haipo → jaribu model mbadala
    Groq free tier ina kikomo cha tokens kwa dakika; makala 10 mfululizo
    zingeigonga bila hii.
    """
    import time
    models = [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]
    last = None
    for model in models:
        for attempt in range(attempts):
            try:
                resp = client.chat.completions.create(
                    model=model, temperature=temperature, max_tokens=max_tokens,
                    messages=messages, timeout=TIMEOUT)
                return resp.choices[0].message.content
            except Exception as e:
                last = e
                status = getattr(e, 'status_code', None)
                text = str(e).lower()
                if status == 429 or 'rate limit' in text or 'rate_limit' in text:
                    wait = 20 * (attempt + 1)
                    try:
                        ra = e.response.headers.get('retry-after')
                        if ra:
                            wait = min(90, max(wait, int(float(ra)) + 1))
                    except Exception:
                        pass
                    logger.warning('Groq 429 (%s) — nasubiri %ss', model, wait)
                    time.sleep(wait)
                    continue
                if status in (400, 404) and ('model' in text and
                                             ('decommission' in text or 'not found' in text
                                              or 'does not exist' in text)):
                    logger.warning('Groq model %s haipatikani — najaribu nyingine', model)
                    break           # nenda model inayofuata
                raise
    raise last or RuntimeError('Groq call failed')


def _json(raw):
    raw = (raw or '').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def _slug(text):
    s = dj_slugify(text)[:200]
    return s or 'habari'


def _unique_slug(model, base):
    slug = base
    i = 2
    while model.objects.filter(slug=slug).exists():
        suffix = f'-{i}'
        slug = base[:200 - len(suffix)] + suffix
        i += 1
    return slug
