"""
Company profile mpya (brochure ya kurasa 12).

Muundo na maandishi makuu yako kwenye template `docs/profile_brochure.html`.
Hapa ndipo data zinazobadilika zinaandaliwa: timu, vifurushi vya bei, bei za
domain, mawasiliano na QR code. Timu na vifurushi vinahaririwa kwenye admin
(CompanyProfile → Brochure); vikiwa tupu, vilivyo hapa chini vinatumika.
"""
import base64
import io
import re
from functools import lru_cache

from django.templatetags.static import static

from .domain_checker import TLD_PRICES

# Picha zisizo na http zinasomwa kama static (apps/static/...).
DEFAULT_TEAM = [
    {'name': 'William Eliya Chipindi', 'role': 'Founder, CEO & Lead Developer',
     'skill': 'Leadership', 'photo': 'profile/team1.jpg', 'position': '58% 20%'},
    {'name': 'Debora Osward', 'role': 'Designer',
     'skill': 'Design', 'photo': 'profile/team2.jpg', 'position': '62% 22%'},
    {'name': 'Beatha Matembo', 'role': 'Developer',
     'skill': 'Development', 'photo': 'profile/team3.jpg', 'position': '58% 18%'},
    {'name': 'Grace William', 'role': 'Customer Support',
     'skill': 'Support', 'photo': 'profile/team4.jpg', 'position': '50% 4%'},
]

TEMPLATE_HOSTING_PER_MONTH = 15000

DEFAULT_PACKAGES = [
    {'name': 'Template website', 'headline': 'Ready design, live fast', 'price': 180000,
     'note': f'one-time + hosting TZS {TEMPLATE_HOSTING_PER_MONTH:,}/mo',
     'features': ['Professional ready-made design', 'Your name, photos and prices',
                  'Upgrade to custom any time']},
    {'name': 'Custom website', 'headline': 'Designed for your brand', 'price': 350000,
     'note': 'one-time payment', 'badge': 'Most chosen',
     'features': ['Unique design, mobile-first', 'English & Kiswahili, SEO-ready',
                  'Dashboard to update content']},
    {'name': 'Custom system', 'headline': 'Built around your work', 'price': 500000,
     'note': 'one-time · 2–6 weeks',
     'features': ['School, loan, stock or booking', 'Dashboards and reports',
                  'Invoices & mobile money']},
    {'name': 'Mobile app', 'headline': 'Android & iOS', 'price': 650000,
     'note': 'one-time payment', 'dark': True,
     'features': ['One app for both stores', 'Connected to your system', 'Push notifications']},
]

# Toleo la Kiswahili la vifurushi (kwa mpangilio uleule wa DEFAULT_PACKAGES)
DEFAULT_PACKAGES_SW = [
    {'name': 'Website ya template', 'headline': 'Muundo tayari, hewani haraka',
     'note': f'mara moja + hosting TZS {TEMPLATE_HOSTING_PER_MONTH:,}/mwezi',
     'features': ['Muundo wa kitaalamu ulio tayari', 'Jina lako, picha na bei zako',
                  'Unaweza kupanda kwenda custom wakati wowote']},
    {'name': 'Website kamili', 'headline': 'Imebuniwa kwa ajili ya brand yako',
     'note': 'malipo ya mara moja', 'badge': 'Inayochaguliwa zaidi',
     'features': ['Muundo wa kipekee, unaofaa simu', 'Kiswahili & Kiingereza, tayari kwa SEO',
                  'Dashboard ya kubadilisha maudhui']},
    {'name': 'Mfumo maalum', 'headline': 'Unajengwa kufuata kazi yako',
     'note': 'mara moja · wiki 2–6',
     'features': ['Shule, mikopo, stoo au booking', 'Dashboards na ripoti',
                  'Ankara & malipo ya simu']},
    {'name': 'App ya simu', 'headline': 'Android & iOS',
     'note': 'malipo ya mara moja',
     'features': ['App moja kwa maduka yote mawili', 'Imeunganishwa na mfumo wako', 'Arifa (notifications)']},
]

TEAM_SW = {
    'Founder, CEO & Lead Developer': 'Mwanzilishi, CEO & Mtengenezaji Mkuu',
    'Designer': 'Mbunifu', 'Developer': 'Mtengenezaji wa mifumo', 'Customer Support': 'Huduma kwa wateja',
    'Leadership': 'Uongozi', 'Design': 'Ubunifu', 'Development': 'Utengenezaji', 'Support': 'Msaada',
}

# Maandishi ya ukurasa (toolbar, kitufe, meta) kwa kila lugha
UI = {
    'en': {'doc': 'Company Profile', 'pages': '12 pages', 'dl': 'Download PDF', 'busy': 'Downloading…',
           'done': 'Downloaded ✓', 'switch': 'Kiswahili', 'switch_url': '?lang=sw',
           'desc': 'Websites, management systems, mobile apps and WhatsApp automation — designed and built in Dar es Salaam, Tanzania.'},
    'sw': {'doc': 'Wasifu wa Kampuni', 'pages': 'kurasa 12', 'dl': 'Pakua PDF', 'busy': 'Inapakua…',
           'done': 'Imepakuliwa ✓', 'switch': 'English', 'switch_url': '?lang=en',
           'desc': 'Websites, mifumo ya usimamizi, apps za simu na huduma za WhatsApp — zimebuniwa na kutengenezwa Dar es Salaam, Tanzania.'},
}

