"""
AI Contract Writer — inaandaa rasimu za mikataba ya kitaalamu (EN + SW).

Falsafa: AI inaandaa RASIMU. Mmiliki (JamiiTek) anaboresha kabla ya kutuma
kwa mteja. AI haisaini chochote — signing ni ya mteja pekee.

Inaandaa mkataba kwa lugha ZOTE mbili (Kiingereza + Kiswahili) ili mteja
achague. Mkataba unafuata muundo wa kimataifa: parties, scope, deliverables,
payment, timeline, IP rights, warranties, termination, governing law.
"""
import os
import re
import json
import logging

logger = logging.getLogger(__name__)

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 90


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


SYSTEM = """You are a professional contract writer for JamiiTek, a web
development company in Tanzania. You draft clear, professional service
agreements that meet international standards while being appropriate for
the Tanzanian business context.

You will draft the SAME contract in BOTH English and Swahili.

STRICT RULES:
1. Output ONLY valid JSON, no markdown, no preamble. Schema:
   {"title": "...", "body_en": "...", "body_sw": "..."}
   CRITICAL: Output the JSON as a SINGLE LINE with no literal line breaks
   inside string values. Any newline within body_en or body_sw MUST be
   written as the two characters backslash-n (\\n), never as an actual
   line break. This is essential for the JSON to parse correctly.
2. "body_en" and "body_sw" are the full contract in clean HTML using ONLY:
   <h2>, <h3>, <p>, <ul>, <li>, <strong>, <ol>. NO styles, scripts, or tables.
3. The contract MUST include these numbered sections (adapt to the project):
   1. Parties (JamiiTek as "the Provider" and the client as "the Client")
   2. Scope of Work / Services (what will be delivered)
   3. Deliverables
   4. Timeline / Delivery Schedule
   5. Payment Terms (amount, currency, schedule)
   6. Client Responsibilities (providing content, feedback, access)
   7. Revisions and Changes
   8. Intellectual Property (ownership transfers on final payment)
   9. Confidentiality
   10. Warranties and Support
   11. Termination
   12. Limitation of Liability
   13. Governing Law (laws of the United Republic of Tanzania)
   14. Entire Agreement
4. Be professional, clear, and fair to both parties. Use real contract
   language, not casual text. Avoid making up specific facts not provided —
   use clear placeholders like [describe deliverable] only if truly needed,
   but prefer to write complete, sensible clauses based on the project info.
5. The Swahili version must be natural, professional Tanzanian Swahili — a
   proper legal-business register, not a rough translation.
6. Do NOT include a title heading inside the body (the title is separate).
   Start body with <h2>1. Parties</h2> style sections.
7. Reference the payment amount, currency, timeline, and payment terms given.
8. CRITICAL — DO NOT write a signatures section, signature blocks, signature
   lines, name/date blanks, or ANY underscores (_____) or dashes (-----) used
   as fill-in lines. The application renders a professional signature block
   automatically after your text. Section 14 must ONLY state that this is the
   entire agreement — nothing about signing lines. End the body after that
   clause.
"""


