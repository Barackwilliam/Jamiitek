"""
JamiiTek Spotlight — makala maalum kuhusu JamiiTek yenyewe.

Kila JUMATATU, JUMATANO na JUMAMOSI (saa za Tanzania) AI inachunguza mfumo
(huduma kwenye database, mipango ya JamiiBot, templates, aina za website,
kazi za portfolio na bidhaa kuu) kisha inaandika MAKALA MOJA kuhusu jambo
moja: huduma fulani, JamiiBot, website builder, domains, kazi tuliyofanya…

Kutorudia:
  • Kila makala inabeba "mada + mtazamo" (mf. `service-3:how-to`) kwenye
    `source_name` kama `spotlight:<ufunguo>`. Ufunguo uliokwisha tumika
    hauchaguliwi tena — mada moja inaweza kurudi tu kwa mtazamo mpya
    (mwongozo, maswali, kesi halisi, faida kwa SME, nyuma ya pazia…).
  • Kichwa cha habari kinalinganishwa na VICHWA VYOTE vya blog (si siku 7
    tu). Kikifanana (sawa kabisa au >80% kwa difflib), AI inaombwa kichwa
    kingine hadi mara 3; kisipopatikana kichwa cha kipekee, hakuna makala.
  • AI inapewa vichwa vya makala zilizopita kuhusu mada hiyo hiyo ili
    isirudie hoja zilezile.

Usalama:
  • AI inatumia UKWELI uliotolewa kutoka mfumoni tu — haibuni bei, takwimu,
    wateja wala nukuu.
  • Inaandika RASIMU (draft) kama newsroom; mmiliki anapata email ya kukagua.
    Weka SPOTLIGHT_AUTOPUBLISH=1 kwenye environment ichapishwe moja kwa moja.

Inaitwa na:
  • /tasks/news/ (cron ya kila siku) — inajiamulia yenyewe kama leo ni siku yake
  • python manage.py jamiitek_spotlight [--force] [--topic KEY] [--no-email]
"""
import os
import re
import random
import logging
from difflib import SequenceMatcher

from django.utils import timezone

logger = logging.getLogger(__name__)

# Jumatatu=0, Jumatano=2, Jumamosi=5 (datetime.weekday())
DAYS = {0, 2, 5}
DAY_NAMES = {0: 'Monday', 2: 'Wednesday', 5: 'Saturday'}
CATEGORY_SLUG = 'jamiitek-spotlight'
CATEGORY_NAME = 'JamiiTek Spotlight'
KEY_PREFIX = 'spotlight:'
TITLE_SIMILARITY = 0.80

# Mitazamo — mada moja inaweza kuandikwa tena kwa mtazamo ambao haujatumika.
ANGLES = [
    ('intro', 'An introduction: what it is, who it is for, and the problem it solves'),
    ('how-to', 'A practical step-by-step guide for a business owner getting started'),
    ('faq', 'Answer the questions Tanzanian business owners most often ask about it'),
    ('benefits', 'Concrete benefits for small and medium businesses in Tanzania'),
    ('use-cases', 'Real-world use cases by industry (shops, tourism, restaurants, schools, NGOs)'),
    ('mistakes', 'Common mistakes businesses make in this area and how JamiiTek helps avoid them'),
    ('behind', 'Behind the scenes: how JamiiTek builds and runs it, in plain language'),
    ('compare', 'How to choose: options compared honestly, and when this one fits best'),
]