# Mistari ya jedwali la domain: (maandishi, tld inayotoa bei)
DOMAIN_ROWS = [
    ('.co.tz', '.co.tz'), ('.tz', '.tz'), ('.com', '.com'), ('.org · .net', '.org'),
    ('.or.tz · .ac.tz', '.or.tz'), ('.africa', '.africa'),
]

# Rangi za kadi za timu, kwa mzunguko
TEAM_COLORS = [
    ('linear-gradient(160deg,#4C74FF,#1B3FD1)', 'var(--or)'),
    ('linear-gradient(160deg,#FF9A5C,#FF5A1F)', 'var(--b)'),
    ('linear-gradient(160deg,#1E2C5E,#0B1530)', 'var(--or)'),
    ('linear-gradient(160deg,#4C74FF,#14214A)', 'var(--or)'),
]


def _asset_url(path):
    path = (path or '').strip()
    if not path:
        return ''
    return path if path.startswith(('http://', 'https://', '/')) else static(path)


def phone_display(raw):
    """'255750910158' / '+255 750 910 158' / '0750910158' → '+255 750 910 158'."""
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('0') and len(digits) == 10:
        digits = '255' + digits[1:]
    if len(digits) == 12 and digits.startswith('255'):
        return f'+{digits[:3]} {digits[3:6]} {digits[6:9]} {digits[9:]}'
    return (raw or '').strip()


def wa_number(raw):
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('0') and len(digits) == 10:
        digits = '255' + digits[1:]
    return digits


@lru_cache(maxsize=16)
def qr_data_uri(text):
    """QR kama PNG ya base64 — inabadilika yenyewe namba au website ikibadilika."""
    import qrcode
    qr = qrcode.QRCode(border=0, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make()
    buf = io.BytesIO()
    qr.make_image(fill_color='#0B1530', back_color='white').save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def _sw(d, key):
    """Thamani ya Kiswahili (key_sw) ikiwepo, la sivyo ya Kiingereza."""
    return d.get(f'{key}_sw') or d.get(key)


def _team(profile, lang='en'):
    rows = [m for m in (profile.team or []) if isinstance(m, dict) and m.get('name')] or DEFAULT_TEAM
    out = []
    for i, m in enumerate(rows):
        bg, accent = TEAM_COLORS[i % len(TEAM_COLORS)]
        m = {**m, 'bg': bg, 'accent': accent, 'photo_url': _asset_url(m.get('photo'))}
        if lang == 'sw':
            for k in ('role', 'skill'):
                m[k] = m.get(f'{k}_sw') or TEAM_SW.get(m.get(k), m.get(k))
        out.append(m)
    return out


def _packages(profile, lang='en'):
    custom = [p for p in (profile.packages or []) if isinstance(p, dict) and p.get('name')]
    rows = custom or DEFAULT_PACKAGES
    if lang == 'sw':
        if custom:
            rows = [{**p, **{k: _sw(p, k) for k in ('name', 'headline', 'note', 'badge', 'features')}} for p in custom]
        else:
            rows = [{**p, **sw} for p, sw in zip(DEFAULT_PACKAGES, DEFAULT_PACKAGES_SW)]
    out = []
    for p in rows:
        try:
            price = f"{int(p.get('price') or 0):,}"
        except (TypeError, ValueError):
            price = str(p.get('price') or '')
        style = 'on' if p.get('badge') else ('dk' if p.get('dark') else '')
        out.append({**p, 'price_display': price, 'style': style,
                    'features': list(p.get('features') or [])})
    return out


def _domains():
    return [{'label': label, 'price_display': f'{TLD_PRICES[tld]:,}'}
            for label, tld in DOMAIN_ROWS if tld in TLD_PRICES]


def brochure_context(profile, lang='en'):
    import json
    lang = 'sw' if lang == 'sw' else 'en'
    period = (profile.period or '2025 — 2026').replace(' — ', '–').replace(' - ', '–')
    website = (profile.website or 'www.jamiitek.com').strip()
    site_url = website if website.startswith('http') else f'https://{website}'
    wa = wa_number(profile.phone)
    return {
        'profile': profile,
        'period': period,
        'period_long': period.replace('–', ' — '),
        'phone_display': phone_display(profile.phone) or profile.phone,
        'lang': lang,
        'ui': UI[lang],
        'ui_js': json.dumps({k: UI[lang][k] for k in ('dl', 'busy', 'done')}),
        'pages_template': f'docs/brochure_pages_{lang}.html',
        'team': _team(profile, lang),
        'packages': _packages(profile, lang),
        'domains': _domains(),
        'template_hosting': f'{TEMPLATE_HOSTING_PER_MONTH:,}',
        'qr_whatsapp': qr_data_uri(f'https://wa.me/{wa}') if wa else '',
        'qr_website': qr_data_uri(site_url),
    }
