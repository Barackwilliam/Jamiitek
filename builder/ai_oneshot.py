"""
One-Shot AI Website Generator
──────────────────────────────
Kutoka sentensi moja ya biashara → website nzima tayari.

Flow:
  1. GENERATE: call moja kubwa ya AI ina-return JSON iliyostructured yenye
     kila kitu (jina, tagline, about, services/products, contact CTAs...)
  2. CRITIQUE: call ya pili ina-review draft ya kwanza kama editor mkali
     wa international standards, kisha ina-return version iliyoboreshwa
  3. APPLY: JSON iliyoboreshwa ina-populated kwenye ClientWebsite +
     collections zake — mteja anasogezwa dashboard yenye website hai.

Design decisions:
  - Calls 2 tu kwa website nzima (siyo per-field) — bajeti safi
  - JSON output enforced kupitia response_format={"type":"json_object"}
  - Timeout ya generous (Groq inaweza kuwa slow kwenye JSON kubwa)
  - Fallback: kama Pass 2 imeshindwa, tunatumia Pass 1 (usiwaache mikono mitupu)
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 60

# Website types tunazoweza kuzalisha (lazima ziwepo kama schema JSON)
SUPPORTED_TYPES = ('tourism', 'ecommerce', 'restaurant', 'events',
                   'companyprofile', 'school', 'realestate', 'ngo', 'default')

# Muundo unaotarajiwa kwenye Pass 1 output — AI ina-follow schema hii
JSON_SCHEMA_HINT = {
    "website_type": "one of: tourism, ecommerce, restaurant, events, companyprofile, school, realestate, ngo, default",
    "site_name": "clean brand name (2-4 words, no emojis, no ALL CAPS)",
    "tagline": "one memorable line (max 90 chars) that positions the brand",
    "hero_headline": "punchy 4-9 word headline for the homepage hero",
    "hero_subline": "supporting 1-2 sentences under the headline",
    "about_us": "3-4 sentence paragraph telling the brand story with heart",
    "why_choose_us": [
        {"title": "short 2-3 word benefit", "description": "one clear sentence"},
        "…exactly 3 items…",
    ],
    "items": [
        {
            "title": "product/service/package name",
            "description": "2-3 sentence description that sells",
            "price": "e.g. '150,000 TZS' or '' if not applicable",
            "extra": {"key": "value pairs for type-specific fields"},
        },
        "…4 to 6 items relevant to this business…",
    ],
    "accent_color": "hex color that matches the brand mood (#RRGGBB)",
    "nav_layout": "one of: top, glass, side, center",
    "design_style": "pick ONE that fits the brand mood: sunset_bold (warm, energetic, consumer brands), clean_minimal (calm, professional, modern services), dark_luxury (premium, high-end, exclusive), fresh_split (friendly, tech-savvy, youthful), sci_fi (futuristic, high-tech, bold — great for tech, gaming, crypto, innovative or youth brands that want a 2090 feel)",
    "palette": {"primary": "vibrant hex for buttons/accents", "deep": "dark hex for backgrounds — both must fit the brand mood and work together"},
}


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


PASS1_SYSTEM = """You are a world-class copywriter and web designer creating
websites for East African businesses (Tanzania, Kenya, Uganda, Rwanda). You
understand the local market — pricing in TZS/KES, WhatsApp-first commerce,
mobile-first users — and you write copy that converts.

You will receive a raw business description (often short, sometimes in
Swahili or mixed English/Swahili). Your job:

1. Understand the business type and pick the right `website_type` from the list.
2. Produce a COMPLETE, PROFESSIONAL first draft in the exact JSON structure
   provided. Every field is required.
3. If pricing is unclear, infer realistic starting prices for the market.
4. Content must be specific to THIS business — never generic filler.
5. Reply in the same language the user used (English or Swahili). Local
   context (place names, phrases like "boda", "duka", "safari") is a plus.

Return ONE JSON object matching the schema. No prose. No markdown fences."""


PASS2_SYSTEM = """You are a ruthless senior editor at a top international
web agency. You have received a first-draft website JSON. Your job is to
review it against professional standards and return an IMPROVED version.

