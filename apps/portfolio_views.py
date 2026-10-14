"""
Portfolio — orodha ya websites zote tulizotengeneza (/portfolio/).

Kadi za homepage zinafungua ukurasa huu. Hapa kila kadi inaeleza tovuti kwa
ufupi, na mgeni anaamua mwenyewe kubonyeza "Visit site". Structured data inaorodhesha
kila tovuti kama `WebSite` yenye `creator` = JamiiTek, na tovuti za wateja
(credit ya "Designed by JamiiTek") zinarudi hapa.
"""
from django.shortcuts import render

from .public_cache import get_or_build
from .seo.schema import SITE_NAME, SITE_URL, breadcrumb_schema, organization_schema, render_schemas
from .site_content import PortfolioItem


def portfolio_list(request):
    items = get_or_build('portfolio_list', lambda: list(PortfolioItem.objects.filter(is_featured=True)))
    sites = []
    for p in items:
        entry = {'@type': 'WebSite', 'name': p.client or p.title, 'creator': {'@id': f'{SITE_URL}/#organization'}}
        if p.live_url:
            entry['url'] = p.live_url
        sites.append(entry)
    page = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        '@id': f'{SITE_URL}/portfolio/#webpage',
        'url': f'{SITE_URL}/portfolio/',
        'name': f'Portfolio — websites built by {SITE_NAME}',
        'isPartOf': {'@id': f'{SITE_URL}/#website'},
        'about': {'@id': f'{SITE_URL}/#organization'},
        'mainEntity': {
            '@type': 'ItemList',
            'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': s} for i, s in enumerate(sites)],
        },
    }
    return render(request, 'site/portfolio_list.html', {
        'items': items,
        'page_title': 'Portfolio — Websites We Built in Tanzania | JamiiTek',
        'page_desc': 'Websites and systems built by JamiiTek for businesses and organisations in Tanzania.',
        'canonical': f'{SITE_URL}/portfolio/',
        'schema_markup': render_schemas(
            organization_schema(), page,
            breadcrumb_schema([('Home', '/'), ('Portfolio', '/portfolio/')]),
        ),
    })
