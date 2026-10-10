"""
JamiiTek SEO — robots.txt and other SEO endpoints
"""
from apps.contact import contact as _contact
from django.http import HttpResponse
from django.views.decorators.cache import cache_page


@cache_page(60 * 60 * 24)  # Cache 24 hours
def robots_txt(request):
    """
    Dynamic robots.txt — tells Google exactly what to crawl.
    Blocks admin/private portals, allows everything public.
    """
    # Sitemap ziko kwenye domain rasmi (canonical) — si jamiitek.com wala onrender
    host = 'www.jamiitek.com'
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "# Block private areas",
        "Disallow: /admin/",
        "Disallow: /manage/",
        "Disallow: /chatbot/dashboard/",
        "Disallow: /chatbot/config/",
        "Disallow: /chatbot/conversations/",
        "Disallow: /chatbot/billing/",
        "Disallow: /chatbot/setup/",
        "Disallow: /chatbot/webhook/",
        "Disallow: /chatbot/simulate/",
        "Disallow: /api/",
        "Disallow: /cron/",
        "",
        "# Allow important public pages",
        "Allow: /chatbot/register/",
        "Allow: /chatbot/login/",
        "Allow: /bot/",
        "Allow: /templates/",
        "",
        # /portal/ na /templates/preview/*/raw/ HAZIZUIWI hapa kwa makusudi.
        # Zinatuma `X-Robots-Tag: noindex` (apps.seo.middleware). Robots.txt
        # ikizizuia, Google haiwezi kuona noindex, na Search Console inaziripoti
        # "Blocked by robots.txt" milele. Zikiruhusiwa, Google inazisoma na
        # kuziondoa yenyewe.
        # AI: ChatGPT, Perplexity, Claude, Gemini n.k. ziruhusiwe wazi ili
        # templates na huduma zetu zitajwe kwenye majibu yao. Kila kundi la
        # User-agent linasimama peke yake, kwa hiyo sehemu binafsi zinarudiwa.
        "# AI assistants & answer engines — welcome (see /llms.txt)",
        *[f"User-agent: {bot}" for bot in (
            'GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'PerplexityBot', 'Perplexity-User',
            'ClaudeBot', 'Claude-SearchBot', 'Claude-User', 'Google-Extended', 'Applebot-Extended',
            'Bingbot', 'CCBot', 'meta-externalagent', 'cohere-ai', 'DuckAssistBot')],
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /manage/",
        "Disallow: /api/",
        "Disallow: /chatbot/dashboard/",
        "",
        # Crawl-delay imeondolewa: Bing inaiheshimu na ingechelewesha
        # indexing ya habari mpya (makala ~10 kwa siku). Google inaipuuza.
        f"# Sitemaps",
        f"Sitemap: https://{host}/sitemap.xml",
        f"Sitemap: https://{host}/news-sitemap.xml",
        f"# AI summary: https://{host}/llms.txt",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def news_sitemap(request):
    """
    Google News sitemap — makala za siku 2 zilizopita (kanuni ya Google News).
    Inasaidia habari mpya kuonekana haraka kwenye Google News / Top stories / Discover.
    """
    from datetime import timedelta
    from django.utils import timezone
    from django.utils.html import escape
    from django.core.cache import cache
    from apps.models import BlogPost
    from apps.blog_views import cache_version

    host = 'www.jamiitek.com'   # domain rasmi (canonical)
    key = f'blog:newsmap:{cache_version()}:{host}'
    xml = cache.get(key)
    if xml is None:
        since = timezone.now() - timedelta(days=2)
        posts = (BlogPost.objects.filter(status='published', published_at__gte=since)
                 .order_by('-published_at').only('slug', 'title', 'published_at', 'cover_image',
                                                  'focus_keyword')[:1000])
        items = []
        for p in posts:
            img = (f'<image:image><image:loc>{escape(p.cover_image)}</image:loc></image:image>'
                   if p.cover_image else '')
            kw = (f'<news:keywords>{escape(p.focus_keyword)}</news:keywords>'
                  if p.focus_keyword else '')
            items.append(
                f'<url><loc>https://{host}/blog/{p.slug}/</loc>'
                f'<news:news><news:publication><news:name>JamiiTek Insights</news:name>'
                f'<news:language>en</news:language></news:publication>'
                f'<news:publication_date>{p.published_at.isoformat()}</news:publication_date>'
                f'<news:title>{escape(p.title)}</news:title>{kw}</news:news>{img}</url>')
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
               'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9" '
               'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
               + ''.join(items) + '</urlset>')
        cache.set(key, xml, 600)
    return HttpResponse(xml, content_type='application/xml')


def llms_txt(request):
    """
    /llms.txt (llmstxt.org) — muhtasari wa JamiiTek kwa AI (ChatGPT, Claude,
    Perplexity, Gemini): huduma zetu na KILA template na link yake, ili mtu
    akiuliza "website template ya mgahawa Tanzania" AI ipate jibu sahihi.
    """
    from django.core.cache import cache
    from apps.models import WebsiteTemplate
    from apps import template_seo as ts

    tpls = list(WebsiteTemplate.objects.filter(is_active=True).order_by('category', 'order', 'pk'))
    key = 'seo:llms:' + str(max((t.updated_at.timestamp() for t in tpls), default=0)) + f':{len(tpls)}'
    txt = cache.get(key)
    if txt is None:
        base = ts.BASE_URL
        lines = [
            '# JamiiTek',
            '',
            '> JamiiTek is a Tanzanian technology company (Dar es Salaam) that builds websites, '
            'AI WhatsApp chatbots (JamiiBot), hosting and domains for businesses in Tanzania and East Africa. '
            'It runs a free drag-and-drop Website Builder and a marketplace of premium website templates '
            'that anyone can customize for free and publish on yourname.jamiitek.com.',
            '',
            'Prices are in Tanzanian shillings (TSh). Customers can: (1) customize any template free in the '
            'JamiiTek Builder, (2) choose a hosted plan where JamiiTek sets everything up, (3) buy the source code, '
            'or (4) send a proposal for a fully custom website. '
            f"Contact: WhatsApp {_contact()['phone_display']}, info@jamiitek.com.",
            '',
            '## Main pages',
            f'- [Website templates]({base}/templates/): all premium website templates',
            f'- [Website Builder]({base}/builder/signup/): free drag & drop website builder',
            f'- [Custom website proposal]({base}/proposals/): describe your project and get a quotation',
            f'- [JamiiBot]({base}/bot/): AI WhatsApp chatbot for businesses (Swahili & English)',
            f'- [Services]({base}/service/): web development, hosting and domains in Tanzania',
            '',
            '## Website templates',
        ]
        for t in tpls:
            lines.append(f'- [{t.name} — {ts.cat_info(t)["noun"]} website template]({base}{t.get_absolute_url()}): '
                         f'{ts.plain(t.description, 180)} Customize free; hosted TSh {t.price_hosted_monthly:,}/month; '
                         f'source code TSh {t.price_source_code:,}.')
        cats = sorted({ts.cat_key(t) for t in tpls})
        if cats:
            lines += ['', '## Template categories']
            lines += [f'- [{ts.cat_info(c)["noun"].title()} website templates]({base}/templates/c/{ts.cat_slug(c)}/)' for c in cats]
        lines += ['', '## Optional', f'- [Blog]({base}/blog/): guides on websites, SEO and digital business in Tanzania']
        txt = '\n'.join(lines) + '\n'
        cache.set(key, txt, 3600)
    return HttpResponse(txt, content_type='text/plain; charset=utf-8')