def generate_contract(project_info):
    """
    project_info: dict yenye {client_name, company, project_name, title,
                              total_amount, currency, payment_terms, timeline,
                              scope, provider_rep}
    Rudisha (ok, dict_or_error) — dict: {title, body_en, body_sw}
    """
    client = _client()
    if client is None:
        return False, 'AI is not configured (GEMINI_API_KEY or GROQ_API_KEY missing).'

    info = project_info
    amount_line = ''
    if info.get('total_amount'):
        amount_line = f"Total amount: {info.get('currency', 'TZS')} {info['total_amount']}\n"

    user = (
        f"Draft a professional service agreement for the following project.\n\n"
        f"Provider: JamiiTek (web development company, Dar es Salaam, Tanzania)\n"
        f"Provider representative: {info.get('provider_rep') or 'JamiiTek Management'}\n"
        f"Client name: {info.get('client_name', '')}\n"
        f"Client company: {info.get('company', '')}\n"
        f"Project: {info.get('project_name') or info.get('title', 'Website Development')}\n"
        f"{amount_line}"
        f"Payment terms: {info.get('payment_terms', 'To be agreed')}\n"
        f"Timeline: {info.get('timeline', 'To be agreed')}\n"
        f"Scope / description: {info.get('scope', 'Design and development of a website.')}\n\n"
        f"Draft the full contract in BOTH English and Swahili now. Return ONLY the JSON."
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.4,   # chini — mkataba unahitaji usahihi, si ubunifu
            max_tokens=7000,   # mkataba wa EN+SW ni mrefu — epuka kukatika katikati
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            timeout=TIMEOUT,
        )
        raw = resp.choices[0].message.content.strip()
        finish_reason = resp.choices[0].finish_reason
    except Exception as e:
        logger.exception('AI contract generation failed')
        return False, f'AI error ({type(e).__name__})'

    if raw.startswith('```'):
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()

    data = _parse_json_lenient(raw)
    if data is None:
        if finish_reason == 'length':
            return False, ('AI response was cut off (contract too long). '
                           'Try again — it usually succeeds on retry.')
        return False, 'AI returned malformed JSON. Please try again.'

    body_en = _clean_html(data.get('body_en', ''))
    body_sw = _clean_html(data.get('body_sw', ''))
    if not body_en or not body_sw:
        if finish_reason == 'length':
            return False, ('AI response was cut off before finishing both languages. '
                           'Try again — it usually succeeds on retry.')
        return False, 'AI response missing English or Swahili body'

    return True, {
        'title': (data.get('title') or info.get('title') or 'Service Agreement').strip()[:200],
        'body_en': body_en,
        'body_sw': body_sw,
    }