# ─────────────────────────────────────────────
# 1. UKWELI KUTOKA MFUMONI
# ─────────────────────────────────────────────
# Bidhaa kuu (ukweli uleule ulio kwenye homepage — si wa kubuni).
CORE_FACTS = {
    'jamiibot': ('JamiiBot — AI WhatsApp assistant', [
        'AI chatbot that answers customers on WhatsApp 24 hours a day',
        'Replies in under 2 seconds and detects Swahili or English automatically',
        'Business owner gets their own conversation dashboard',
        'Can be ready in about 10 minutes with no coding',
        'Starts from TSh 5,000 per month; free trial available at jamiitek.com/bot/',
    ]),
    'builder': ('JamiiTek Website Builder', [
        'Drag & drop website builder, no coding needed',
        'AI can generate a whole website from a one-sentence business description, in English or Swahili',
        'Free subdomain: yourname.jamiitek.com',
        'Ready-made structures for shops, tourism, restaurants, events and more',
        'Orders and inquiries can go straight to WhatsApp',
        'Templates from TSh 15,000 per month; start at jamiitek.com/get-started/',
    ]),
    'domains-hosting': ('Domains & managed hosting', [
        'Domain registration for .co.tz (TSh 25,000/yr), .tz (TSh 15,000/yr), .com/.org/.net (TSh 30,000/yr)',
        'JamiiTek registers the domain within 24 hours',
        'Managed hosting with 99.9% uptime guarantee, free SSL and daily backups',
        'DNS and email hosting, with renewal reminders before expiry',
        'Domain availability can be checked on the jamiitek.com homepage',
    ]),
    'custom-website': ('Custom website development', [
        'Fully custom websites designed around the business',
        'Answer a short questionnaire to get an instant proposal with pricing',
        'Fixed price and timeline agreed before work starts; the client reviews progress as it is built',
        'After launch JamiiTek keeps the site secure, backed up and supported on WhatsApp',
        'Websites from TSh 150,000 depending on scope; most delivered in 2-6 weeks',
    ]),
    'payments': ('Mobile money and local payments', [
        'JamiiTek accepts M-Pesa, Tigo Pesa, Airtel Money, CRDB and NMB',
        'Websites and bots can send customers straight to WhatsApp to order and pay',
    ]),
    'company': ('About JamiiTek', [
        'Digital studio based in Dar es Salaam, Tanzania, serving East Africa',
        'Builds websites, AI WhatsApp bots, hosting, domains, mobile apps and systems',
        'Clear pricing, plain-language explanations, support after launch on WhatsApp',
        'Believes every business deserves to be found online — not only the big ones',
    ]),
}


def gather_topics():
    """Rudisha {ufunguo: (jina, [ukweli…])} — mada zote ambazo AI inaweza kuandika."""
    topics = dict(CORE_FACTS)

    try:
        from apps.models import Service
        for s in Service.objects.all().order_by('order', 'id')[:20]:
            desc = re.sub(r'<[^>]+>', ' ', s.description or '')
            desc = re.sub(r'\s+', ' ', desc).strip()
            facts = [x for x in [s.summary, desc[:700]] if x]
            if facts:
                topics[f'service-{s.pk}'] = (s.service_type, facts)
    except Exception:
        logger.exception('Spotlight: kusoma Services kumeshindwa')

    try:
        from apps.chatbot.models import SubscriptionPlan
        plans = []
        for p in SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order'):
            limit = 'unlimited messages' if p.msg_limit == 0 else f'{p.msg_limit:,} messages/month'
            feats = ', '.join(str(f) for f in (p.features or [])[:6])
            plans.append(f'{p.name} plan: TSh {p.price_tzs:,}/month, {limit}' + (f' — {feats}' if feats else ''))
        if plans:
            name, facts = topics['jamiibot']
            topics['jamiibot-plans'] = ('JamiiBot plans and pricing', facts[:3] + plans)
    except Exception:
        logger.exception('Spotlight: kusoma mipango ya JamiiBot kumeshindwa')

    try:
        from apps.models import WebsiteTemplate
        tpls = list(WebsiteTemplate.objects.all()[:40])
        if tpls:
            cats = sorted({t.get_category_display() for t in tpls if t.category})
            examples = [f'{t.name} ({t.get_category_display()}): {(t.description or "")[:120]}' for t in tpls[:6]]
            topics['templates'] = ('Ready-made website templates', [
                f'{len(tpls)} ready-made website templates in the JamiiTek marketplace (jamiitek.com/templates/)',
                'Categories: ' + ', '.join(cats),
                'Each template can be previewed live on mobile, tablet and desktop before buying',
            ] + examples)
    except Exception:
        logger.exception('Spotlight: kusoma templates kumeshindwa')

    try:
        from apps.models import WebsiteType
        types = [f'{w.name}' + (f': {w.description[:100]}' if w.description else '')
                 for w in WebsiteType.objects.all()[:15]]
        if types:
            topics['website-types'] = ('Types of websites JamiiTek builds', types)
    except Exception:
        logger.exception('Spotlight: kusoma aina za website kumeshindwa')

    try:
        from apps.site_content import PortfolioItem
        for p in PortfolioItem.objects.filter(is_featured=True)[:12]:
            facts = [f'Project: {p.title}']
            if p.client: facts.append(f'Client: {p.client}')
            if p.category: facts.append(f'Category: {p.get_category_display() if hasattr(p, "get_category_display") else p.category}')
            if p.summary: facts.append(f'Summary: {p.summary}')
            if p.live_url: facts.append(f'Live at: {p.live_url}')
            if p.year: facts.append(f'Year: {p.year}')
            topics[f'case-{p.pk}'] = (f'Case study: {p.title}', facts)
    except Exception:
        logger.exception('Spotlight: kusoma portfolio kumeshindwa')

    return topics


