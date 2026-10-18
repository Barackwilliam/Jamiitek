"""
AI Theme Generator — inabadilisha LOOK ya website nzima kwa Global CSS.

Tofauti na ai_field (field moja) au ai_oneshot (site mpya): hii inachukua
website ILIYOPO na maelezo mafupi ('nataka iwe ya kisasa, rangi za bahari')
kisha ina-generate CSS block inayo-override design ya sasa — inatumika pages
ZOTE kupitia site.global_css.

Output ni CSS SAFI (bila markdown, bila <style>), tayari kuingizwa.
"""
import os
import logging

logger = logging.getLogger(__name__)

MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
TIMEOUT = 40


def _client():
    # Gemini kwanza, Groq akiba (apps/llm.py)
    from apps.llm import client
    return client()


THEME_SYSTEM = """You are an expert web designer who writes clean, modern CSS.
You will receive a description of the look a business owner wants, plus their
current brand color. Produce a CSS snippet that restyles their whole website.

STRICT RULES:
1. Output ONLY raw CSS. No markdown, no ```css fences, no <style> tags, no prose.
2. Use broad, safe selectors that apply site-wide: body, h1, h2, h3, p, a,
   section, .jt-nav, .jt-footer, button, and generic patterns. You may target
   sections via `section:nth-of-type(n)` but keep it resilient.
3. NEVER use `!important` on layout properties that could break structure
   (display, position, width on sections). You may use it sparingly on colors
   and typography to override inline styles.
4. Prefer CSS variables where possible: the site exposes --accent.
5. Keep it cohesive: pick a palette, a heading font feel (via font-family
   stacks that are web-safe or common Google fonts already likely loaded),
   consistent spacing, border-radius, and button styling.
6. Include smooth, tasteful touches: subtle transitions, hover states.
7. Be mobile-safe: don't set fixed widths that break small screens.
8. Aim for 40-90 lines of high-quality CSS. No comments needed except section
   headers as /* comments */ if helpful.

The result must look professional and intentional, like a designer made it."""


def generate_theme_css(site, brief: str):
    """Rudisha (ok, css_or_error)."""
    client = _client()
    if client is None:
        return False, 'AI is not configured on the server.'
    if len(brief) > 800:
        return False, 'Description is too long (max 800 characters).'

    user = (
        f'Business: "{site.site_name}" (type: {site.website_type})\n'
        f'Current brand/accent color: {site.accent_color}\n'
        f'The owner wants this look: "{brief.strip()}"\n\n'
        f'Write the site-wide CSS now. Remember: raw CSS only, no fences, no <style>.'
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.7,
            max_tokens=1600,
            messages=[
                {"role": "system", "content": THEME_SYSTEM},
                {"role": "user", "content": user},
            ],
            timeout=TIMEOUT,
        )
        css = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('AI theme generation failed')
        return False, f'AI is temporarily unavailable ({type(e).__name__}).'

    # Safisha: ondoa markdown fences na <style> kama AI imezidisha
    css = css.strip()
    if css.startswith('```'):
        # ondoa fence ya kwanza na ya mwisho
        lines = css.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        css = '\n'.join(lines).strip()
    css = css.replace('<style>', '').replace('</style>', '').strip()

    if not css or '{' not in css:
        return False, 'AI did not return valid CSS — please try again.'

    return True, css[:60000]
