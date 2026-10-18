"""
AI kwa hosting: sababu za kusimamisha (suspension) na ujumbe wa matengenezo.

Kila kitu hapa kina fallback ya maandishi ya kawaida — kama AI haipo au
imeshindwa, mfumo unaendelea kufanya kazi bila kusimama.
"""
import os
import re
import logging

logger = logging.getLogger(__name__)

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 35


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


SYSTEM = """You write short, professional hosting notices for JamiiTek, a web
hosting and development company in Tanzania.

RULES:
1. Output ONLY the notice text — no preamble, no quotes, no markdown, no
   labels like "Message:".
2. Be polite and respectful. The client is a valued customer, not a defaulter.
   Never shame, threaten, or use legal language.
3. Be factual and specific: say what happened, what it means, and exactly
   what the client should do next.
4. Keep it SHORT — 2 to 4 sentences maximum.
5. Never invent amounts, dates, or reference numbers that were not given.
6. End with a reassurance that data is safe and the site is restored
   immediately after payment (for suspension notices).
"""


def suspension_reason(website, days_overdue=0, language='en'):
    """
    Sababu ya ndani (internal) ya kusimamisha — inayoonekana kwako.
    Rudisha (ok, text). Ikishindwa, rudisha fallback (ok=False lakini text ipo).
    """
    fallback = (
        f'Hosting expired on {website.hosting_end_date:%d %b %Y} '
        f'({days_overdue} day(s) overdue). Automatically suspended by the system.'
    )
    client = _client()
    if client is None:
        return False, fallback

    lang_note = 'Write in Swahili.' if language == 'sw' else 'Write in English.'
    user = (
        f"Write a SHORT internal note (1-2 sentences) explaining why this "
        f"website was automatically suspended, for our own records.\n\n"
        f"Website: {website.name}\n"
        f"Client: {website.client.name}\n"
        f"Hosting expired: {website.hosting_end_date:%d %b %Y}\n"
        f"Days overdue: {days_overdue}\n"
        f"Monthly cost: TZS {website.monthly_cost:,.0f}\n\n"
        f"{lang_note} Factual and neutral — this is an internal record."
    )
    ok, text = _ask(user)
    return (True, text) if ok else (False, fallback)


def suspension_message(website, days_overdue=0, language='en'):
    """
    Ujumbe unaomwonekana MTEJA kwenye tovuti iliyosimamishwa.
    Rudisha (ok, text) — daima kuna text.
    """
    if language == 'sw':
        fallback = (
            f'Huduma ya {website.name} imesimamishwa kwa muda kwa sababu muda '
            f'wa hosting uliisha tarehe {website.hosting_end_date:%d %b %Y}. '
            f'Taarifa zako zote ni salama. Tafadhali lipia ili tovuti irudi '
            f'mtandaoni mara moja. Wasiliana nasi: info@jamiitek.com'
        )
    else:
        fallback = (
            f'{website.name} is temporarily suspended because the hosting period '
            f'ended on {website.hosting_end_date:%d %b %Y}. All your data is safe. '
            f'Please renew to restore the site immediately. '
            f'Contact us: info@jamiitek.com'
        )

    client = _client()
    if client is None:
        return False, fallback

    lang_note = ('Write in warm, professional Tanzanian Swahili.'
                 if language == 'sw' else 'Write in English.')
    user = (
        f"Write the notice a visitor sees on a temporarily suspended website.\n\n"
        f"Website: {website.name}\n"
        f"Client: {website.client.name}\n"
        f"Hosting ended: {website.hosting_end_date:%d %b %Y}\n"
        f"Days overdue: {days_overdue}\n"
        f"Renewal contact: info@jamiitek.com\n\n"
        f"{lang_note} Reassure them their data is safe and the site returns "
        f"as soon as hosting is renewed. Polite and respectful."
    )
    ok, text = _ask(user)
    return (True, text) if ok else (False, fallback)


def maintenance_message(website, problem='', language='en'):
    """
    Ujumbe wa matengenezo — pale mfumo unapokuwa na tatizo la kiufundi.
    Rudisha (ok, text) — daima kuna text.
    """
    if language == 'sw':
        fallback = (
            f'{website.name} iko kwenye matengenezo kwa sasa. Timu yetu ya '
            f'kiufundi inashughulikia jambo hili na tovuti itarudi mtandaoni '
            f'hivi karibuni. Taarifa zako zote ni salama. Samahani kwa usumbufu.'
        )
    else:
        fallback = (
            f'{website.name} is currently under maintenance. Our technical team '
            f'is working on it and the site will be back online shortly. '
            f'All your data is safe. We apologise for the inconvenience.'
        )

    client = _client()
    if client is None:
        return False, fallback

    lang_note = ('Write in warm, professional Tanzanian Swahili.'
                 if language == 'sw' else 'Write in English.')
    user = (
        f"Write the notice visitors see while a website is under maintenance "
        f"due to a technical issue on our side.\n\n"
        f"Website: {website.name}\n"
        f"Technical note (internal, do NOT repeat verbatim or expose technical "
        f"details to visitors): {problem or 'system issue detected'}\n\n"
        f"{lang_note} Apologise briefly, reassure that data is safe, and say "
        f"the team is working on it. Do NOT mention payment or suspension — "
        f"this is OUR issue, not the client's."
    )
    ok, text = _ask(user)
    return (True, text) if ok else (False, fallback)


def _ask(user_prompt):
    """Piga simu AI. Rudisha (ok, text)."""
    client = _client()
    if client is None:
        return False, ''
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.5, max_tokens=350,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user_prompt}],
            timeout=TIMEOUT,
        )
        text = (resp.choices[0].message.content or '').strip()
    except Exception as e:
        logger.warning('hosting_ai call failed: %s', type(e).__name__)
        return False, ''

    text = text.strip().strip('"').strip("'")
    if text.startswith('```'):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text).strip()
    text = re.sub(r'<[^>]+>', '', text)          # hakuna HTML
    if not text or len(text) < 15:               # jibu lisilo na maana
        return False, ''
    return True, text[:1200]
