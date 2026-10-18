"""
AI Blog Writer — inaandika RASIMU za makala za blog kwa JamiiTek.

Falsafa: AI inaandika rasimu (status='draft') TU. Mmiliki anakagua, anarekebisha,
kisha anabonyeza Publish. AI haichapishi yenyewe — hii inalinda brand + inakidhi
sheria za Google kuhusu AI content isiyokaguliwa.

Inachagua mada AMBAYO bado haijaandikwa (haisirudii), inabadilisha lugha
(SW/EN), na inaelekeza kila makala kushawishi watumiaji kuhusu huduma za JamiiTek
bila kuwa tangazo la wazi mno.
"""
import os
import re
import json
import logging
import random

logger = logging.getLogger(__name__)

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 60


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


# ── Bank ya mada — AI inachagua ambayo bado haijaandikwa ──
# (topic, language, focus_keyword)
TOPIC_BANK = [
    ("Jinsi ya kutengeneza website kwa biashara ndogo Tanzania", "sw", "website biashara ndogo Tanzania"),
    ("Why every Tanzanian business needs a website in 2026", "en", "business website Tanzania"),
    ("WhatsApp bot ni nini na inasaidiaje biashara yako", "sw", "WhatsApp bot biashara"),
    ("How AI WhatsApp bots help you sell 24/7 in Tanzania", "en", "AI WhatsApp bot Tanzania"),
    ("Gharama za kutengeneza website Tanzania: mwongozo wa bei", "sw", "gharama website Tanzania"),
    ("SEO for beginners: how to appear on Google in Tanzania", "en", "SEO Tanzania"),
    ("Jinsi ya kupata wateja mtandaoni kwa biashara yako", "sw", "kupata wateja mtandaoni"),
    ("E-commerce in Tanzania: how to start selling online", "en", "e-commerce Tanzania"),
    ("Kwa nini biashara yako inahitaji domain ya kitaalamu", "sw", "domain biashara Tanzania"),
    ("Website vs social media: which does your business need?", "en", "website vs social media business"),
    ("Jinsi ya kuandika maudhui ya website yanayovutia wateja", "sw", "maudhui website"),
    ("5 signs your business is losing customers without a website", "en", "business website customers"),
    ("Namna ya kutumia AI kukuza biashara yako Tanzania", "sw", "AI biashara Tanzania"),
    ("Mobile-first design: why it matters for Tanzanian users", "en", "mobile website Tanzania"),
    ("Jinsi ya kuunganisha WhatsApp na website yako", "sw", "WhatsApp website biashara"),
    ("From idea to launch: building your first website in a week", "en", "build website week"),
    ("Faida za web hosting ya kuaminika kwa biashara yako", "sw", "web hosting Tanzania"),
    ("How restaurants in Tanzania can take orders online", "en", "restaurant website Tanzania"),
    ("Jinsi ya kuongeza mauzo kwa kutumia website na AI bot", "sw", "kuongeza mauzo website"),
    ("Building trust online: what makes customers buy from you", "en", "online trust business Tanzania"),
]


SYSTEM = """You are a senior content writer for JamiiTek, Tanzania's modern web
development company. JamiiTek builds websites, AI WhatsApp bots (JamiiBot), web
hosting, and domains for businesses across Tanzania.

Write a helpful, engaging blog article that genuinely helps Tanzanian business
owners — while naturally showing how JamiiTek's services solve their problems.

STRICT RULES:
1. Output ONLY valid JSON, no markdown fences, no preamble. Schema:
   {"title": "...", "excerpt": "...", "body": "...", "meta_description": "..."}
2. "body" must be clean HTML using <h2>, <h3>, <p>, <ul>, <li>, <strong> only.
   NO <html>, <head>, <style>, <script>, or inline styles. 700-1100 words.
3. Write in the SPECIFIED LANGUAGE. If Swahili, use natural Tanzanian Swahili
   (not textbook Swahili). If English, keep it simple and clear.
4. Be genuinely useful FIRST. Teach something real. Then weave in how JamiiTek
   helps — mention JamiiTek or JamiiBot naturally 2-4 times, not as spam.
5. End with a soft call-to-action inviting them to start a project with JamiiTek.
6. "excerpt" = 1-2 sentence summary (max 300 chars). "meta_description" = SEO
   description (max 155 chars) with the focus keyword.
7. "title" should be catchy and include the main keyword. Max 65 chars.
8. Vary your structure and tone so articles don't feel templated. Use real
   Tanzanian context (towns, mobile money, WhatsApp culture, local business types).
9. NEVER invent specific prices unless asked — speak generally about affordability.
   NEVER make false claims or fake statistics.
"""


def pick_topic(existing_titles):
    """Chagua mada ambayo bado haijaandikwa (fuzzy match kwa keyword)."""
    existing_lower = ' '.join(existing_titles).lower()
    available = []
    for topic, lang, kw in TOPIC_BANK:
        # Kama keyword kuu ya mada haipo kwenye titles zilizopo, ni mpya
        kw_core = kw.split()[0].lower()
        topic_core = topic.lower()[:20]
        if topic_core not in existing_lower and kw.lower() not in existing_lower:
            available.append((topic, lang, kw))
    if not available:
        # Zote zimeandikwa — chagua random (mzunguko mpya)
        available = TOPIC_BANK
    return random.choice(available)


def generate_draft(existing_titles=None):
    """
    Rudisha (ok, dict_or_error).
    dict: {title, slug, excerpt, body, meta_description, focus_keyword, language}
    """
    client = _client()
    if client is None:
        return False, 'AI is not configured (GEMINI_API_KEY or GROQ_API_KEY missing).'

    existing_titles = existing_titles or []
    topic, lang, keyword = pick_topic(existing_titles)
    lang_name = 'Swahili' if lang == 'sw' else 'English'

    user = (
        f'Write a blog article for JamiiTek.\n'
        f'Topic: "{topic}"\n'
        f'Language: {lang_name}\n'
        f'Focus keyword (use naturally): "{keyword}"\n\n'
        f'Return ONLY the JSON object.'
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.85,   # ubunifu zaidi ili zisifanane
            max_tokens=2600,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            timeout=TIMEOUT,
        )
        raw = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('AI blog generation failed')
        return False, f'AI error ({type(e).__name__})'

    # Safisha fences kama zipo
    if raw.startswith('```'):
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Jaribu kutoa JSON kwa regex
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return False, 'AI did not return valid JSON'
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return False, 'AI returned malformed JSON'

    title = (data.get('title') or '').strip()[:200]
    body = (data.get('body') or '').strip()
    if not title or not body:
        return False, 'AI response missing title or body'

    # Slug kutoka title
    slug = _slugify(title)

    return True, {
        'title': title,
        'slug': slug,
        'excerpt': (data.get('excerpt') or '').strip()[:320],
        'body': _clean_html(body),
        'meta_description': (data.get('meta_description') or '').strip()[:170],
        'focus_keyword': keyword,
        'language': lang,
    }


def _slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text).strip('-')
    return text[:200] or 'makala'


def _clean_html(html):
    """Ondoa tags hatari — allowlist (apps/html_sanitize.py), si regex."""
    from apps.html_sanitize import clean_html
    html = re.sub(r'\sstyle="[^"]*"', '', html or '', flags=re.I)
    return clean_html(html)
