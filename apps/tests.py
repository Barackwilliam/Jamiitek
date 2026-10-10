import json
import re
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from .models import WebsiteTemplate, WebsiteType, ProjectProposal


class NoPingMixin:
    """IndexNow isijaribu mtandao wakati wa tests (setUp pia inahifadhi templates)."""
    def setUp(self):
        p = mock.patch('apps.indexnow.ping')
        p.start()
        self.addCleanup(p.stop)
        super().setUp()


def _tpl(**kw):
    data = dict(name='Savanna Luxe', category='Tourism', description='A luxury safari website with tours and booking.',
                preview_html='<!doctype html><html><body><h1>Wild Tanzania</h1></body></html>')
    data.update(kw)
    return WebsiteTemplate.objects.create(**data)


class TemplateSeoTest(NoPingMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tpl = _tpl()

    def test_slug_is_generated_unique_and_avoids_reserved_paths(self):
        self.assertEqual(self.tpl.slug, 'savanna-luxe')
        self.assertEqual(_tpl().slug, 'savanna-luxe-2')
        self.assertEqual(_tpl(name='Preview').slug, 'preview-template')
        self.assertEqual(self.tpl.get_absolute_url(), '/templates/savanna-luxe/')

    def test_detail_page_has_unique_meta_real_text_and_json_ld(self):
        r = self.client.get('/templates/savanna-luxe/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('<title>Savanna Luxe — Safari &amp; Travel Website Template | JamiiTek</title>', html)
        self.assertIn('<link rel="canonical" href="https://www.jamiitek.com/templates/savanna-luxe/">', html)
        self.assertIn('<h1>Savanna Luxe', html)
        self.assertIn('Kwa Kiswahili', html)                 # maandishi ya Kiswahili pia
        self.assertIn('/builder/templates/%d/use/' % self.tpl.pk, html)
        self.assertIn('/proposals/?template=%d' % self.tpl.pk, html)
        blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        types = [b.get('@type') for b in blocks]
        for t in ('Product', 'BreadcrumbList', 'FAQPage'):
            self.assertIn(t, types)
        product = next(b for b in blocks if b.get('@type') == 'Product')
        self.assertEqual(product['offers'][0]['price'], '0')
        self.assertNotIn('aggregateRating', product)       # hakuna rating za kubuni

    def test_inactive_or_unknown_template_is_404(self):
        _tpl(name='Hidden', is_active=False)
        self.assertEqual(self.client.get('/templates/hidden/').status_code, 404)
        self.assertEqual(self.client.get('/templates/nope/').status_code, 404)

    def test_old_urls_still_work_and_point_google_to_the_new_page(self):
        r = self.client.get(f'/templates/preview/{self.tpl.pk}/')
        self.assertContains(r, '<link rel="canonical" href="https://www.jamiitek.com/templates/savanna-luxe/">', html=False)
        raw = self.client.get(f'/templates/preview/{self.tpl.pk}/raw/')
        self.assertEqual(raw['X-Robots-Tag'], 'noindex, follow')

    def test_category_page_and_crawlable_chips(self):
        _tpl(name='Mama Lishe', category='restaurant')
        r = self.client.get('/templates/c/tourism/')
        self.assertContains(r, 'Safari &amp; Travel Website Templates')
        self.assertContains(r, 'Savanna Luxe')
        self.assertNotContains(r, 'Mama Lishe</a></h3>')
        self.assertContains(r, '"@type": "ItemList"')
        self.assertEqual(self.client.get('/templates/c/unknown/').status_code, 404)
        m = self.client.get('/templates/')
        self.assertContains(m, 'href="/templates/c/restaurant/"')
        self.assertContains(m, 'href="/templates/savanna-luxe/"')

    def test_sitemap_llms_and_robots(self):
        sm = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('/templates/savanna-luxe/', sm)
        self.assertIn('/templates/c/tourism/', sm)
        self.assertIn('/templates/</loc>', sm)
        llms = self.client.get('/llms.txt').content.decode()
        self.assertIn('# JamiiTek', llms)
        self.assertIn('[Savanna Luxe — safari & travel website template](https://www.jamiitek.com/templates/savanna-luxe/)', llms)
        robots = self.client.get('/robots.txt').content.decode()
        self.assertIn('User-agent: GPTBot', robots)
        self.assertIn('llms.txt', robots)
        # Kurasa zenye noindex zisizuiwe, la sivyo Google haioni noindex
        self.assertNotIn('Disallow: /portal/', robots)
        self.assertNotIn('/raw/', robots)
        self.assertIn('Disallow: /manage/', robots)
        self.assertEqual(self.client.get('/portal/register/')['X-Robots-Tag'], 'noindex, follow')

    def test_saving_a_template_pings_indexnow(self):
        with mock.patch('apps.indexnow.ping') as ping:
            self.tpl.save()
        self.assertIn('/templates/savanna-luxe/', ping.call_args[0][0])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ProposalFlowTest(NoPingMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.tpl = _tpl()
        self.wt = WebsiteType.objects.create(name='Company Profile', description='For companies', icon='fas fa-briefcase')

    def test_step_one_links_templates_and_proposal(self):
        r = self.client.get('/proposals/')
        self.assertContains(r, 'We’ll design it for you')
        self.assertContains(r, f'/proposals/form/{self.wt.pk}/')
        self.assertContains(r, f'/proposals/?template={self.tpl.pk}')
        r = self.client.get(f'/proposals/?template={self.tpl.pk}')
        self.assertContains(r, 'Your starting design')
        self.assertContains(r, f'/proposals/form/{self.wt.pk}/?template={self.tpl.pk}')

    def test_submitting_a_proposal_emails_jamiitek_and_confirms(self):
        from .forms import DynamicProposalForm
        form = DynamicProposalForm(self.wt.name)
        data = {'reference_template': self.tpl.pk}
        for name, field in form.fields.items():
            if name == 'turnstile':
                continue
            if name == 'client_email':
                data[name] = 'asha@example.com'
            elif getattr(field, 'choices', None):
                data[name] = [str(field.choices[0][0])] if field.widget.allow_multiple_selected else str(field.choices[0][0])
            else:
                data[name] = 'Asha' if name.startswith('client_') else 'Some text'
        with mock.patch('threading.Thread') as T:
            T.side_effect = lambda target, daemon: mock.Mock(start=target)
            r = self.client.post(f'/proposals/form/{self.wt.pk}/', data)
        p = ProjectProposal.objects.get()
        self.assertRedirects(r, f'/proposals/preview/{p.pk}/?sent=1')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f'JT-{p.pk}', mail.outbox[0].subject)
        self.assertIn('Savanna Luxe', mail.outbox[0].alternatives[0][0])
        self.assertEqual(p.requirements['reference_template']['preview_url'], '/templates/savanna-luxe/')
        self.assertContains(self.client.get(r['Location']), 'Sent to JamiiTek')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NewsletterTest(TestCase):
    """Fomu ya footer ilituma email peke yake kwenda /contact/ na kupata
    "Please fill in all fields". Sasa ina njia yake."""
    url = '/newsletter/subscribe/'

    def test_ajax_subscribe_sends_notice(self):
        r = self.client.post(self.url, {'email': 'neema@biashara.co.tz'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('neema@biashara.co.tz', mail.outbox[0].body)

    def test_invalid_email_rejected(self):
        r = self.client.post(self.url, {'email': 'si-email'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 0)

    def test_without_js_redirects_back_with_status(self):
        r = self.client.post(self.url, {'email': 'juma@example.com'}, HTTP_REFERER='http://testserver/About/?x=1')
        self.assertRedirects(r, '/About/?subscribed=ok#site-footer', fetch_redirect_response=False)

    def test_foreign_referer_is_not_followed(self):
        r = self.client.post(self.url, {'email': 'juma@example.com'}, HTTP_REFERER='https://evil.example/')
        self.assertEqual(r['Location'], '/?subscribed=ok#site-footer')

    def test_honeypot_drops_silently(self):
        r = self.client.post(self.url, {'email': 'bot@spam.com', 'company_website': 'x'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 0)

    def test_get_redirects_home(self):
        self.assertRedirects(self.client.get(self.url), '/', fetch_redirect_response=False)


class SpotlightTest(TestCase):
    """JamiiTek Spotlight: makala 1 kuhusu JamiiTek Jumatatu/Jumatano/Jumamosi."""

    def setUp(self):
        from datetime import datetime
        from django.utils import timezone as tz
        self.monday = tz.make_aware(datetime(2026, 10, 5, 6, 0))     # Jumatatu
        self.tuesday = tz.make_aware(datetime(2026, 10, 6, 6, 0))    # Jumanne
        self.n = 0

    def _fake_write(self, titles):
        it = iter(titles)
        def write(topic_name, facts, angle_text, previous, avoid):
            self.n += 1
            t = next(it)
            return True, {'title': t, 'slug': t.lower().replace(' ', '-'), 'excerpt': 'x', 'body': '<p>Body</p>',
                          'meta_title': t[:60], 'meta_description': 'd', 'focus_keyword': 'k', 'tags': 'a'}
        return write

    def _run(self, when, titles, **kw):
        from apps import spotlight_blog as sb
        with mock.patch.object(sb.timezone, 'localtime', return_value=when), \
             mock.patch('django.utils.timezone.now', return_value=when), \
             mock.patch.object(sb, 'write', side_effect=self._fake_write(titles)), \
             mock.patch('apps.news_blog.unsplash_cover', return_value=''):
            return sb.run(**kw)

    def test_only_on_spotlight_days(self):
        r = self._run(self.tuesday, ['Should not be written'])
        self.assertEqual(r['created'], [])
        self.assertIn('not a spotlight day', r['skipped'])
        self.assertEqual(self.n, 0)

    def test_writes_one_draft_on_monday_then_stops(self):
        r = self._run(self.monday, ['How JamiiBot Answers Customers at 2am'])
        self.assertEqual(len(r['created']), 1)
        post = r['created'][0]
        self.assertEqual(post.status, 'draft')
        self.assertEqual(post.category.slug, 'jamiitek-spotlight')
        self.assertTrue(post.source_name.startswith('spotlight:'))
        again = self._run(self.monday, ['Another One'])
        self.assertEqual(again['created'], [])
        self.assertEqual(again['skipped'], 'already wrote today')

    def test_topic_and_angle_never_repeat(self):
        from apps.models import BlogPost
        keys = set()
        heads = ['How JamiiBot Answers Customers at 2am', 'Choosing Between .co.tz and .com',
                 'Five Mistakes Shops Make With Their First Website', 'Inside Our Daily Backup Routine',
                 'What Safari Companies Need From a Booking Page', 'Mobile Money Checkout Explained Simply']
        for i in range(6):
            r = self._run(self.monday, [heads[i]], force=True)
            self.assertEqual(len(r['created']), 1, r)
            keys.add(r['created'][0].source_name)
        self.assertEqual(len(keys), 6)
        self.assertEqual(BlogPost.objects.filter(source_name__startswith='spotlight:').count(), 6)

    def test_similar_title_is_rejected_and_retried(self):
        from apps.models import BlogPost
        BlogPost.objects.create(title='Why Every Dar Shop Needs a WhatsApp Bot', slug='why-bot',
                                excerpt='x', body='<p>x</p>')
        r = self._run(self.monday, ['Why every Dar shop needs a WhatsApp bot!',
                                    'Five Questions Shop Owners Ask About Online Orders'])
        self.assertEqual(self.n, 2)
        self.assertEqual(r['created'][0].title, 'Five Questions Shop Owners Ask About Online Orders')

    def test_gives_up_without_unique_title(self):
        from apps.models import BlogPost
        BlogPost.objects.create(title='Same Title', slug='same', excerpt='x', body='<p>x</p>')
        r = self._run(self.monday, ['Same Title', 'same title', 'Same  Title.'])
        self.assertEqual(r['created'], [])
        self.assertEqual(self.n, 3)

    def test_autopublish_flag(self):
        with mock.patch.dict('os.environ', {'SPOTLIGHT_AUTOPUBLISH': '1'}):
            r = self._run(self.monday, ['A Practical Guide to .co.tz Domains'])
        self.assertEqual(r['created'][0].status, 'published')


class SiteSeoTest(NoPingMixin, TestCase):
    """SEO ya kurasa kuu: hakuna rating za kubuni, /bot/ ina canonical na schema."""

    def _ld(self, html):
        out = []
        for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            j = json.loads(b)
            out.extend(j if isinstance(j, list) else [j])
        return out

    def test_no_fake_ratings_anywhere(self):
        for url in ('/', '/bot/', '/service/', '/About/', '/contact/', '/get-started/'):
            html = self.client.get(url).content.decode()
            self.assertNotIn('aggregateRating', html, url)

    def test_bot_landing_has_canonical_og_and_schema(self):
        html = self.client.get('/bot/').content.decode()
        self.assertIn('<link rel="canonical" href="https://www.jamiitek.com/bot/">', html)
        self.assertIn('property="og:image"', html)
        types = [b.get('@type') for b in self._ld(html)]
        self.assertIn('SoftwareApplication', types)
        self.assertIn('BreadcrumbList', types)

    def test_key_pages_have_schema_and_tanzania_titles(self):
        for url, kind in (('/About/', 'AboutPage'), ('/contact/', 'ContactPage'), ('/get-started/', 'FAQPage')):
            html = self.client.get(url).content.decode()
            self.assertIn(kind, [b.get('@type') for b in self._ld(html)], url)
            title = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
            self.assertIn('Tanzania', title, url)

    def test_sitemap_lists_get_started_once_and_service_once(self):
        xml = self.client.get('/sitemap.xml').content.decode()
        locs = [re.sub(r'^https?://[^/]+', '', u) for u in re.findall(r'<loc>([^<]*)</loc>', xml)]
        self.assertIn('/get-started/', locs)
        self.assertEqual(locs.count('/service/'), 1)


class SeoAuditFixesTest(NoPingMixin, TestCase):
    """Marekebisho ya ukaguzi wa SEO: domain rasmi, canonical, noindex, alt, viungo."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)

    def test_sitemaps_and_robots_use_the_canonical_domain_only(self):
        xml = self.client.get('/sitemap.xml', HTTP_HOST='jamiitek.onrender.com').content.decode()
        locs = re.findall(r'<loc>([^<]*)</loc>', xml)
        self.assertTrue(locs)
        self.assertTrue(all(u.startswith('https://www.jamiitek.com/') for u in locs), locs)
        self.assertIn('https://www.jamiitek.com/builder/ai/', locs)
        self.assertIn('https://www.jamiitek.com/chatbot/privacy-policy/', locs)
        self.assertNotIn('https://www.jamiitek.com/company-profile/', locs)   # hakuna profile hai
        # Kurasa za kudumu hazina lastmod ya "leo" ya kubuni
        home = re.search(r'<url><loc>https://www.jamiitek.com/</loc>(.*?)</url>', xml, re.S).group(1)
        self.assertNotIn('<lastmod>', home)
        robots = self.client.get('/robots.txt', HTTP_HOST='jamiitek.com').content.decode()
        self.assertIn('Sitemap: https://www.jamiitek.com/sitemap.xml', robots)

    def test_company_profile_link_only_when_profile_exists(self):
        from apps.models import CompanyProfile
        self.assertNotContains(self.client.get('/'), '/company-profile/')
        CompanyProfile.objects.create(is_active=True)
        from django.core.cache import cache
        cache.clear()
        self.assertContains(self.client.get('/'), '/company-profile/')
        self.assertEqual(self.client.get('/company-profile/').status_code, 200)

    def test_standalone_pages_have_canonical_and_social_tags(self):
        for url in ('/chatbot/register/?plan=pro', '/chatbot/privacy-policy/', '/builder/ai/'):
            html = self.client.get(url).content.decode()
            path = url.split('?')[0]
            self.assertIn(f'<link rel="canonical" href="https://www.jamiitek.com{path}">', html, url)
            self.assertIn('property="og:title"', html, url)
            self.assertIn('name="twitter:card"', html, url)
            self.assertIn('name="description"', html, url)
        login = self.client.get('/chatbot/login/').content.decode()
        self.assertIn('<meta name="robots" content="noindex, follow">', login)

    def test_old_base_twitter_image_and_non_blocking_fonts(self):
        html = self.client.get('/templates/').content.decode()
        self.assertIn('name="twitter:image"       content="https://www.jamiitek.com/static/images/og-image.jpg"', html)
        self.assertNotIn('/static/images.jpg', html)
        self.assertNotIn('family=Orbitron:wght@700;800&family=Exo+2:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet"', html)

    def test_article_images_get_alt_and_lazy_loading(self):
        from apps.templatetags.blog_extras import img_seo
        out = img_seo('<p><img src="/a.jpg"><img src="/b.jpg" alt="Ramani" loading="eager"></p>', 'Bei ya "website"')
        self.assertIn('<img src="/a.jpg" alt="Bei ya &quot;website&quot;" loading="lazy" decoding="async">', out)
        self.assertIn('alt="Ramani" loading="eager" decoding="async"', out)

    def test_titles_and_descriptions_stay_within_search_limits(self):
        WebsiteType.objects.create(name='E-commerce')
        for url in ('/service/', '/proposals/', '/templates/'):
            html = self.client.get(url).content.decode()
            title = re.search(r'<title>(.*?)</title>', html, re.S).group(1).strip()
            desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
            self.assertLessEqual(len(title), 65, (url, title))
            self.assertLessEqual(len(desc), 165, (url, desc))


class OneAccountTest(NoPingMixin, TestCase):
    """Akaunti moja: Web Builder ↔ Client Portal ↔ JamiiBot (apps/accounts_link.py)."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('neema', 'neema@example.com', 'Kilimo2026!')

    def test_builder_account_signs_in_to_client_portal(self):
        from apps.models import Client
        r = self.client.post('/portal/login/', {'username': 'neema', 'password': 'Kilimo2026!'})
        self.assertRedirects(r, '/portal/', fetch_redirect_response=False)
        c = Client.objects.get(user=self.user)
        self.assertEqual(c.email, 'neema@example.com')
        self.assertEqual(self.client.get('/portal/').status_code, 200)

    def test_portal_login_accepts_email_and_blocks_external_next(self):
        r = self.client.post('/portal/login/', {'username': 'NEEMA@example.com', 'password': 'Kilimo2026!',
                                                'next': '//evil.example/x'})
        self.assertRedirects(r, '/portal/', fetch_redirect_response=False)

    def test_builder_account_signs_in_to_jamiibot(self):
        from apps.chatbot.models import ChatbotClient
        r = self.client.post('/chatbot/login/', {'username': 'neema@example.com', 'password': 'Kilimo2026!'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(ChatbotClient.objects.filter(user=self.user).exists())

    def test_already_signed_in_goes_straight_to_bot(self):
        self.client.force_login(self.user)
        r = self.client.get('/chatbot/login/')
        self.assertRedirects(r, '/chatbot/dashboard/', fetch_redirect_response=False)

    def test_switcher_on_all_three_apps(self):
        self.client.force_login(self.user)
        for url in ('/portal/', '/builder/'):
            html = self.client.get(url).content.decode()
            self.assertIn('Switch app', html, url)
            for href in ('href="/portal/"', 'href="/chatbot/dashboard/"', 'href="/builder/"'):
                self.assertIn(href, html, url)


class SecurityHardeningTest(TestCase):
    """Kufunga login baada ya makosa mengi, headers, na `next` salama."""

    def setUp(self):
        from django.contrib.auth.models import User
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user('mlinzi', 'mlinzi@example.com', 'Sahihi-Kabisa-2026')

    def _portal(self, password, **extra):
        return self.client.post('/portal/login/', {'username': 'mlinzi', 'password': password, **extra})

    def test_account_locks_after_five_failures_even_with_right_password(self):
        for _ in range(5):
            self._portal('kosa')
        r = self._portal('Sahihi-Kabisa-2026')
        self.assertContains(r, 'Too many failed sign-in attempts')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_lock_applies_to_every_login_page(self):
        for _ in range(5):
            self._portal('kosa')
        r = self.client.post('/builder/login/', {'username': 'mlinzi', 'password': 'Sahihi-Kabisa-2026'})
        self.assertContains(r, 'Too many failed sign-in attempts')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_success_resets_counter(self):
        for _ in range(4):
            self._portal('kosa')
        self._portal('Sahihi-Kabisa-2026')
        self.client.logout()
        for _ in range(4):
            self._portal('kosa')
        self._portal('Sahihi-Kabisa-2026')
        self.assertIn('_auth_user_id', self.client.session)

    def test_portal_next_rejects_external_redirect(self):
        for bad in ('//evil.com', '/\\evil.com', 'https://evil.com/'):
            self.client.logout()
            r = self._portal('Sahihi-Kabisa-2026', next=bad)
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r['Location'], '/portal/', bad)

    def test_security_headers_present(self):
        r = self.client.get('/')
        self.assertIn('camera=()', r['Permissions-Policy'])
        self.assertIn("object-src 'none'", r['Content-Security-Policy'])

    def test_private_pages_not_cached_for_signed_in_users(self):
        self._portal('Sahihi-Kabisa-2026')
        r = self.client.get('/portal/')
        self.assertIn('no-store', r.get('Cache-Control', ''))


class SecurityFixesTest(NoPingMixin, TestCase):
    """Matundu yaliyogunduliwa kwenye ukaguzi wa usalama — yasirudi."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        from django.contrib.auth.models import User
        from apps.chatbot.models import BotConfig, BotSubscription, ChatbotClient, SubscriptionPlan
        cache.clear()
        plans = list(SubscriptionPlan.objects.filter(is_active=True).order_by('price_tzs'))
        self.cheap, self.dear = plans[0], plans[-1]
        self.user = User.objects.create_user('duka', 'd@x.com', 'Sahihi-Kabisa-2026')
        cl = ChatbotClient.objects.create(user=self.user, full_name='Mama Duka',
                                          business_name='Duka', email='d@x.com')
        self.bot = BotConfig.objects.create(client=cl, bot_name='DukaBot', business_name='Duka',
                                            status='active', is_active=True,
                                            owner_whatsapp='255754111225')
        self.sub = BotSubscription.objects.create(bot=self.bot, plan=self.cheap, status='active')

    # ── JamiiBot ──
    def test_is_owner_needs_nine_digits(self):
        self.assertFalse(self.bot.is_owner('5'))
        self.assertFalse(self.bot.is_owner('w5'))
        self.assertTrue(self.bot.is_owner('255754111225'))

    def test_web_chat_visitor_cannot_run_owner_commands(self):
        from apps.chatbot import handoff
        with mock.patch.object(handoff, 'handle_owner_command', return_value=True) as cmd, \
                mock.patch('apps.chatbot.views.ai_engine', create=True):
            self.client.post(f'/chatbot/web/{self.bot.id}/', json.dumps(
                {'visitor': '255754111225', 'message': 'orodha'}), content_type='application/json')
        cmd.assert_not_called()

    def test_meta_webhook_rejects_unsigned_post(self):
        body = json.dumps({'entry': [{'changes': [{'value': {'messages': [
            {'from': '255700000000', 'id': 'x', 'type': 'text', 'text': {'body': 'hi'}}]}}]}]})
        with mock.patch('apps.chatbot.views._process_message') as pm:
            r = self.client.post(f'/chatbot/webhook/{self.bot.id}/', body, content_type='application/json')
            r2 = self.client.post('/chatbot/webhook/', body, content_type='application/json')
        self.assertEqual((r.status_code, r2.status_code), (403, 403))
        pm.assert_not_called()

    def test_meta_webhook_accepts_valid_signature(self):
        import hashlib, hmac
        body = b'{"entry": []}'
        sig = 'sha256=' + hmac.new(b'app-secret', body, hashlib.sha256).hexdigest()
        with override_settings(WHATSAPP_APP_SECRET='app-secret'):
            r = self.client.post('/chatbot/webhook/', body, content_type='application/json',
                                 HTTP_X_HUB_SIGNATURE_256=sig)
        self.assertEqual(r.status_code, 200)

    def test_letters_only_visitor_is_rate_limited(self):
        from apps.chatbot import ratelimit
        results = [ratelimit.check(self.bot, 'wabcdefgh')[0] for _ in range(ratelimit.PER_CUSTOMER_MINUTE + 1)]
        self.assertFalse(results[-1])

    def test_paid_subscription_cannot_switch_plan_via_deploy(self):
        self.client.force_login(self.user)
        self.client.post('/chatbot/setup/', {'action': 'deploy', 'plan_id': self.dear.id})
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.plan_id, self.cheap.id)

    def test_suspended_bot_cannot_redeploy_itself(self):
        self.bot.status, self.bot.is_active, self.bot.admin_suspended_reason = 'suspended', False, 'abuse'
        self.bot.save()
        self.client.force_login(self.user)
        self.client.post('/chatbot/setup/', {'action': 'deploy', 'plan_id': self.cheap.id})
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.status, 'suspended')

    def test_unparseable_amount_rejected(self):
        from apps.chatbot.models import SubscriptionPayment
        self.client.force_login(self.user)
        self.client.post('/chatbot/billing/', {'transaction_ref': 'ABC1', 'months': 12,
                                               'plan_id': self.dear.id, 'amount': 'x'})
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_bulk_verify_holds_underpaid(self):
        from django.contrib.auth.models import User
        from apps.chatbot.models import SubscriptionPayment
        pay = SubscriptionPayment.objects.create(subscription=self.sub, plan=self.dear, amount=1000,
                                                 months_covered=12, transaction_ref='LOW1')
        staff = User.objects.create_user('boss', 'b@x.com', 'Sahihi-Kabisa-2026', is_staff=True)
        self.client.force_login(staff)
        self.client.post('/manage/chatbot/payments/bulk-action/',
                         {'bulk_action': 'verify_all', 'payment_ids': [pay.id]})
        pay.refresh_from_db()
        self.assertEqual(pay.status, 'pending')

    def test_weak_password_rejected_on_bot_register(self):
        from django.contrib.auth.models import User
        self.client.post('/chatbot/register/', {
            'username': 'dhaifu', 'email': 'dh@x.com', 'full_name': 'Dhaifu Mtu',
            'business_name': 'Biz', 'password': '12345678', 'password2': '12345678'})
        self.assertFalse(User.objects.filter(username='dhaifu').exists())

    # ── Mengine ──
    def test_sanitizer_strips_script_vectors(self):
        from apps.html_sanitize import clean_html
        dirty = ('<p>Habari</p><img src=x onerror=alert(1)><a href="javascript:alert(1)">x</a>'
                 "<svg onload='alert(1)'><circle/></svg><script>alert(1)</script>"
                 '<a href="https://jamiitek.com" target="_blank">ok</a>')
        out = clean_html(dirty)
        for bad in ('onerror', 'javascript:', 'onload', '<svg', '<script', 'alert(1)</'):
            self.assertNotIn(bad, out)
        self.assertIn('<p>Habari</p>', out)
        self.assertIn('href="https://jamiitek.com"', out)
        self.assertIn('rel="noopener noreferrer"', out)

    def test_upload_rejects_html_disguised_as_png(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps import storage
        f = SimpleUploadedFile('a.png', b'<html><script>x</script>', content_type='text/html')
        with mock.patch.object(storage, 'is_configured', return_value=True), \
                mock.patch.object(storage, '_put') as put:
            r = storage.upload(f)
        self.assertFalse(r['success'])
        put.assert_not_called()
        png = SimpleUploadedFile('a.png', b'\x89PNG\r\n\x1a\n' + b'0' * 20, content_type='text/html')
        with mock.patch.object(storage, 'is_configured', return_value=True), \
                mock.patch.object(storage, '_put', return_value={'success': True}) as put:
            storage.upload(png)
        self.assertEqual(put.call_args[0][2], 'image/png')

    def test_brevo_webhook_fails_closed_without_token(self):
        r = self.client.post('/webhooks/brevo/', '[]', content_type='application/json')
        self.assertEqual(r.status_code, 403)


@mock.patch.dict('os.environ', {'STAFF_2FA_REQUIRED': 'True'})
class StaffTwoFactorTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from django.core.cache import cache
        cache.clear()
        self.staff = User.objects.create_user('boss', 'boss@x.com', 'Sahihi-Kabisa-2026', is_staff=True)

    def _login(self):
        self.client.post('/manage/login/', {'username': 'boss', 'password': 'Sahihi-Kabisa-2026'})

    def _enroll(self):
        from apps import two_factor as tf
        self._login()
        self.client.get('/account/2fa/setup/')
        secret = self.client.session['staff_2fa_pending']
        r = self.client.post('/account/2fa/setup/', {'code': tf.totp_at(secret, int(__import__('time').time() // 30))})
        return secret, r

    def test_totp_matches_rfc6238_vector(self):
        from apps import two_factor as tf
        secret = __import__('base64').b32encode(b'12345678901234567890').decode()
        # RFC 6238 SHA1, T=59 → 94287082 (tarakimu 8); 6 za mwisho
        self.assertEqual(tf.totp_at(secret, 59 // 30), '287082')

    def test_staff_forced_to_set_up_2fa(self):
        self._login()
        r = self.client.get('/manage/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('/account/2fa/setup/'))

    def test_enroll_shows_recovery_codes_and_unlocks(self):
        secret, r = self._enroll()
        self.assertContains(r, 'Two-step verification is on')
        self.assertEqual(len(r.context['codes']), 8)
        self.assertNotEqual(self.client.get('/manage/').get('Location', ''), '/account/2fa/setup/')
        from apps.security_models import StaffTwoFactor
        rec = StaffTwoFactor.objects.get(user=self.staff)
        self.assertNotIn(secret, rec.secret_encrypted)        # imesimbwa

    def test_new_login_needs_code_and_code_cannot_be_replayed(self):
        import time
        from apps import two_factor as tf
        secret, _ = self._enroll()
        self.client.logout()
        self._login()
        r = self.client.get('/manage/clients/')
        self.assertEqual(r['Location'], '/account/2fa/')     # hakuna ?next= kwenye URL
        page = self.client.get('/account/2fa/').content.decode()
        for leak in ('Staff', 'staff', '/manage/', 'payments'):
            self.assertNotIn(leak, page)
        # Code ile ile iliyotumika kwenye setup haikubaliwi tena (replay)
        used = tf.totp_at(secret, int(time.time() // 30))
        r = self.client.post('/account/2fa/', {'code': used})
        self.assertContains(r, 'not valid')
        # Code ya hatua inayofuata inakubaliwa
        nxt = tf.totp_at(secret, int(time.time() // 30) + 1)
        r = self.client.post('/account/2fa/', {'code': nxt})
        self.assertEqual(r['Location'], '/manage/clients/')   # inarudi ulikokuwa

    def test_recovery_code_works_once(self):
        _, r = self._enroll()
        code = r.context['codes'][0]
        for expect_ok in (True, False):
            self.client.logout()
            self._login()
            r = self.client.post('/account/2fa/', {'mode': 'recovery', 'code': code, 'next': '/manage/'})
            if expect_ok:
                self.assertEqual(r['Location'], '/manage/')
            else:
                self.assertContains(r, 'not valid')

    def test_five_wrong_codes_sign_out(self):
        self._enroll()
        self.client.logout()
        self._login()
        for _ in range(5):
            r = self.client.post('/account/2fa/', {'code': '000000'})
        self.assertEqual(r['Location'], '/manage/login/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_help_and_privacy_open_during_2fa(self):
        self._enroll()
        self.client.logout()
        self._login()
        self.assertEqual(self.client.get('/manage/').status_code, 302)      # bado inahitaji code
        for url in ('/account/help/', '/chatbot/privacy-policy/'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertContains(self.client.get('/account/2fa/'), '/account/help/')

    def test_clients_are_not_asked_for_2fa(self):
        from django.contrib.auth.models import User
        from apps.models import Client
        u = User.objects.create_user('mteja', 'm@x.com', 'Sahihi-Kabisa-2026')
        Client.objects.create(user=u, name='Mteja', email='m@x.com')
        self.client.force_login(u)
        self.assertEqual(self.client.get('/portal/').status_code, 200)

    def test_reset_command_removes_2fa(self):
        from django.core.management import call_command
        from apps.security_models import StaffTwoFactor
        self._enroll()
        call_command('reset_staff_2fa', 'boss', stdout=__import__('io').StringIO())
        self.assertFalse(StaffTwoFactor.objects.exists())


class PasswordResetTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user('asha', 'asha@example.com', 'Zamani-Sana-2026')

    def _link(self):
        self.client.post('/account/password-reset/', {'email': 'ASHA@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        return re.search(r'https?://[^/\s]+(/account/password-reset/[^\s]+/)', body).group(1), body

    def test_same_response_for_unknown_email(self):
        r = self.client.post('/account/password-reset/', {'email': 'nobody@example.com'})
        self.assertRedirects(r, '/account/password-reset/sent/')
        self.assertEqual(len(mail.outbox), 0)

    def test_link_uses_configured_domain_not_host_header(self):
        with override_settings(SITE_BASE_URL='https://www.jamiitek.com'):
            self.client.post('/account/password-reset/', {'email': 'asha@example.com'},
                             HTTP_HOST='localhost')
        self.assertIn('https://www.jamiitek.com/account/password-reset/', mail.outbox[0].body)

    def test_full_reset_flow_unlocks_and_link_dies(self):
        from apps.security import _key
        from django.core.cache import cache
        cache.set(_key('user', 'asha'), 99, 900)       # imefungwa kwa makosa
        path, _ = self._link()
        r = self.client.get(path, follow=True)
        set_url = r.redirect_chain[-1][0]
        weak = self.client.post(set_url, {'new_password1': '12345678', 'new_password2': '12345678'})
        self.assertContains(weak, 'too common')
        r = self.client.post(set_url, {'new_password1': 'Mpya-Kabisa-2026!', 'new_password2': 'Mpya-Kabisa-2026!'})
        self.assertRedirects(r, '/account/password-reset/complete/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Mpya-Kabisa-2026!'))
        self.assertIsNone(cache.get(_key('user', 'asha')))
        self.assertIn('password was changed', mail.outbox[-1].subject)
        # Link haitumiki mara ya pili
        self.assertContains(self.client.get(path, follow=True), 'This link has expired')

    def test_requests_are_rate_limited(self):
        for _ in range(8):
            self.client.post('/account/password-reset/', {'email': 'asha@example.com'})
        self.assertEqual(len(mail.outbox), 5)

    def test_login_pages_link_to_reset(self):
        for url in ('/portal/login/', '/chatbot/login/', '/builder/login/', '/manage/login/'):
            self.assertContains(self.client.get(url), '/account/password-reset/', msg_prefix=url)


class AdminPagesRenderTest(TestCase):
    """Kurasa za admin/manage zenye data zifunguke (zilikuwa zinaanguka au nzito)."""

    def test_subscription_payment_admin_list_renders(self):
        from django.contrib.auth.models import User
        from apps.chatbot.models import (BotConfig, BotSubscription, ChatbotClient,
                                         SubscriptionPayment, SubscriptionPlan)
        boss = User.objects.create_superuser('boss2', 'b2@x.com', 'Sahihi-Kabisa-2026')
        cl = ChatbotClient.objects.create(user=boss, full_name='B', business_name='Biz', email='b2@x.com')
        bot = BotConfig.objects.create(client=cl, bot_name='B', business_name='Biz')
        plan = SubscriptionPlan.objects.filter(is_active=True).first()
        sub = BotSubscription.objects.create(bot=bot, plan=plan, status='active')
        SubscriptionPayment.objects.create(subscription=sub, plan=plan, amount=15000,
                                           months_covered=1, transaction_ref='Z1')
        self.client.force_login(boss)
        r = self.client.get('/admin/chatbot/subscriptionpayment/')
        self.assertContains(r, 'TZS 15,000')
        for url in ('/manage/chatbot/', '/manage/chatbot/clients/', '/manage/infra/',
                    '/manage/websites/', '/manage/clients/', '/admin/chatbot/botconfig/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)


@mock.patch.dict('os.environ', {'STAFF_2FA_REQUIRED': 'True'})
class StaffTwoFactorDoubleSubmitTest(TestCase):
    """Code ikitumwa mara mbili (auto-submit + Enter) mtumiaji asitolewe nje."""

    def test_same_code_twice_keeps_user_signed_in(self):
        import time
        from django.contrib.auth.models import User
        from django.core.cache import cache
        from apps import two_factor as tf
        cache.clear()
        User.objects.create_user('boss3', 'b3@x.com', 'Sahihi-Kabisa-2026', is_staff=True)
        self.client.post('/manage/login/', {'username': 'boss3', 'password': 'Sahihi-Kabisa-2026'})
        self.client.get('/account/2fa/setup/')
        secret = self.client.session['staff_2fa_pending']
        now = int(time.time() // 30)
        self.client.post('/account/2fa/setup/', {'code': tf.totp_at(secret, now)})
        self.client.logout()
        self.client.post('/manage/login/', {'username': 'boss3', 'password': 'Sahihi-Kabisa-2026'})
        self.client.get('/manage/')
        code = tf.totp_at(secret, now + 1)
        from django.conf import settings as dj
        old_cookie = self.client.cookies[dj.SESSION_COOKIE_NAME].value
        r1 = self.client.post('/account/2fa/', {'code': code})
        # Ombi la pili lilitumwa KABLA jibu la kwanza halijafika: lina cookie ya zamani
        self.client.cookies[dj.SESSION_COOKIE_NAME] = old_cookie
        r2 = self.client.post('/account/2fa/', {'code': code})
        self.assertEqual(r1['Location'], '/manage/')
        self.assertEqual(r2['Location'], '/manage/')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/manage/').status_code, 200)