Rate the draft (silently) on:
  - Copy quality: hooks, specificity, clarity of value
  - Emotional pull: does it make a customer want to buy?
  - Local relevance: does it fit an East African market context?
  - Completeness: are all items rich enough to publish as-is?

If any dimension is below 9/10 — REWRITE it. Do not water down; strengthen.
Common problems to fix:
  - Generic taglines ("Best in the business") → make them specific and vivid
  - Bland descriptions → add sensory details, benefits, proof
  - Weak headlines → make them punchy, promise-driven
  - Prices that feel random → align them across items

Return ONE JSON object with the SAME schema. Only the content changes.
Reply in the same language as the input. No prose. No markdown fences."""


def _call(client, system, user, temperature=0.7):
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        max_tokens=3200,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=TIMEOUT,
    )
    raw = resp.choices[0].message.content.strip()
    return json.loads(raw)


def generate_website_plan(business_description: str):
    """
    Rudisha (ok, result_or_error).
    result ni dict yenye kila kitu kinachohitajika kutengeneza website.
    """
    client = _client()
    if client is None:
        return False, 'The AI generator is not configured on the server.'

    if not business_description or len(business_description.strip()) < 8:
        return False, ('Please describe your business in a bit more detail — '
                       'even one or two sentences is enough.')
    if len(business_description) > 2000:
        return False, 'Description is too long (max 2000 characters).'

    prompt = (f"Business description from the user:\n\n"
              f'"""{business_description.strip()}"""\n\n'
              f"Return a JSON object with EXACTLY these keys "
              f"(follow the schema strictly):\n\n"
              f"{json.dumps(JSON_SCHEMA_HINT, indent=2, ensure_ascii=False)}")

    # ── Pass 1: initial draft ────────────────────────────────
    import time
    t0 = time.time()
    try:
        draft = _call(client, PASS1_SYSTEM, prompt, temperature=0.8)
    except json.JSONDecodeError:
        logger.exception('Pass 1 returned invalid JSON')
        return False, 'The AI response was not valid — please try again.'
    except Exception as e:
        logger.exception('Pass 1 failed')
        return False, f'The AI is temporarily unavailable ({type(e).__name__}). Please try again shortly.'

    # ── Pass 2: senior-editor critique + rewrite ─────────────
    # Kama Pass 1 imechukua muda mrefu (mtandao slow), ruka Pass 2 ili
    # jibu lisizidi timeout za proxy (Cloudflare ~100s) — draft inatosha.
    pass1_elapsed = time.time() - t0
    if pass1_elapsed > 25:
        logger.warning('Pass 1 took %.1fs — skipping critique pass', pass1_elapsed)
        final = draft
    else:
      try:
          critique_prompt = (
              "Here is the first-draft website JSON. Improve every weak part "
              "to professional international standards, then return the improved JSON "
              "with the SAME keys.\n\n"
              f"Original business description:\n\"\"\"{business_description.strip()}\"\"\"\n\n"
              f"First draft:\n{json.dumps(draft, ensure_ascii=False)}"
          )
          final = _call(client, PASS2_SYSTEM, critique_prompt, temperature=0.6)
      except Exception:
          logger.exception('Pass 2 failed — falling back to draft')
          final = draft  # graceful: mteja bado anapata output ya heshima

    # ── Validation na cleanup ────────────────────────────────
    if not isinstance(final, dict):
        return False, 'Unexpected AI output — please try again.'

    website_type = str(final.get('website_type', 'default')).lower().strip()
    if website_type not in SUPPORTED_TYPES:
        website_type = 'default'
    final['website_type'] = website_type

    if not isinstance(final.get('items'), list):
        final['items'] = []
    if not isinstance(final.get('why_choose_us'), list):
        final['why_choose_us'] = []

    # Weka defaults salama kwa kila field ambayo AI imeikosa
    final.setdefault('site_name', 'My Business')
    final.setdefault('tagline', '')
    final.setdefault('hero_headline', final['site_name'])
    final.setdefault('hero_subline', final.get('tagline', ''))
    final.setdefault('about_us', '')
    final.setdefault('accent_color', '#e8a13c')
    final.setdefault('nav_layout', 'top')

    # Sanitize accent_color ijawe hex halali
    ac = str(final['accent_color']).strip()
    if not (ac.startswith('#') and len(ac) in (4, 7)):
        final['accent_color'] = '#e8a13c'

    nav = str(final['nav_layout']).lower().strip()
    if nav not in ('top', 'glass', 'side', 'center'):
        final['nav_layout'] = 'top'
    else:
        final['nav_layout'] = nav

    # Design style + palette
    from .ai_designs import STYLES
    style = str(final.get('design_style', '')).lower().strip()
    final['design_style'] = style if style in STYLES else 'sunset_bold'
    pal = final.get('palette') if isinstance(final.get('palette'), dict) else {}
    def _hex(v, fallback):
        v = str(v or '').strip()
        return v if (v.startswith('#') and len(v) in (4, 7)) else fallback
    final['palette'] = {
        'primary': _hex(pal.get('primary'), final['accent_color']),
        'deep': _hex(pal.get('deep'), '#1a1428'),
    }

    return True, final


# ── COLLECTION MAPPING: kila website_type → collection ya main ya items ──
# One-Shot AI ina-generate items 4-6 ya generic. Tunahitaji kujua items hizo
# zinaenda wapi — kwenye packages, products, menu, n.k.
PRIMARY_COLLECTION = {
    'tourism': 'packages',
    'ecommerce': 'products',
    'restaurant': 'menu',
    'events': 'events',
    'companyprofile': 'services',
    'school': 'programs',
    'realestate': 'properties',
    'ngo': 'projects',
    'default': 'services',
}


SUGGEST_SYSTEM = """You are a product strategist for East African businesses.
Given a business context and its existing catalog items, suggest NEW items
that complement the catalog — realistic, specific, priced for the local market.

