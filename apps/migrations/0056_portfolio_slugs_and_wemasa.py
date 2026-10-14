from django.db import migrations
from django.utils.text import slugify

WEMASA = {
    'title': 'WEMASA Tanzania — NGO website & content dashboard',
    'client': 'WEMASA Tanzania Organization',
    'category': 'NGO / Non-profit',
    'summary': 'A fast, mobile-first website for an environmental NGO, with a dashboard the team uses to run every page.',
    'live_url': 'https://www.wemasatanzania.org/',
    'year': '2026',
    'image': 'https://www.jamiitek.com/static/images/work/wemasa-tanzania.webp',
    'slug': 'wemasa-tanzania',
    'services': 'Website design, Web development, Content dashboard, SEO, Hosting setup, Staff training',
    'technologies': 'Python, Django, PostgreSQL, Supabase Storage, Render',
    'description': (
        "WEMASA (Weka Mazingira Safi) is a registered Tanzanian NGO working on waste management, "
        "climate education, organic farming and tree planting with communities, schools, women and young people.\n\n"
        "They needed a website that would earn the trust of partners and donors, tell the story of their field work, "
        "and stay up to date without a developer for every change.\n\n"
        "JamiiTek designed and built a complete website: projects, focus areas, news and stories, a photo gallery, "
        "videos, reports to download, partners, certificates and a donation page with bank details that copy in one tap. "
        "Every page is managed from a private content dashboard, so the WEMASA team publishes stories, photos and "
        "videos themselves.\n\n"
        "The site is mobile-first and fast, with automatic image optimisation, search-engine structured data, a sitemap "
        "and one main address for Google, so WEMASA can be found when people search for it."
    ),
    'is_featured': True,
    'order': 0,
}


def forwards(apps, schema_editor):
    PortfolioItem = apps.get_model('apps', 'PortfolioItem')
    used = set(PortfolioItem.objects.exclude(slug__isnull=True).exclude(slug='').values_list('slug', flat=True))
    for item in PortfolioItem.objects.filter(slug__isnull=True) | PortfolioItem.objects.filter(slug=''):
        base = slugify(item.client or item.title)[:120] or 'project'
        slug, n = base, 2
        while slug in used:
            slug, n = f'{base}-{n}', n + 1
        used.add(slug)
        item.slug = slug
        item.save(update_fields=['slug'])

    if not PortfolioItem.objects.filter(live_url__icontains='wemasatanzania.org').exists():
        data = dict(WEMASA)
        if data['slug'] in used:
            data['slug'] = 'wemasa-tanzania-ngo'
        PortfolioItem.objects.create(**data)


class Migration(migrations.Migration):
    dependencies = [('apps', '0055_portfolio_case_studies')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
