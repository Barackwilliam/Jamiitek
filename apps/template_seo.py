"""
SEO ya Templates Marketplace — ili kila template ipatikane Google na kwenye
majibu ya AI (ChatGPT, Gemini, Perplexity, Copilot).

TATIZO

Kila template ilikuwa na ukurasa mmoja tu: /templates/preview/<namba>/ —
fremu tupu yenye iframe. Google haisomi maudhui ya iframe kama sehemu ya
ukurasa, hakukuwa na maneno, kichwa cha kipekee, structured data, wala
sitemap. Kwa Google template hizi hazikuwepo.

SULUHISHO

  - /templates/<slug>/ — ukurasa kamili wa kila template: kichwa na maelezo
    ya kipekee, maandishi halisi (vipengele, bei, hatua, FAQ, maelezo kwa
    Kiingereza na Kiswahili), templates zinazohusiana, na JSON-LD
    (Product + Offers, BreadcrumbList, FAQPage).
  - /templates/c/<jamii>/ — kurasa za jamii ("Restaurant website templates").
  - sitemap.xml, IndexNow (Bing/ChatGPT search) kila template ikihifadhiwa,
    na /llms.txt kwa AI.

Hakuna "rating/reviews" kwenye JSON-LD: bila maoni halisi ya wateja Google
inaiona kama udanganyifu (self-serving review markup).
"""
import re

from django.utils.text import slugify

BASE_URL = 'https://www.jamiitek.com'

# Maneno ya utafutaji na vipengele kwa kila jamii. Funguo = WebsiteTemplate.category
CATEGORY_SEO = {
    'restaurant': {'noun': 'restaurant', 'sw': 'mgahawa / hoteli ya chakula',
                   'who': 'restaurants, cafés, fast-food and catering businesses',
                   'features': ['Menu with photos and prices', 'Order & reserve on WhatsApp', 'Opening hours and location map']},
    'salon': {'noun': 'salon & beauty', 'sw': 'saluni na urembo',
              'who': 'hair salons, barbershops, spas and beauty studios',
              'features': ['Services & price list', 'Book an appointment on WhatsApp', 'Before-and-after gallery']},
    'hotel': {'noun': 'hotel & lodge', 'sw': 'hoteli, lodge na nyumba za wageni',
              'who': 'hotels, lodges, guest houses and Airbnb hosts',
              'features': ['Rooms with photos and rates', 'Booking inquiries straight to you', 'Amenities and location map']},
    'shop': {'noun': 'online shop', 'sw': 'duka la mtandaoni',
             'who': 'shops, boutiques and online sellers',
             'features': ['Product catalogue with prices', 'Order on WhatsApp with one tap', 'Categories and featured products']},
    'clinic': {'noun': 'clinic & healthcare', 'sw': 'kliniki na huduma za afya',
               'who': 'clinics, pharmacies, dentists and health practitioners',
               'features': ['Services and doctors', 'Appointment requests', 'Opening hours and emergency contacts']},
    'church': {'noun': 'church & ministry', 'sw': 'kanisa na huduma za dini',
               'who': 'churches, mosques, ministries and faith organisations',
               'features': ['Service times and events', 'Sermons, news and ministries', 'Giving and contact details']},
    'school': {'noun': 'school & education', 'sw': 'shule na elimu',
               'who': 'schools, colleges, academies and tuition centres',
               'features': ['Programmes and admissions', 'News, events and gallery', 'Fees and contact information']},
    'portfolio': {'noun': 'portfolio', 'sw': 'portfolio ya kazi binafsi',
                  'who': 'freelancers, photographers, designers and creatives',
                  'features': ['Project gallery', 'About and services', 'Hire-me contact section']},
    'tourism': {'noun': 'safari & travel', 'sw': 'utalii na safari',
                'who': 'tour operators, safari companies and travel agents',
                'features': ['Tour packages with itineraries and prices', 'Booking inquiries on WhatsApp', 'Destinations gallery']},
    'real estate': {'noun': 'real estate', 'sw': 'nyumba na viwanja (real estate)',
                    'who': 'real-estate agents, property managers and developers',
                    'features': ['Property listings with photos', 'Viewing requests', 'Location and price details']},
    'technology': {'noun': 'technology & startup', 'sw': 'teknolojia na startup',
                   'who': 'tech startups, IT companies and software agencies',
                   'features': ['Product and features sections', 'Pricing plans', 'Demo and contact forms']},
    'admin': {'noun': 'admin dashboard', 'sw': 'dashboard ya usimamizi',
              'who': 'businesses that need an admin or management dashboard',
              'features': ['Clean data tables and cards', 'Charts and statistics layout', 'Responsive navigation']},
    'booking': {'noun': 'booking', 'sw': 'mfumo wa booking',
                'who': 'businesses that take bookings and appointments',
                'features': ['Booking and inquiry flow', 'Services and availability', 'Confirmation on WhatsApp']},
    'landing': {'noun': 'landing page', 'sw': 'landing page ya kuuza',
                'who': 'product launches, campaigns and single-offer businesses',
                'features': ['Conversion-focused hero', 'Benefits and social proof', 'Clear call-to-action buttons']},
    'niche': {'noun': 'premium niche', 'sw': 'biashara maalum',
              'who': 'businesses that want a distinctive premium look',
              'features': ['Premium, unique design', 'Story-driven sections', 'Strong calls to action']},
    'media': {'noun': 'media & news', 'sw': 'habari na media',
              'who': 'news sites, blogs, magazines and media houses',
              'features': ['Articles and categories layout', 'Featured stories', 'Newsletter and social links']},
}
DEFAULT_SEO = {'noun': 'business', 'sw': 'biashara', 'who': 'small and growing businesses',
               'features': ['Services or products section', 'About and contact sections', 'WhatsApp and call buttons']}