Rules:
1. Never duplicate or closely mirror existing items.
2. Spread across price points (entry, mid, premium) where it makes sense.
3. Each description must be 2-3 sentences that SELL — specific, vivid,
   benefit-driven. No generic filler.
4. Reply in the same language as the existing content (English or Swahili).
5. Return ONE JSON object: {"items": [{"title": ..., "description": ...,
   "price": ..., "extra": {...}}, ...]} — nothing else."""


def suggest_items(site, collection, count=5):
    """
    AI ina-generate items mpya za collection kwa muktadha wa zilizopo.
    Rudisha (ok, items_list_or_error).
    """
    client = _client()
    if client is None:
        return False, 'AI is not configured on the server.'

    existing = list(collection.items.values_list('title', flat=True)[:20])
    field_keys = [f.get('key') for f in collection.fields
                  if isinstance(f, dict) and f.get('key')][:8]

    prompt = (
        f'Business: "{site.site_name}" (type: {site.website_type})\n'
        f'Tagline: "{site.tagline}"\n'
        f'Catalog section: {collection.name}\n'
        f'Existing items (do NOT duplicate): {json.dumps(existing, ensure_ascii=False)}\n'
        f'Item fields available for "extra": {field_keys}\n\n'
        f'Suggest exactly {count} NEW items for this catalog. '
        f'Return JSON: {{"items": [{{"title", "description", "price", "extra"}}]}}'
    )

    try:
        result = _call(client, SUGGEST_SYSTEM, prompt, temperature=0.85)
    except json.JSONDecodeError:
        logger.exception('suggest_items: invalid JSON')
        return False, 'The AI response was not valid — please try again.'
    except Exception as e:
        logger.exception('suggest_items failed')
        return False, f'The AI is temporarily unavailable ({type(e).__name__}).'

    items = result.get('items') if isinstance(result, dict) else None
    if not isinstance(items, list) or not items:
        return False, 'The AI returned no suggestions — please try again.'

    clean = []
    existing_lower = {t.lower() for t in existing}
    for it in items[:count + 2]:
        if not isinstance(it, dict):
            continue
        title = str(it.get('title', '')).strip()[:200]
        if not title or title.lower() in existing_lower:
            continue
        clean.append({
            'title': title,
            'description': str(it.get('description', ''))[:2000],
            'price': str(it.get('price', ''))[:80],
            'extra': it.get('extra') if isinstance(it.get('extra'), dict) else {},
        })
    if not clean:
        return False, 'All suggestions duplicated existing items — please try again.'
    return True, clean[:count]