def _parse_json_lenient(raw):
    """
    Jaribu kupata JSON kutoka kwenye output ya AI kwa njia kadhaa, kwa sababu
    LLMs mara nyingi huweka newline halisi ndani ya strings (huvunja JSON
    strict), au huongeza maandishi ya ziada kabla/baada ya JSON.
    Rudisha dict au None.
    """
    # 1. Jaribu moja kwa moja, strict=False inaruhusu control characters
    #    (newline halisi) ndani ya JSON strings — hii ndiyo sababu #1 ya
    #    "malformed JSON" kutoka kwa AI zenye maandishi marefu ya HTML.
    for candidate in (raw, _extract_braces(raw)):
        if not candidate:
            continue
        try:
            return json.loads(candidate, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. Jaribu kurekebisha makosa ya kawaida: trailing commas
    for candidate in (raw, _extract_braces(raw)):
        if not candidate:
            continue
        fixed = re.sub(r',(\s*[}\]])', r'\1', candidate)
        try:
            return json.loads(fixed, strict=False)
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Njia ya mwisho: chukua kila field kwa regex moja kwa moja
    #    (inafanya kazi hata kama JSON nzima imeharibika, mradi kila
    #    field yenyewe iko kamili)
    result = {}
    for key in ('title', 'body_en', 'body_sw'):
        m = re.search(rf'"{key}"\s*:\s*"(.*?)"\s*(?:,\s*"[a-z_]+"\s*:|}}\s*$|}}\s*,)',
                       raw, re.DOTALL)
        if m:
            try:
                # Fungua escapes za JSON (\\n, \\", n.k.) kwa string moja
                result[key] = json.loads(f'"{m.group(1)}"', strict=False)
            except (json.JSONDecodeError, ValueError):
                result[key] = m.group(1)
    return result if result.get('body_en') and result.get('body_sw') else None


def _extract_braces(text):
    """Toa sehemu ya kwanza ya { ... } yenye braces zilizolingana."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]  # haikufunga vizuri — rudisha yote, jaribu tu


def _clean_html(html):
    """Ruhusu tags salama tu, na ondoa signature lines za AI."""
    html = re.sub(r'<(script|style|iframe|head|html|body)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.I)
    html = re.sub(r'</?(?:html|head|body|script|style|iframe)[^>]*>', '', html, flags=re.I)
    html = re.sub(r'\sstyle="[^"]*"', '', html, flags=re.I)
    from apps.html_sanitize import clean_html
    html = clean_html(html)
    html = strip_signature_lines(html)
    return html.strip()


# Maneno ya vichwa vya sehemu za saini (EN + SW)
_SIG_HEADING_WORDS = (
    'signature', 'signatures', 'signed by', 'in witness whereof',
    'saini', 'sahihi', 'kuandikisha', 'kusaini', 'kutia saini',
)


def strip_signature_lines(html):
    """
    Ondoa mistari ya kujaza (____ au ----) na sehemu nzima ya saini kutoka
    kwenye maandishi ya AI. App inaweka signature block yake ya kitaalamu,
    kwa hiyo ya AI ni marudio yasiyopendeza.
    """
    if not html:
        return html

    # 1. Ondoa aya/mistari yenye underscores/dashes za kujaza (3+ mfululizo)
    fill_line = r'(?:_{3,}|-{5,}|\.{6,})'
    # Ondoa <p> au <li> nzima kama ina fill-line
    html = re.sub(rf'<(p|li)[^>]*>(?:(?!</\1>).)*?{fill_line}(?:(?!</\1>).)*?</\1>',
                  '', html, flags=re.DOTALL | re.I)
    # Ondoa fill-lines zilizobaki popote
    html = re.sub(fill_line, '', html)

    # 2. Ondoa sehemu nzima kama kichwa chake ni cha saini
    #    (kutoka <h2>/<h3> ya saini mpaka kichwa kinachofuata au mwisho)
    pattern = re.compile(
        r'<h([23])[^>]*>(?P<head>(?:(?!</h\1>).)*)</h\1>(?P<body>.*?)(?=<h[23][^>]*>|$)',
        flags=re.DOTALL | re.I)

    def _drop_if_signature(m):
        heading = re.sub(r'<[^>]+>', '', m.group('head')).lower()
        if any(w in heading for w in _SIG_HEADING_WORDS):
            return ''
        return m.group(0)

    html = pattern.sub(_drop_if_signature, html)

    # 3. Safisha aya tupu zilizobaki
    html = re.sub(r'<(p|li)[^>]*>\s*(?:&nbsp;|\s)*</\1>', '', html, flags=re.I)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


# ── AI ndogo: msaada kwa field moja ──

FIELD_PROMPTS = {
    'scope': "Write a clear, professional 'Scope of Work' description for a web development project. 2-4 sentences describing what will be delivered.",
    'payment_terms': "Suggest professional payment terms for a web development project (e.g. deposit split, milestones). One concise line.",
    'timeline': "Suggest a realistic project timeline phrase for a web development project (e.g. '3-4 weeks from deposit'). One short line.",
    'title': "Suggest a professional contract title for this project. Just the title, max 8 words.",
    'section': "Write a professional contract section (heading + 1-2 short paragraphs) on the given topic. Return as: HEADING||BODY",
    'deliverable': "Write a concise, professional deliverable line item description for a web project. One short phrase.",
}


def assist_field(field_type, context='', language='en'):
    """
    AI ndogo: inapendekeza maandishi kwa field moja.
    field_type: scope|payment_terms|timeline|title|section|deliverable
    context: maelezo ya ziada (mfano jina la project)
    Rudisha (ok, text_or_error).
    """
    client = _client()
    if client is None:
        return False, 'AI not configured.'

    base = FIELD_PROMPTS.get(field_type, "Write professional contract text for the following.")
    lang_note = 'Respond in Swahili (natural Tanzanian business Swahili).' if language == 'sw' else 'Respond in English.'

    system = (
        "You are a professional contract writing assistant for JamiiTek, a web "
        "development company in Tanzania. You write concise, professional text. "
        "Output ONLY the requested text, no preamble, no quotes, no markdown."
    )
    user = f"{base}\n{lang_note}\n\nProject context: {context or 'Website development project'}\n\nWrite it now:"

    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.6, max_tokens=400,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            timeout=40,
        )
        text = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('assist_field failed')
        return False, f'AI error ({type(e).__name__})'

    # Safisha quotes/fences
    text = text.strip().strip('"').strip("'")
    if text.startswith('```'):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text).strip()
    return True, text[:2000]