# Vipengele vya kila template (vinavyotolewa na JamiiTek Builder na hosting)
COMMON_FEATURES = [
    ('📱', 'Mobile-perfect', 'Looks great on phones, tablets and laptops — most of your customers are on mobile.'),
    ('✨', 'Customize free in the Builder', 'Change every text, photo and color with drag & drop, code or AI — no coding needed.'),
    ('🌍', 'Free yourname.jamiitek.com address', 'Publish in minutes, then connect your own domain (.co.tz, .com) any time.'),
    ('💬', 'WhatsApp & inquiries built in', 'Customers message you on WhatsApp or send inquiries straight to your dashboard.'),
    ('🔎', 'SEO-ready', 'Clean code, fast loading and proper page titles so customers find you on Google.'),
    ('⚡', 'Fast & secure', 'Hosted on a fast CDN with free SSL (https) and daily reliability.'),
]


def cat_key(tpl_or_key):
    key = tpl_or_key if isinstance(tpl_or_key, str) else (tpl_or_key.category or '')
    return key.strip().lower()


def cat_info(tpl_or_key):
    return CATEGORY_SEO.get(cat_key(tpl_or_key), DEFAULT_SEO)


def cat_slug(key):
    return slugify(key) or 'other'


def plain(text, limit=None):
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(text or ''))).strip()
    if limit and len(text) > limit:
        text = text[:limit - 1].rsplit(' ', 1)[0].rstrip(',.;:') + '…'
    return text


def title(tpl):
    """≤ ~60 herufi: jina + aina + neno la eneo."""
    if tpl.seo_title:
        return tpl.seo_title
    noun = cat_info(tpl)['noun'].title()
    t = f'{tpl.name} — {noun} Website Template'
    return t if len(t) <= 52 else f'{tpl.name} — {noun} Template'


def description(tpl):
    if tpl.seo_description:
        return tpl.seo_description
    info = cat_info(tpl)
    return plain(f'{tpl.name}: a premium {info["noun"]} website template for {info["who"]} in Tanzania & East Africa. '
                 f'Customize it free in the JamiiTek Builder or let us set it up.', 158)


def keywords(tpl):
    info = cat_info(tpl)
    n = info['noun']
    return ', '.join([
        f'{n} website template', f'{n} website Tanzania', f'{tpl.name} template',
        f'website ya {info["sw"]}', f'template ya website ya {info["sw"]}',
        'website template Tanzania', 'website builder Tanzania', 'JamiiTek templates',
    ])


def features(tpl):
    return cat_info(tpl)['features']