# ─────────────────────────────────────────────
# 2. KUCHAGUA MADA + MTAZAMO AMBAO HAUJATUMIKA
# ─────────────────────────────────────────────
def used_keys():
    from apps.models import BlogPost
    return set(
        k[len(KEY_PREFIX):] for k in
        BlogPost.objects.filter(source_name__startswith=KEY_PREFIX).values_list('source_name', flat=True))


def pick(topics, used, force_topic=None, rng=random):
    """Rudisha (topic_key, angle_key, angle_text) ambayo haijatumika, au None.

    Mada ambazo hazijawahi kuandikwa kabisa zinapewa kipaumbele; kisha mada
    zilizoandikwa mara chache. Kesi halisi (case-*) zinaandikwa kwa mtazamo
    mmoja tu — hadithi moja haiandikwi mara mbili.
    """
    keys = [force_topic] if force_topic else list(topics)
    times_used = {k: sum(1 for u in used if u.split(':', 1)[0] == k) for k in keys}
    rng.shuffle(keys)
    keys.sort(key=lambda k: times_used[k])
    for k in keys:
        if k not in topics:
            continue
        angles = ANGLES[:1] if k.startswith('case-') else ANGLES
        free = [a for a in angles if f'{k}:{a[0]}' not in used]
        if k.startswith('case-') and times_used[k]:
            continue
        if free:
            a = rng.choice(free) if len(free) > 1 else free[0]
            return k, a[0], a[1]
    return None


# ─────────────────────────────────────────────
# 3. KICHWA CHA KIPEKEE
# ─────────────────────────────────────────────
def _norm(t):
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()


def title_clash(title, existing):
    """Rudisha kichwa kilichopo kinachofanana nacho, au None."""
    n = _norm(title)
    if not n:
        return title
    for e in existing:
        en = _norm(e)
        if en == n or SequenceMatcher(None, n, en).ratio() >= TITLE_SIMILARITY:
            return e
    return None


# ─────────────────────────────────────────────
# 4. KUANDIKA (Groq)
# ─────────────────────────────────────────────
_SYS = """You are the content lead at JamiiTek, a digital studio in Dar es Salaam,
Tanzania. Write ONE original, genuinely useful blog article about JamiiTek for
Tanzanian business owners. It is published on JamiiTek's own blog, so it may
promote JamiiTek — but it must teach the reader something real, not read like an ad.

STRICT RULES:
1. Output ONLY valid JSON, no markdown fences. Schema:
   {"title","excerpt","body","meta_title","meta_description","focus_keyword","tags"}
2. "body" = clean HTML using ONLY <h2>,<h3>,<p>,<ul>,<li>,<strong>,<blockquote>.
   No <img>, scripts, styles or inline CSS. 600-900 words.
3. Use ONLY the facts provided about JamiiTek. NEVER invent prices, statistics,
   client names, testimonials, quotes, awards or dates. General advice that is
   common knowledge is fine.
4. Follow the requested ANGLE exactly, and make the article clearly different from
   the earlier articles listed — new points, new structure, new headline.
5. "title" = specific, compelling, max 70 chars, must NOT resemble any title in
   the "titles to avoid" list. Avoid generic titles like "Introducing X".
6. Write in clear, friendly, professional English. Short paragraphs. Use <h2> sections.
7. End with a short call to action pointing to jamiitek.com, WhatsApp or the
   relevant page from the facts.
8. "excerpt" max 300 chars. "meta_title" max 60. "meta_description" max 155 with
   the keyword. "tags" = 3-6 short tags.
"""


def write(topic_name, facts, angle_text, previous_titles, avoid_titles):
    """Rudisha (ok, dict|kosa)."""
    from apps.blog_ai import _client, _clean_html
    from apps.news_blog import _chat, _json, _slug
    client = _client()
    if client is None:
        return False, 'No AI key (GEMINI_API_KEY or GROQ_API_KEY)'

    user = (
        f'TOPIC: {topic_name}\n'
        f'ANGLE: {angle_text}\n\n'
        'FACTS ABOUT JAMIITEK (use only these):\n' + '\n'.join(f'- {f}' for f in facts) + '\n\n'
        + ('EARLIER ARTICLES ON THIS TOPIC (do not repeat their points or headlines):\n'
           + '\n'.join(f'- {t}' for t in previous_titles) + '\n\n' if previous_titles else '')
        + 'TITLES TO AVOID (already used on the blog):\n'
        + '\n'.join(f'- {t}' for t in avoid_titles[:60]) + '\n\n'
        'Write the article now. Return ONLY the JSON object.'
    )
    try:
        raw = _chat(client, temperature=0.8, max_tokens=2600,
                    messages=[{'role': 'system', 'content': _SYS},
                              {'role': 'user', 'content': user}])
        data = _json(raw)
    except Exception as e:
        logger.exception('Spotlight: kuandika kumeshindwa')
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
    return True, {
        'title': title,
        'slug': _slug(title),
        'excerpt': (data.get('excerpt') or '').strip()[:320],
        'body': _clean_html(body),
        'meta_title': (data.get('meta_title') or '').strip()[:70],
        'meta_description': (data.get('meta_description') or '').strip()[:170],
        'focus_keyword': (data.get('focus_keyword') or title).strip()[:100],
        'tags': tags,
    }


