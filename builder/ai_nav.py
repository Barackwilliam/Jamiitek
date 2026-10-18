"""
AI Navbar/Footer Generator — inatengeneza custom nav/footer HTML kutoka maneno.

Mteja anaandika 'nataka navbar ya kisasa yenye logo katikati na button ya
WhatsApp' → AI ina-generate HTML kamili + <style>, ikitumia placeholders za
mfumo ({{logo}}, {{nav_links}}, n.k.) ili links za pages zibaki dynamic.

Output ni HTML SAFI (bila markdown), tayari kuhifadhiwa kama custom_nav_html.
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


# Maelekezo haya ndiyo yanayoamua ubora. Yanaeleza kwa kina muundo wa kiwango
# cha kimataifa (nafasi, typography, hali za hover/active, menyu ya simu) kwa
# sababu model ikiachiwa "make it modern" inarudisha navbar ya kawaida sana.

DESIGN_PRINCIPLES = """DESIGN STANDARD — this must look like a navigation built by a top agency for a
brand worth billions (think Stripe, Linear, Apple, Airbnb), not a template:
- Generous spacing: 14-20px vertical padding on bars, 24-48px side padding
  (use clamp(16px,4vw,48px)), 4-8px gaps between links, links padded 8-14px.
- Typography: brand 18-22px weight 800 with letter-spacing:-.02em; links 14-15px
  weight 600; never more than two font weights besides the brand.
- Colour: var(--accent) is the brand colour — use it for ONE primary button and
  for active/hover indicators only. Text on light backgrounds #0f172a / muted
  rgba(15,23,42,.65); on dark backgrounds #f4f6fa / muted rgba(244,246,250,.7).
- Details that signal quality: 1px hairline borders (rgba 8-12%), soft layered
  shadows (0 10px 30px rgba(15,23,42,.08)), radius 10-14px on buttons,
  transitions of .2s on colour/background, :hover AND .on (active page) states,
  visible :focus-visible outlines, tap targets of at least 44px on phones.
- Use backdrop-filter blur ONLY on desktop (inside @media(min-width:901px)) —
  on phones it breaks position:fixed children.
- No emojis, no placeholder text, no lorem ipsum, no external fonts or images,
  no JavaScript except the onclick handlers described below."""

NAV_SYSTEM = """You are a senior product designer and front-end engineer. You design and code
the header / navigation of a small-business website. The owner describes what they
want; you return production-ready code.

OUTPUT FORMAT — follow exactly:
- Return ONLY raw HTML: one <header> (or <aside> for a sidebar) element, then ONE
  <style> block. No markdown fences, no comments outside the code, no explanation.

PLACEHOLDERS — the system fills these in; use them, never invent links or text:
  {{logo}}        the logo <img> (may be empty — design must still look right)
  {{site_name}}   the business name
  {{nav_links}}   ALL page links as plain <a> tags; the current page has class="on"
  {{whatsapp}}    a wa.me URL for a WhatsApp button (use as href)
  {{phone}}       phone number text
  {{cta}}         a ready-made contact button (<a class="hx-cta">) — or build your
                  own button with href="{{whatsapp}}"

