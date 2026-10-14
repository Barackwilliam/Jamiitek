"""Portfolio: kila kazi ina ukurasa wake, unaoonekana Google na unaounganishwa na tovuti ya mteja."""
import json
import re

from django.core.cache import caches
from django.test import TestCase
from django.urls import reverse

from apps.site_content import PortfolioItem


class PortfolioPagesTest(TestCase):
    def setUp(self):
        caches['local'].clear()

    def test_wemasa_case_study_is_added_by_migration(self):
        item = PortfolioItem.objects.get(slug='wemasa-tanzania')
        self.assertIn('wemasatanzania.org', item.live_url)
        self.assertTrue(item.is_featured)

    def test_list_and_detail_pages(self):
        r = self.client.get(reverse('portfolio'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '/portfolio/wemasa-tanzania/')

        r = self.client.get('/portfolio/wemasa-tanzania/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('href="https://www.wemasatanzania.org/"', html)
        self.assertIn('<link rel="canonical" href="https://www.jamiitek.com/portfolio/wemasa-tanzania/">', html)
        # Structured data names JamiiTek as the creator of the client's live site
        blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        project = next(b for b in blocks if b.get('@type') == 'CreativeWork')
        self.assertEqual(project['creator']['@id'], 'https://www.jamiitek.com/#organization')
        self.assertEqual(project['workExample']['url'], 'https://www.wemasatanzania.org/')

    def test_hidden_or_unknown_projects_404(self):
        PortfolioItem.objects.filter(slug='wemasa-tanzania').update(is_featured=False)
        self.assertEqual(self.client.get('/portfolio/wemasa-tanzania/').status_code, 404)
        self.assertEqual(self.client.get('/portfolio/does-not-exist/').status_code, 404)

    def test_slug_is_generated_and_unique(self):
        a = PortfolioItem.objects.create(title='Shop One', client='Duka Bora')
        b = PortfolioItem.objects.create(title='Shop Two', client='Duka Bora')
        self.assertEqual(a.slug, 'duka-bora')
        self.assertEqual(b.slug, 'duka-bora-2')

    def test_sitemap_lists_case_studies(self):
        xml = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('<loc>https://www.jamiitek.com/portfolio/</loc>', xml)
        self.assertIn('<loc>https://www.jamiitek.com/portfolio/wemasa-tanzania/</loc>', xml)

    def test_home_cards_open_the_case_study(self):
        html = self.client.get('/').content.decode()
        self.assertIn('href="/portfolio/wemasa-tanzania/"', html)