def article(tpl):
    """Maandishi ya ukurasa (aya) — admin akiandika long_description, hayo kwanza."""
    info = cat_info(tpl)
    paras = [p.strip() for p in (tpl.long_description or '').split('\n\n') if p.strip()]
    paras += [
        f'{tpl.name} is a {info["noun"]} website template designed for {info["who"]}. '
        f'{plain(tpl.description)} It is built mobile-first, loads fast on 3G and 4G, and puts the '
        f'most important action — contacting you — one tap away.',
        f'Open it in the free JamiiTek Website Builder to make it yours: change the text, photos and colors, '
        f'add pages, connect WhatsApp and publish on your own address in minutes. Prefer not to do it yourself? '
        f'The JamiiTek team can build it for you.',
        f'Kwa Kiswahili: {tpl.name} ni template ya website ya {info["sw"]}. Unaweza kuibadilisha bure kwenye '
        f'JamiiTek Builder — maandishi, picha na rangi — na kuiweka hewani kwa jina lako, au ukatuachia sisi tukutengenezee.',
    ]
    return paras


def faq(tpl):
    info = cat_info(tpl)
    return [
        (f'Can I customize the {tpl.name} template myself?',
         f'Yes. Click “Customize in Builder”, create a free account and the {tpl.name} design opens in the JamiiTek '
         f'Website Builder. You can change every text, image and color with drag & drop, code or AI, then publish.'),
        ('How much does it cost?',
         (f'{tpl.name} costs TSh {tpl.price:,}, paid one time. You can try it free in the Builder first. '
          f'The price includes 1 year of hosting, connecting your own domain and no JamiiTek logo on your website.')
         if tpl.for_sale else
         (f'{tpl.name} is free. Build your website and put it online free on yourname.jamiitek.com. '
          f'Free websites show "Developed by JamiiTek" at the bottom.')),
        ('Does it work on mobile phones?',
         f'Yes. Every JamiiTek template, including {tpl.name}, is mobile-first and tested on phones, tablets and laptops.'),
        ('Can I use my own domain name?',
         'Yes. Publish free on yourname.jamiitek.com, then connect your own domain such as .co.tz or .com.'),
        (f'Is this template good for {info["noun"]} businesses in Tanzania?',
         f'It was made for {info["who"]} — with WhatsApp buttons, inquiry forms and prices in TSh, the way customers '
         f'in Tanzania and East Africa like to buy.'),
        ('What if I cannot find the design I want?',
         'Send us a short proposal describing your business and the look you want — the JamiiTek team designs it for you.'),
    ]


def _offer(name, price, url):
    return {'@type': 'Offer', 'name': name, 'price': str(price), 'priceCurrency': 'TZS',
            'availability': 'https://schema.org/InStock', 'url': url}


def json_ld(tpl):
    url = BASE_URL + tpl.get_absolute_url()
    cat = tpl.category_plain()
    product = {
        '@context': 'https://schema.org', '@type': 'Product',
        'name': f'{tpl.name} — {cat_info(tpl)["noun"].title()} Website Template',
        'description': description(tpl), 'url': url, 'sku': f'JT-TPL-{tpl.pk}',
        'category': f'Website templates > {cat}',
        'brand': {'@type': 'Brand', 'name': 'JamiiTek'},
        'image': f'{BASE_URL}/static/images/og-image.jpg',
        'offers': [_offer(f'{tpl.name} website template', tpl.price if tpl.for_sale else 0, url)],
    }
    crumbs = {
        '@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Home', 'item': BASE_URL + '/'},
            {'@type': 'ListItem', 'position': 2, 'name': 'Website Templates', 'item': BASE_URL + '/templates/'},
            {'@type': 'ListItem', 'position': 3, 'name': cat, 'item': f'{BASE_URL}/templates/c/{cat_slug(cat_key(tpl))}/'},
            {'@type': 'ListItem', 'position': 4, 'name': tpl.name, 'item': url},
        ]}
    faq_ld = {
        '@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': [
            {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faq(tpl)
        ]}
    return [product, crumbs, faq_ld]


def item_list_ld(templates, name, url):
    return {
        '@context': 'https://schema.org', '@type': 'ItemList', 'name': name, 'url': url,
        'numberOfItems': len(templates),
        'itemListElement': [
            {'@type': 'ListItem', 'position': i + 1, 'url': BASE_URL + t.get_absolute_url(), 'name': t.name}
            for i, t in enumerate(templates)
        ],
    }


# ── Anatomia ya template (ukurasa wa template: "Inside this template") ──────
# Inasomwa kutoka preview_html yenyewe — sehemu, rangi na fonti halisi za demo,
# kwa hiyo kila ukurasa unaonyesha kilichopo kweli, si maneno ya jumla.

_GENERIC_FONTS = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'inherit', 'initial',
                  'arial', 'helvetica', 'helvetica neue', 'times new roman', 'georgia', 'segoe ui', 'roboto mono',
                  '-apple-system', 'blinkmacsystemfont', 'ui-sans-serif', 'ui-serif', 'ui-monospace', 'var'}