REQUIRED STRUCTURE (the site's JavaScript depends on it):
  <header class="PREFIX">
    <a class="PREFIX-brand" href="/">{{logo}}<span>{{site_name}}</span></a>
    <button class="PREFIX-burger" type="button" onclick="jtMenu(true)" aria-label="Open menu" aria-controls="jt-links"><span></span></button>
    <nav id="jt-links" class="PREFIX-menu" aria-label="Main menu">
      <div class="PREFIX-mhead">(brand again) <button type="button" onclick="jtMenu(false)" aria-label="Close menu"></button></div>
      <div class="PREFIX-links">{{nav_links}}</div>
      (optional contact button)
    </nav>
    <div class="PREFIX-scrim" onclick="jtMenu(false)"></div>
  </header>
- Pick one short unique PREFIX (e.g. "nx7") and prefix EVERY class and selector.
- jtMenu(true) adds class "open" to #jt-links and class "jt-menu-open" to <html>.

DESKTOP (min-width:901px): sticky top bar (position:sticky;top:0;z-index:60) or a
fixed left sidebar (then add `.jt-body{margin-left:<sidebar width>}` inside the same
media query). Hide the burger, the mhead and the scrim. Links sit in a row (or a
column for a sidebar) with a clear hover and .on state (pill background, underline
bar or accent side-marker).

PHONES (max-width:900px) — this is where most customers are, make it excellent:
- Show the burger (44x44, hairline border, three lines drawn with CSS).
- #jt-links becomes a PANEL: position:fixed; z-index:90; with a solid background,
  hidden by default with transform (e.g. translateX(104%)) + visibility:hidden, and
  shown when it has class "open" (transform:none; visibility:visible). Animate with
  transition:transform .5s cubic-bezier(.32,.72,0,1). Choose the panel type the owner
  asked for; if they did not say, use a drawer from the right, width min(88vw,380px),
  full height, rounded inner corners 24px, big shadow.
  Other good panel types: left drawer (for sidebars), bottom sheet (rounded top,
  small grab handle), full screen with very large links.
- Inside the panel: the mhead row (brand + round close button drawn with two
  rotated bars), then the links stacked full-width: 16-18px, weight 600, 14-16px
  padding, 14px radius, a subtle chevron on the right, accent-tinted background on
  .on; then the contact button full-width at the bottom.
- The scrim: position:fixed; inset:0; z-index:85; rgba(5,8,15,.55); fades in when
  html.jt-menu-open is set. Also add `html.jt-menu-open,html.jt-menu-open body{overflow:hidden}`.
- Never use backdrop-filter on the header at this width.

""" + DESIGN_PRINCIPLES + """

Keep the CSS focused: roughly 60-120 lines. The result must look intentional and
premium on both a 1440px desktop and a 390px phone."""


FOOTER_SYSTEM = """You are a senior product designer and front-end engineer. You design and code
the footer of a small-business website. The owner describes what they want; you
return production-ready code.

OUTPUT FORMAT — follow exactly:
- Return ONLY raw HTML: one <footer> element, then ONE <style> block. No markdown
  fences, no explanation.

PLACEHOLDERS — the system fills these in; use them, never invent contact details:
  {{logo}} {{site_name}} {{tagline}} {{year}}
  {{nav_links}}     all page links as plain <a> tags
  {{contact_list}}  a <ul> of the contacts that exist (phone, WhatsApp, email, address)
  {{contact_icons}} round icon buttons for phone / WhatsApp / email
  {{cta_footer}}    a ready-made primary button (<a class="fx-cta">Contact us</a>)
  {{whatsapp}}      a wa.me URL      {{phone}} {{email}} {{address}}  plain text
  {{to_top}}        a "Back to top" link
Any placeholder may be empty for a business that has no such detail — the layout
must still look complete. The ready-made pieces ({{contact_list}}, {{contact_icons}},
{{cta_footer}}, {{to_top}}) arrive already styled; restyle them through your prefix
if needed (e.g. .PREFIX .fx-cta{...}).

DO NOT add any "Built with", "Powered by" or "Developed by" credit — the platform
adds its own credit below every footer automatically.

LAYOUT STANDARD — footers must feel substantial, not an afterthought:
- 88-120px top padding, 28-32px bottom bar, content max-width 1200px centred with
  side padding clamp(20px,4vw,48px).
- A clear hierarchy: brand block (logo, name, one line about the business, icons),
  then columns (Pages, Contact, and usually a call-to-action card or band), then a
  bottom bar with "© {{year}} {{site_name}}. All rights reserved." and {{to_top}},
  separated by a 1px hairline.
- Column headings: 12px uppercase, letter-spacing .16em, weight 700.
- Links: 15px, 12px apart, subtle hover (colour change + 3px slide).
- Grid: 3-4 columns on desktop, 2 on tablets (max-width:1000px), 1 on phones
  (max-width:600px) with 36-40px gaps. Nothing may overflow at 360px wide.

""" + DESIGN_PRINCIPLES + """

Keep the CSS focused: roughly 50-110 lines. Use a unique short class prefix for
every selector."""


def _generate(system, site, brief, extra_ctx=''):
    client = _client()
    if client is None:
        return False, 'AI is not configured on the server.'
    if len(brief) > 800:
        return False, 'Description is too long (max 800 characters).'

    user = (
        f'Business: "{site.site_name}" (type: {site.website_type})\n'
        f'Brand/accent color: {site.accent_color}\n'
        f'{extra_ctx}'
        f'The owner wants: "{brief.strip()}"\n\n'
        f'Build it now: raw HTML + one <style> block only, use the placeholders, '
        f'and make it look premium on desktop AND on a 390px phone.'
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.6, max_tokens=3500,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            timeout=TIMEOUT,
        )
        html = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception('AI nav/footer generation failed')
        return False, f'AI is temporarily unavailable ({type(e).__name__}).'

    # Safisha fences
    if html.startswith('```'):
        lines = html.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        html = '\n'.join(lines).strip()

    if not html or '<' not in html:
        return False, 'AI did not return valid HTML — please try again.'
    return True, html[:40000]


def generate_navbar(site, brief):
    """Rudisha (ok, html_or_error)."""
    return _generate(NAV_SYSTEM, site, brief,
                     extra_ctx='This is for the site NAVBAR.\n')


def generate_footer(site, brief):
    """Rudisha (ok, html_or_error)."""
    return _generate(FOOTER_SYSTEM, site, brief,
                     extra_ctx='This is for the site FOOTER.\n')
