"""Portfolio: orodha ya websites zote; kadi za homepage zinafungua ukurasa huu."""
import json
import re

from django.core.cache import caches
from django.test import TestCase
from django.urls import reverse

from apps.site_content import PortfolioItem


class PortfolioPageTest(TestCase):
    def setUp(self):
        caches['local'].clear()

    def test_wemasa_is_added_by_migration(self):
        item = PortfolioItem.objects.get(live_url__icontains='wemasatanzania.org')
        self.assertTrue(item.is_featured)

    def test_portfolio_lists_every_website_and_links_to_it(self):
        item = PortfolioItem.objects.get(live_url__icontains='wemasatanzania.org')
        r = self.client.get(reverse('portfolio'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn(f'id="p-{item.pk}"', html)
        self.assertIn('href="https://www.wemasatanzania.org/"', html)   # the "Visit site" button
        self.assertNotIn('<a class="work', html)                       # the card itself is not a link
        self.assertIn('<link rel="canonical" href="https://www.jamiitek.com/portfolio/">', html)
        blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        page = next(b for b in blocks if b.get('@type') == 'CollectionPage')
        sites = [e['item'] for e in page['mainEntity']['itemListElement']]
        wemasa = next(s for s in sites if s.get('url') == 'https://www.wemasatanzania.org/')
        self.assertEqual(wemasa['creator']['@id'], 'https://www.jamiitek.com/#organization')

    def test_home_cards_open_the_portfolio_page(self):
        item = PortfolioItem.objects.get(live_url__icontains='wemasatanzania.org')
        html = self.client.get('/').content.decode()
        self.assertIn(f'href="/portfolio/#p-{item.pk}"', html)

    def test_sitemap_lists_the_portfolio(self):
        xml = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('<loc>https://www.jamiitek.com/portfolio/</loc>', xml)
