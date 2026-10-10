"""
JamiiTek SEO — Sitemap definitions
Covers: public pages, service pages, chatbot landing, bot registration
"""
from django.contrib.sitemaps import Sitemap as _Sitemap
from django.urls import reverse

CANONICAL_DOMAIN = 'www.jamiitek.com'


class Sitemap(_Sitemap):
    """
    Kila URL ya sitemap iko kwenye domain rasmi, hata sitemap ikisomwa kupitia
    jamiitek.com au jamiitek.onrender.com — canonical za kurasa zote ni www.
    """
    protocol = 'https'

    def get_domain(self, site=None):
        return CANONICAL_DOMAIN


class StaticPageSitemap(Sitemap):
    """All important static/public pages."""
    protocol = 'https'
    changefreq = 'weekly'

    pages = [
        # (url_name, priority, changefreq)
        ('home',            1.0,  'daily'),
        ('service',         0.9,  'weekly'),
        ('About',           0.7,  'monthly'),
        ('contact',         0.7,  'monthly'),
        ('select_website',  0.8,  'weekly'),
        ('get_started',     0.9,  'weekly'),    # vitufe vyote vya "Start a project"
        ('templates_marketplace', 0.9, 'daily'),
        ('jamiibot_landing',0.95, 'daily'),     # Bot landing page
        ('chatbot_register',0.9,  'weekly'),    # Bot signup
        ('builder:ai_generator', 0.7, 'monthly'),  # "Describe your business" — AI website
        ('privacy_policy',  0.3,  'yearly'),
    ]

    def items(self):
        from apps.models import CompanyProfile
        pages = list(self.pages)
        # Company profile ipo tu kama imewekwa hai — vinginevyo ni 404
        if CompanyProfile.objects.filter(is_active=True).exists():
            pages.append(('company_profile_view', 0.6, 'monthly'))
        return pages

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]

    def changefreq(self, item):
        return item[2]

    # Hakuna lastmod: tarehe ya leo kila siku si ya kweli, na Google huacha
    # kuiamini lastmod ya tovuti nzima ikigundua hivyo (hata ya makala).


class ServiceSitemap(Sitemap):
    """Dynamic service pages."""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.85

    def items(self):
        from apps.models import Service
        # Bila ordering, pagination ya sitemap inaweza kutoa matokeo
        # yasiyolingana kila ombi (UnorderedObjectListWarning).
        # Kila huduma ilikuwa na location ile ile (/service/), kwa hiyo
        # huduma 8 = URL moja iliyorudiwa mara 8 kwenye sitemap. Google
        # inaona nakala. Moja inatosha.
        return Service.objects.order_by('pk')[:1]

    def location(self, item):
        return reverse('service')


class BlogSitemap(Sitemap):
    """Published blog posts + the blog index."""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        from apps.models import BlogPost
        # .only(): bila kupakia body ya kila makala (sitemap ingekuwa nzito sana)
        return list(BlogPost.objects.filter(status='published').order_by('-published_at')
                    .only('slug', 'updated_at', 'published_at'))

    def location(self, item):
        return reverse('blog_detail', kwargs={'slug': item.slug})

    def lastmod(self, item):
        return item.updated_at or item.published_at


class BlogAuthorSitemap(Sitemap):
    """Kurasa za waandishi + sera ya uhariri (E-E-A-T)."""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        from apps.models import BlogAuthor
        return ['__policy__'] + list(BlogAuthor.objects.filter(is_active=True).order_by('pk'))

    def location(self, item):
        if item == '__policy__':
            return reverse('blog_editorial')
        return reverse('blog_author', args=[item.slug])


class BlogIndexSitemap(Sitemap):
    """The /blog/ landing page."""
    protocol = 'https'
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return ['blog_list']

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        from apps.models import BlogPost
        latest = BlogPost.objects.filter(status='published').order_by('-published_at').first()
        return latest.published_at if latest else None


class TemplateSitemap(Sitemap):
    """Ukurasa wa kila template (/templates/<slug>/) — apps/template_seo.py."""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        from apps.models import WebsiteTemplate
        return list(WebsiteTemplate.objects.filter(is_active=True).exclude(slug__isnull=True)
                    .exclude(slug='').order_by('order', 'pk').only('slug', 'updated_at'))

    def location(self, item):
        return item.get_absolute_url()

    def lastmod(self, item):
        return item.updated_at


class TemplateCategorySitemap(Sitemap):
    """Kurasa za jamii: /templates/c/restaurant/ n.k."""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.75

    def items(self):
        from apps.models import WebsiteTemplate
        from apps.template_seo import cat_key, cat_slug
        keys = WebsiteTemplate.objects.filter(is_active=True).values_list('category', flat=True).distinct()
        return sorted({cat_slug(cat_key(k)) for k in keys})

    def location(self, item):
        return reverse('templates_category', args=[item])


# Combine all sitemaps
sitemaps = {
    'static':     StaticPageSitemap(),
    'blog_index': BlogIndexSitemap(),
    'blog':       BlogSitemap(),
    'blog-authors': BlogAuthorSitemap(),
    'templates':  TemplateSitemap(),
    'template-categories': TemplateCategorySitemap(),
}