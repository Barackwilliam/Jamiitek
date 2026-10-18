"""
AI Proposal Writer — inaandaa mapendekezo ya kitaalamu (EN + SW).

generate_proposal: mapendekezo mazima (summary, scope, about) kwa lugha zote.
assist_field: msaada kwa field moja (summary, scope, about, section).
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


SYSTEM = """You are a senior proposal writer for JamiiTek, a professional web
development company in Dar es Salaam, Tanzania. You write persuasive,
client-winning business proposals that meet international standards.

You will write the SAME proposal content in BOTH English and Swahili.

STRICT RULES:
1. Output ONLY valid JSON, no markdown, no preamble. Schema:
   {"summary_en":"...","summary_sw":"...","scope_en":"...","scope_sw":"...","about_en":"...","about_sw":"..."}
   CRITICAL: Output as a SINGLE LINE. Any newline inside a value MUST be the
   two characters backslash-n (\\n), never a real line break.
2. Content guidance:
   - summary: A compelling executive summary (2-3 short paragraphs). Address
     the client's need, and how JamiiTek will solve it. Warm but professional.
   - scope: What JamiiTek will do — the approach and what's included. Can use
     short paragraphs. Be concrete about a web/digital project.
   - about: "Why JamiiTek" — brief, confident positioning (Tanzania-based,
     modern stack, AI WhatsApp bots, reliable delivery). 1-2 paragraphs.
3. Plain text with simple line breaks (\\n) between paragraphs. NO HTML tags,
   NO markdown, NO bullet symbols unless natural.
4. Swahili must be natural, professional Tanzanian business Swahili.
5. Be persuasive and specific to the project given, but NEVER invent fake
   statistics, fake client names, or specific prices.
"""


def generate_proposal(info):
    """
    info: {client_name, company, project_name, title, currency}
    Rudisha (ok, dict) — dict: {summary_en,summary_sw,scope_en,scope_sw,about_en,about_sw}
    """
    client = _client()
    if client is None:
        return False, 'AI is not configured (GEMINI_API_KEY or GROQ_API_KEY missing).'

    user = (
        f"Write a professional web development proposal.\n\n"
        f"Client: {info.get('client_name', '')}\n"
        f"Company: {info.get('company', '')}\n"
        f"Project: {info.get('project_name') or info.get('title', 'Website Project')}\n\n"
        f"Write the summary, scope, and about sections in BOTH English and "
        f"Swahili now. Return ONLY the JSON object."
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.6, max_tokens=4000,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
            timeout=TIMEOUT,
        )
        raw = resp.choices[0].message.content.strip()
        finish = resp.choices[0].finish_reason
    except Exception as e:
        logger.exception('AI proposal generation failed')
        return False, f'AI error ({type(e).__name__})'

    if raw.startswith('```'):
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()

    data = _parse_json_lenient(raw)
    if data is None:
        if finish == 'length':
            return False, 'AI response was cut off. Please try again.'
        return False, 'AI returned malformed JSON. Please try again.'

    # Angalau summary_en ipo
    if not data.get('summary_en') and not data.get('summary_sw'):
        return False, 'AI response missing content'

    clean = {}
    for k in ('summary_en', 'summary_sw', 'scope_en', 'scope_sw', 'about_en', 'about_sw'):
        clean[k] = _strip_tags(data.get(k, ''))
    return True, clean


FIELD_PROMPTS = {
    'summary': "Write a compelling executive summary for a web development proposal (2-3 short paragraphs). Address the client's need and how JamiiTek solves it.",
    'scope': "Write the 'Scope of Work' for a web development proposal — the approach and what's included. Concrete and professional.",
    'about': "Write a brief, confident 'Why JamiiTek' section for a proposal (Tanzania-based web & AI company, modern stack, reliable).",
    'section': "Write a professional proposal section (heading + 1-2 short paragraphs) on the given topic. Return as: HEADING||BODY",
    'title': "Suggest a professional proposal title for this project. Just the title, max 8 words.",
}


def assist_field(field_type, context='', language='en'):
    client = _client()
    if client is None:
        return False, 'AI not configured.'
    base = FIELD_PROMPTS.get(field_type, "Write professional proposal text.")
    lang_note = 'Respond in natural Tanzanian business Swahili.' if language == 'sw' else 'Respond in English.'
    system = ("You are a professional proposal writing assistant for JamiiTek, "
              "a web development company in Tanzania. Write concise, persuasive, "
              "professional text. Output ONLY the requested text — no preamble, "
              "no quotes, no markdown.")
    user = f"{base}\n{lang_note}\n\nProject context: {context or 'Website development project'}\n\nWrite it now:"
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.65, max_tokens=600,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            timeout=40,
        )
        text = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('proposal assist_field failed')
        return False, f'AI error ({type(e).__name__})'
    text = text.strip().strip('"').strip("'")
    if text.startswith('```'):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text).strip()
    return True, text[:2500]


def _strip_tags(text):
    """Ondoa HTML tags — proposal ni plain text."""
    text = re.sub(r'<[^>]+>', '', text or '')
    return text.strip()


def _parse_json_lenient(raw):
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
    for key in ('summary_en', 'summary_sw', 'scope_en', 'scope_sw', 'about_en', 'about_sw'):
        m = re.search(rf'"{key}"\s*:\s*"(.*?)"\s*(?:,\s*"[a-z_]+"\s*:|}}\s*$)', raw, re.DOTALL)
        if m:
            try:
                result[key] = json.loads(f'"{m.group(1)}"', strict=False)
            except (json.JSONDecodeError, ValueError):
                result[key] = m.group(1)
    return result if result.get('summary_en') or result.get('summary_sw') else None


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
