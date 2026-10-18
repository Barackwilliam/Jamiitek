"""
AI kwa Company Profile na Invoice.

generate_profile: inaandika about/mission/vision (EN + SW) kwa profile.
assist_profile_field: msaada kwa field moja ya profile.
assist_invoice_field: msaada kwa field moja ya invoice (desc, notes, terms).
"""
import os
import re
import json
import logging

logger = logging.getLogger(__name__)

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 75


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


# ── COMPANY PROFILE ──

PROFILE_SYSTEM = """You write company profile copy for JamiiTek, a Tanzanian
digital agency in Dar es Salaam specialising in web development, mobile apps
(Flutter), WhatsApp/AI automation, USSD services, e-commerce, SEO and SaaS
platforms for the East African market.

You write the SAME content in BOTH English and Swahili.

STRICT RULES:
1. Output ONLY valid JSON, no markdown, no preamble. Schema:
   {"about_en":"...","about_sw":"...","mission_en":"...","mission_sw":"...","vision_en":"...","vision_sw":"..."}
   CRITICAL: Output as a SINGLE LINE. Any newline inside a value MUST be the
   two characters backslash-n (\\n), never a real line break.
2. Content:
   - about: 2 short paragraphs describing the company, its focus, and its
     commitment to the African market. Confident and professional.
   - mission: ONE clear sentence-or-two mission statement.
   - vision: ONE clear sentence-or-two vision statement.
3. Plain text only. NO HTML, NO markdown, NO bullet symbols.
4. Swahili must be natural, professional Tanzanian business Swahili.
5. Never invent fake statistics, awards, staff numbers, or client names.
"""


def generate_profile(info=None):
    """Rudisha (ok, {about_en, about_sw, mission_en, mission_sw, vision_en, vision_sw})."""
    client = _client()
    if client is None:
        return False, 'AI is not configured (GEMINI_API_KEY or GROQ_API_KEY missing).'

    info = info or {}
    default_tagline = "Building Tanzania's Digital Future"
    user = (
        f"Company: {info.get('company_name', 'JamiiTek Digital Agency')}\n"
        f"Tagline: {info.get('tagline') or default_tagline}\n"
        f"Location: {info.get('address', 'Dar es Salaam, Tanzania')}\n\n"
        "Write the about, mission and vision sections in BOTH English and "
        "Swahili now. Return ONLY the JSON object."
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.6, max_tokens=3000,
            messages=[{"role": "system", "content": PROFILE_SYSTEM},
                      {"role": "user", "content": user}],
            timeout=TIMEOUT,
        )
        raw = resp.choices[0].message.content.strip()
        finish = resp.choices[0].finish_reason
    except Exception as e:
        logger.exception('AI profile generation failed')
        return False, f'AI error ({type(e).__name__})'

    if raw.startswith('```'):
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()

    keys = ('about_en', 'about_sw', 'mission_en', 'mission_sw', 'vision_en', 'vision_sw')
    data = _parse_json_lenient(raw, keys)
    if data is None:
        if finish == 'length':
            return False, 'AI response was cut off. Please try again.'
        return False, 'AI returned malformed JSON. Please try again.'
    if not data.get('about_en') and not data.get('about_sw'):
        return False, 'AI response missing content'

    return True, {k: _strip_tags(data.get(k, '')) for k in keys}


PROFILE_FIELD_PROMPTS = {
    'about': "Write an 'About the company' section for JamiiTek's company profile (2 short paragraphs). Confident, professional, focused on the Tanzanian and East African market.",
    'mission': "Write a clear, inspiring mission statement for JamiiTek (1-2 sentences).",
    'vision': "Write a clear, ambitious vision statement for JamiiTek (1-2 sentences).",
    'service': "Write a short service description (1-2 sentences) for a company profile, for the service named in the context. Concrete and benefit-focused.",
    'why': "Write ONE short 'why choose us' bullet point for JamiiTek (one line, no bullet symbol).",
    'section': "Write a professional company-profile section (heading + 1-2 short paragraphs) on the given topic. Return as: HEADING||BODY",
    'pricing_note': "Write a short, honest pricing note for a company profile — explaining that pricing is tailored, with flexible payment terms. 2-3 sentences.",
}


# ── INVOICE ──

INVOICE_FIELD_PROMPTS = {
    'item': "Write a clear, professional invoice line-item description for the work named in the context. One short phrase, no pricing.",
    'notes': "Write a short, polite invoice note to the client (thanks for the business, payment instructions reminder). 1-2 sentences.",
    'terms': "Write concise invoice payment terms (e.g. due within X days, late payment note). One or two short lines.",
    'title': "Suggest a clear invoice title for this work. Just the title, max 8 words.",
}


def assist_field(field_type, context='', language='en', kind='profile'):
    """
    kind: 'profile' au 'invoice' — inaamua orodha ya prompts.
    Rudisha (ok, text).
    """
    client = _client()
    if client is None:
        return False, 'AI not configured.'

    prompts = PROFILE_FIELD_PROMPTS if kind == 'profile' else INVOICE_FIELD_PROMPTS
    base = prompts.get(field_type)
    if base is None:
        base = "Write short, professional business text for the following."

    lang_note = ('Respond in natural Tanzanian business Swahili.'
                 if language == 'sw' else 'Respond in English.')
    system = ("You are a professional business writing assistant for JamiiTek, "
              "a digital agency in Tanzania. Write concise, professional text. "
              "Output ONLY the requested text — no preamble, no quotes, no markdown.")
    user = f"{base}\n{lang_note}\n\nContext: {context or 'JamiiTek digital agency'}\n\nWrite it now:"

    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.6, max_tokens=600,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            timeout=40,
        )
        text = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('docs assist_field failed')
        return False, f'AI error ({type(e).__name__})'

    text = text.strip().strip('"').strip("'")
    if text.startswith('```'):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text).strip()
    return True, _strip_tags(text)[:2500]


# ── HELPERS ──

def _strip_tags(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()


def _parse_json_lenient(raw, keys):
    for candidate in (raw, _extract_braces(raw)):
        if not candidate:
            continue
        try:
            return json.loads(candidate, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass
    for candidate in (raw, _extract_braces(raw)):
        if not candidate:
            continue
        fixed = re.sub(r',(\s*[}\]])', r'\1', candidate)
        try:
            return json.loads(fixed, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass
    result = {}
    for key in keys:
        m = re.search(rf'"{key}"\s*:\s*"(.*?)"\s*(?:,\s*"[a-z_]+"\s*:|}}\s*$)', raw, re.DOTALL)
        if m:
            try:
                result[key] = json.loads(f'"{m.group(1)}"', strict=False)
            except (json.JSONDecodeError, ValueError):
                result[key] = m.group(1)
    return result if any(result.values()) else None


def _extract_braces(text):
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]
