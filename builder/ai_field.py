"""
AI Field Helper — inayotoa content ya sehemu MOJA ya form kwa muktadha kamili.

Tofauti na `ai_assist` (ambayo ni general chat) na `ai_oneshot` (ambayo ni
website nzima), hii ni AI ya "magic button" kila field:

  - Mtu bonyeza ✨ karibu na field ya "About Us"
  - Endpoint hii inasoma: aina ya field, jina la biashara, aina ya website,
    tagline aliyoiweka tayari, na fields nyingine za form
  - Ina-generate content sahihi kwa field HIYO peke yake — sio essay nzima
  - Ina-return text safi (au HTML kwa fields za sections)

Field types tunazoshughulikia:
  - site_name        → jina fupi la brand
  - tagline          → mstari mmoja
  - about_us         → 3-4 sentences
  - hero_headline    → headline ya wow
  - description      → item description (package, product, dish...)
  - features_list    → orodha ya vitu (one per line)
  - why_choose_us    → sababu 3
"""
import os
import json
import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cache TTL ya AI responses (sekunde). AI ni ghali; maombi yanayofanana
# ndani ya dakika 30 yanapata jibu lile lile bila API call.
AI_CACHE_TTL = int(os.getenv('BUILDER_AI_CACHE_TTL', '1800'))

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 30


FIELD_PROMPTS = {
    'site_name': {
        'role': 'a brand naming expert',
        'task': ('Generate a memorable, professional brand name (2-4 words). '
                 'No emojis, no ALL CAPS, no "The" prefix unless it truly fits. '
                 'Make it easy to say and remember. Return ONLY the name.'),
        'max_words': 4,
    },
    'tagline': {
        'role': 'a world-class copywriter',
        'task': ('Write ONE memorable tagline (max 90 characters) that positions '
                 'the brand. Be specific, avoid clichés like "Best in the business". '
                 'Return ONLY the tagline text.'),
        'max_words': 15,
    },
    'about_us': {
        'role': 'a warm, professional storyteller',
        'task': ('Write a 3-4 sentence About Us paragraph that tells the brand '
                 'story with heart. Include what they do, who they serve, and '
                 'one thing that makes them different. Return ONLY the paragraph — '
                 'no heading, no quotes.'),
        'max_words': 100,
    },
    'hero_headline': {
        'role': 'a punchy headline writer',
        'task': ('Write ONE 4-9 word homepage headline that promises a benefit. '
                 'Punchy, specific, promise-driven. Return ONLY the headline.'),
        'max_words': 10,
    },
    'hero_subline': {
        'role': 'a supporting-copy specialist',
        'task': ('Write 1-2 supporting sentences that go under the hero headline. '
                 'Add clarity and one specific proof point. Return ONLY the subline.'),
        'max_words': 30,
    },
    'description': {
        'role': 'a persuasive product-description writer',
        'task': ('Write a 2-3 sentence description that SELLS this specific '
                 'product/service/item. Focus on benefits, not just features. '
                 'Make it specific and vivid. Return ONLY the description.'),
        'max_words': 70,
    },
    'features_list': {
        'role': 'a benefits-focused writer',
        'task': ('Write 4-6 items for this list — one per line, no bullets, '
                 'no numbering. Each line should be short and concrete. '
                 'Return ONLY the list, nothing else.'),
        'max_words': 60,
    },
    'why_choose_us': {
        'role': 'a differentiation strategist',
        'task': ('Write exactly 3 "Why Choose Us" reasons. Format each as: '
                 '"TITLE: one-sentence description" (short title + short reason). '
                 'One per line. Return ONLY the 3 lines.'),
        'max_words': 80,
    },
}


BASE_SYSTEM = """You are helping business owners in Tanzania and East Africa
write website content. You understand the local market: mobile-first users,
WhatsApp commerce, TZS/KES pricing, and the mix of English and Swahili.

Rules:
1. Match the language the user is writing in (English or Swahili — or a mix).
2. Be SPECIFIC to the business context you're given. No generic filler.
3. Follow the exact format requested. No preambles like "Here is..." or
   "Sure!". No markdown, no code fences, no quotes around the output.
4. If the business context is thin, use reasonable, believable specifics —
   never leave the answer generic.

After you draft your answer, silently check it against these criteria:
  - Does it match the format asked for exactly?
  - Is it specific to THIS business?
  - Would a professional web agency ship this as-is?
If any answer is "no", rewrite it before returning. Ship your BEST version."""


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


def _build_context(site, extra_context: dict):
    """Muktadha wa biashara kwa AI — kuchanganya field zilizojazwa na site info."""
    bits = []
    if site is not None:
        bits.append(f'Business name: "{site.site_name}"')
        bits.append(f'Website type: {site.website_type}')
        if site.tagline:
            bits.append(f'Existing tagline: "{site.tagline}"')

    for key, value in (extra_context or {}).items():
        if not value:
            continue
        v = str(value).strip()[:400]
        if v:
            bits.append(f'{key}: "{v}"')

    return '\n'.join(bits) if bits else 'No context provided yet.'


def generate_field(field_type: str, site, extra_context: dict = None,
                   user_hint: str = ''):
    """
    Rudisha (ok, text_or_error).
    field_type — moja ya keys za FIELD_PROMPTS
    site       — ClientWebsite (au None kwa field za signup)
    extra_context — dict ya fields nyingine za form (title ya item, n.k.)
    user_hint  — maelezo ya ziada ambayo mtu ameyaandika (hiari)
    """
    spec = FIELD_PROMPTS.get(field_type)
    if spec is None:
        return False, f'Unknown field type: {field_type}'

    client = _client()
    if client is None:
        return False, 'AI is not configured on the server.'

    context = _build_context(site, extra_context)
    hint_line = f'\n\nUser hint: "{user_hint.strip()[:400]}"' if user_hint.strip() else ''

    # ── Cache: ombi linalofanana (field + context + hint) → jibu lile lile ──
    cache_key = 'aif:' + hashlib.sha256(
        f'{field_type}|{context}|{hint_line}'.encode()).hexdigest()[:40]
    cached = cache.get(cache_key)
    if cached:
        return True, cached

    system = f'{BASE_SYSTEM}\n\nYou are {spec["role"]}.'
    user = (f'{spec["task"]}\n\nBusiness context:\n{context}{hint_line}')

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.75,
            max_tokens=600,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=TIMEOUT,
        )
        text = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('AI field generation failed')
        return False, f'AI is temporarily unavailable ({type(e).__name__}).'

    # Safisha: ondoa quotes za nje, markdown fences, "Here is..." prefixes
    text = text.strip().strip('"').strip("'").strip()
    for prefix in ('Here is', 'Here\'s', 'Sure!', 'Sure,', 'Certainly!', 'Of course!'):
        if text.lower().startswith(prefix.lower()):
            # kata mstari wa kwanza
            parts = text.split('\n', 1)
            text = parts[1].strip() if len(parts) > 1 else ''
    text = text.strip('`').strip()

    if not text:
        return False, 'AI returned an empty response — please try again.'

    cache.set(cache_key, text, AI_CACHE_TTL)
    return True, text