def _text(fragment):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment or '')).strip()


def _sections(html):
    """[(namba, jina)] — namba ni nafasi ya <section> kwenye ukurasa (JS inaitumia kusogeza demo)."""
    out = []
    parts = re.split(r'(?i)<section\b', html)[1:]
    for i, part in enumerate(parts):
        head = re.search(r'(?is)<h[1-3][^>]*>(.*?)</h[1-3]>', part)
        label = _text(head.group(1)) if head else ''
        if not label:
            sid = re.match(r'(?is)[^>]*\bid=["\']([^"\']+)', part)
            label = sid.group(1).replace('-', ' ').replace('_', ' ').title() if sid else ''
        if label:
            out.append((i, label[:48]))
    return out


def _palette(html, limit=6):
    """Rangi zinazotumika zaidi kwenye CSS ya demo (hex), bila marudio."""
    counts = {}
    for raw in re.findall(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', ' '.join(re.findall(r'(?is)<style[^>]*>(.*?)</style>', html))
                          + ' ' + ' '.join(re.findall(r'(?i)style="([^"]*)"', html))):
        h = raw.lower() if len(raw) == 6 else ''.join(c * 2 for c in raw.lower())
        counts[h] = counts.get(h, 0) + 1
    return ['#' + h for h, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


def _google_fonts(html):
    names = []
    for fam in re.findall(r'(?i)fonts\.googleapis\.com/css2?\?[^"\'>]*', html):
        names += [f.split(':')[0].replace('+', ' ').strip() for f in re.findall(r'family=([^&"\']+)', fam)]
    return [n for i, n in enumerate(names) if re.fullmatch(r'[A-Za-z0-9 ]{2,40}', n) and n not in names[:i]]


def _fonts(html, limit=3):
    names = _google_fonts(html)
    for decl in re.findall(r'(?i)font-family\s*:\s*((?:"[^"<>]*"|\'[^\'<>]*\'|[^;}"\'<>])+)', html):
        names += [n.strip().strip('\'"') for n in decl.split(',')]
    out = []
    for n in names:
        n = n.strip()
        if re.fullmatch(r'[A-Za-z0-9 ]{2,40}', n) and n.lower() not in _GENERIC_FONTS and n not in out:
            out.append(n)
    return out[:limit]


def anatomy(tpl):
    """Sehemu, rangi, fonti na idadi ya vitu vya demo — inahifadhiwa kwenye RAM hadi template ibadilike.

    Si cache ya 'default': bila Redis hiyo ni DatabaseCache (safari ya Supabase),
    na preview_html haisomwi kabisa kama anatomia ipo tayari (view inaiahirisha).
    """
    from .public_cache import get_or_build

    # public_cache: toleo linapanda template yoyote ikihifadhiwa, kwa hiyo anatomia mpya mara moja
    stamp = int(tpl.updated_at.timestamp()) if tpl.updated_at else 0
    return get_or_build(f'tpl-anatomy:{tpl.pk}:{stamp}', lambda: _build_anatomy(tpl.preview_html or ''), ttl=60 * 60 * 24)


def _build_anatomy(html):
    sections = _sections(html)
    data = {
        'sections': sections,
        'section_count': len(re.findall(r'(?i)<section\b', html)),
        'images': len(re.findall(r'(?i)<img\b', html)) + len(re.findall(r'(?i)background(?:-image)?\s*:[^;]*url\(', html)),
        'palette': _palette(html),
        'fonts': _fonts(html),
        'breakpoints': len(set(re.findall(r'(?i)@media[^{]*?(\d{3,4})px', html))),
        'animated': bool(re.search(r'(?i)@keyframes|IntersectionObserver|transition\s*:', html)),
    }
    # Fonti za Google za demo zinapakiwa pia kwenye ukurasa ili sampuli "Aa" ionekane kwa fonti halisi
    google = [f for f in data['fonts'] if f in _google_fonts(html)]
    data['font_url'] = ('https://fonts.googleapis.com/css2?' + '&'.join(
        'family=' + f.replace(' ', '+') for f in google) + '&display=swap') if google else ''
    return data