# ─────────────────────────────────────────────
# 5. KUENDESHA
# ─────────────────────────────────────────────
def is_spotlight_day(now=None):
    now = now or timezone.localtime()
    return now.weekday() in DAYS


def already_ran_today(now=None):
    from apps.models import BlogPost
    now = now or timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return BlogPost.objects.filter(source_name__startswith=KEY_PREFIX, created_at__gte=start).exists()


def run(force=False, topic=None):
    """
    Andika makala moja ya Spotlight ikiwa leo ni Jumatatu/Jumatano/Jumamosi.
    Rudisha {'created': [BlogPost] , 'skipped': str|None, 'errors': [..]}.
    """
    from apps.models import BlogPost, BlogCategory
    from apps.news_blog import _unique_slug, unsplash_cover

    now = timezone.localtime()
    if not force and not is_spotlight_day(now):
        return {'created': [], 'skipped': f'not a spotlight day ({now:%A})', 'errors': []}
    if not force and already_ran_today(now):
        return {'created': [], 'skipped': 'already wrote today', 'errors': []}

    topics = gather_topics()
    used = used_keys()
    choice = pick(topics, used, force_topic=topic)
    if not choice:
        return {'created': [], 'skipped': None,
                'errors': ['Every topic/angle combination has been used — add a service, '
                           'template or portfolio item, or a new angle in spotlight_blog.ANGLES']}
    tkey, akey, atext = choice
    tname, facts = topics[tkey]

    all_titles = list(BlogPost.objects.values_list('title', flat=True))
    previous = list(BlogPost.objects.filter(source_name__startswith=f'{KEY_PREFIX}{tkey}:')
                    .values_list('title', flat=True))
    avoid = list(previous) + all_titles[:60]

    art, errors = None, []
    for attempt in range(3):
        ok, res = write(tname, facts, atext, previous, avoid)
        if not ok:
            errors.append(res)
            break
        clash = title_clash(res['title'], all_titles)
        if not clash:
            art = res
            break
        errors.append(f'title too similar to "{clash}" — retrying')
        avoid.insert(0, res['title'])
    if not art:
        return {'created': [], 'skipped': None, 'errors': errors or ['no unique title after 3 attempts']}

    cat, _ = BlogCategory.objects.get_or_create(slug=CATEGORY_SLUG, defaults={'name': CATEGORY_NAME})
    autopublish = os.getenv('SPOTLIGHT_AUTOPUBLISH', '').lower() in ('1', 'true', 'yes')
    post = BlogPost.objects.create(
        title=art['title'], slug=_unique_slug(BlogPost, art['slug']), category=cat,
        excerpt=art['excerpt'], body=art['body'],
        cover_image=unsplash_cover(art['focus_keyword'] or tname),
        meta_title=art['meta_title'], meta_description=art['meta_description'],
        focus_keyword=art['focus_keyword'], author_name='JamiiTek',
        status='published' if autopublish else 'draft', is_news=False,
        source_name=f'{KEY_PREFIX}{tkey}:{akey}'[:120],
    )
    logger.info('Spotlight: "%s" (%s:%s)', post.title, tkey, akey)
    return {'created': [post], 'skipped': None, 'errors': [e for e in errors if 'retrying' not in e]}


def run_and_notify(force=False, topic=None):
    """Endesha, kisha mtumie mmiliki email ya kukagua (siku ya Spotlight tu)."""
    from apps.utils import email_notifications as en
    try:
        result = run(force=force, topic=topic)
    except Exception as e:
        logger.exception('Spotlight run failed')
        result = {'created': [], 'skipped': None, 'errors': [f'Crash: {type(e).__name__}: {e}']}

    try:
        if result['created']:
            en.send_blog_review_reminder(
                result['created'],
                subject=f'⭐ JamiiTek Spotlight: "{result["created"][0].title[:60]}" ready for review')
        elif not result['skipped']:
            en.send_news_run_report({'errors': [f'JamiiTek Spotlight: {e}' for e in result['errors']], 'skipped': 0})
    except Exception:
        logger.exception('Spotlight notification failed')
    return result
