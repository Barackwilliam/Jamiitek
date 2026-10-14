"""
Portfolio — kazi halisi za JamiiTek, kila moja na ukurasa wake (case study).

Kila ukurasa wa kazi unaelekeza kwenye tovuti ya mteja, na tovuti ya mteja
(credit ya "Designed by JamiiTek") inarudi hapa. Kwa Google, viungo vya pande
mbili kati ya kurasa halisi ndivyo vinavyoonyesha kwamba kazi ni ya kweli.
"""
from django.shortcuts import get_object_or_404, render

from .public_cache import get_or_build
from .seo.schema import SITE_NAME, SITE_URL, breadcrumb_schema, organization_schema, render_schemas
from .site_content import PortfolioItem


def _visible():
    return PortfolioItem.objects.filter(is_featured=True).exclude(slug__isnull=True).exclude(slug='')


def portfolio_list(request):
    items = get_or_build('portfolio_list', lambda: list(_visible()))
    item_list = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        '@id': f'{SITE_URL}/portfolio/#webpage',
        'url': f'{SITE_URL}/portfolio/',
        'name': f'Portfolio — websites and systems built by {SITE_NAME}',
        'isPartOf': {'@id': f'{SITE_URL}/#website'},
        'about': {'@id': f'{SITE_URL}/#organization'},
        'mainEntity': {
            '@type': 'ItemList',
            'itemListElement': [
                {'@type': 'ListItem', 'position': i + 1, 'url': f'{SITE_URL}{p.get_absolute_url()}', 'name': p.title}
                for i, p in enumerate(items)
            ],
        },
    }
    return render(request, 'site/portfolio_list.html', {
        'items': items,
        'page_title': 'Portfolio — Websites & Systems We Built in Tanzania | JamiiTek',
        'page_desc': 'Real websites, dashboards and systems built by JamiiTek for businesses and organisations in '
                     'Tanzania — every project is live and serving customers.',
        'canonical': f'{SITE_URL}/portfolio/',
        'schema_markup': render_schemas(
            organization_schema(), item_list,
            breadcrumb_schema([('Home', '/'), ('Portfolio', '/portfolio/')]),
        ),
    })


def portfolio_detail(request, slug):
    item = get_object_or_404(_visible(), slug=slug)
    url = f'{SITE_URL}{item.get_absolute_url()}'
    project = {
        '@context': 'https://schema.org',
        '@type': 'CreativeWork',
        '@id': f'{url}#project',
        'name': item.title,
        'url': url,
        'description': item.summary or item.title,
        'creator': {'@id': f'{SITE_URL}/#organization'},
        'publisher': {'@id': f'{SITE_URL}/#organization'},
        'inLanguage': 'en',
    }
    if item.image:
        project['image'] = item.image
    if item.year[:4].isdigit():
        project['dateCreated'] = item.year[:4]
    if item.technologies_list:
        project['keywords'] = ', '.join(item.services_list + item.technologies_list)
    if item.client or item.live_url:
        client = {'@type': 'Organization', 'name': item.client or item.title}
        if item.live_url:
            client['url'] = item.live_url
        project['about'] = client
        if item.live_url:
            # The live site itself, made by JamiiTek.
            project['workExample'] = {
                '@type': 'WebSite', 'name': item.client or item.title, 'url': item.live_url,
                'creator': {'@id': f'{SITE_URL}/#organization'},
            }

    others = [p for p in get_or_build('portfolio_list', lambda: list(_visible())) if p.pk != item.pk][:3]
    return render(request, 'site/portfolio_detail.html', {
        'item': item,
        'others': others,
        'page_title': f'{item.title} | JamiiTek Portfolio',
        'page_desc': (item.summary or f'{item.title} — built by JamiiTek in Tanzania.')[:300],
        'canonical': url,
        'schema_markup': render_schemas(
            organization_schema(), project,
            breadcrumb_schema([('Home', '/'), ('Portfolio', '/portfolio/'), (item.title, item.get_absolute_url())]),
        ),
    })
