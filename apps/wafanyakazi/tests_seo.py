import base64
import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import override_settings

from apps.models import BlogPost, WebsiteTemplate
from apps.seo import gsc

from . import actions, grace, seo
from .models import Alama, Kazi, SeoBadiliko, SeoRipoti
from .tests import Base


def _creds():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, {'type': 'service_account', 'client_email': 'seo@jt.iam.gserviceaccount.com',
                 'private_key': pem, 'private_key_id': 'abc'}


KEY, CREDS = _creds()
GSC = override_settings(GSC_SERVICE_ACCOUNT_JSON=json.dumps(CREDS), GSC_SITE_URL='sc-domain:jamiitek.com')


def row(query, page, impressions, clicks, position):
    return {'keys': [query, page], 'impressions': impressions, 'clicks': clicks,
            'ctr': clicks / impressions if impressions else 0, 'position': position}


class GscClientTest(Base):
    def test_not_configured_without_json(self):
        with override_settings(GSC_SERVICE_ACCOUNT_JSON=''):
            self.assertFalse(gsc.is_configured())
        with override_settings(GSC_SERVICE_ACCOUNT_JSON='{"client_email": "x"}'):
            self.assertFalse(gsc.is_configured())

    def test_base64_json_is_accepted(self):
        with override_settings(GSC_SERVICE_ACCOUNT_JSON=base64.b64encode(json.dumps(CREDS).encode()).decode()):
            self.assertEqual(gsc.credentials()['client_email'], CREDS['client_email'])

    @GSC
    def test_signed_jwt_verifies_and_query_uses_token(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        jwt = gsc._signed_jwt(CREDS, now=1_700_000_000)
        head, body, sig = jwt.split('.')
        pad = lambda s: s + '=' * (-len(s) % 4)  # noqa: E731
        claims = json.loads(base64.urlsafe_b64decode(pad(body)))
        self.assertEqual(claims['scope'], gsc.SCOPE)
        self.assertEqual(claims['iss'], CREDS['client_email'])
        KEY.public_key().verify(base64.urlsafe_b64decode(pad(sig)), f'{head}.{body}'.encode(),
                                padding.PKCS1v15(), hashes.SHA256())   # inatupa kosa kama si sahihi

        token = mock.Mock(status_code=200, json=lambda: {'access_token': 'tok', 'expires_in': 3600})
        data = mock.Mock(status_code=200, json=lambda: {'rows': [row('a', 'https://x/', 10, 1, 3)]})
        with mock.patch('apps.seo.gsc.requests.post', side_effect=[token, data]) as post:
            rows = gsc.query(date.today(), date.today())
        self.assertEqual(len(rows), 1)
        url = post.call_args_list[1].args[0]
        self.assertIn('sites/sc-domain%3Ajamiitek.com/searchAnalytics/query', url)
        self.assertEqual(post.call_args_list[1].kwargs['headers']['Authorization'], 'Bearer tok')

    @GSC
    def test_permission_error_is_explained(self):
        token = mock.Mock(status_code=200, json=lambda: {'access_token': 'tok', 'expires_in': 3600})
        denied = mock.Mock(status_code=403, text='forbidden')
        with mock.patch('apps.seo.gsc.requests.post', side_effect=[token, denied]):
            with self.assertRaisesRegex(gsc.GSCError, 'Users and permissions'):
                gsc.query(date.today(), date.today())


class AnalysisTest(Base):
    def test_opportunities_rank_pages_by_missed_clicks(self):
        rows = [
            row('website template tanzania', 'https://www.jamiitek.com/templates/', 900, 4, 3.2),   # CTR ndogo sana
            row('jamiitek', 'https://www.jamiitek.com/', 400, 120, 1.1),                          # iko sawa
            row('safari website', 'https://www.jamiitek.com/templates/savanna/', 200, 1, 11.0),   # karibu ukurasa 1
            row('rare words', 'https://www.jamiitek.com/x/', 5, 0, 4.0),                          # data chache
            row('far away', 'https://www.jamiitek.com/y/', 500, 0, 35.0),                         # mbali mno
        ]
        out = seo.opportunities(rows)
        self.assertEqual([o['page'] for o in out],
                         ['https://www.jamiitek.com/templates/', 'https://www.jamiitek.com/templates/savanna/'])
        self.assertEqual(out[0]['queries'][0]['kind'], 'ctr')
        self.assertEqual(out[1]['queries'][0]['kind'], 'karibu')

    def test_coverage_and_draft_parsing(self):
        cov = seo.coverage('restaurant website template', {'title': 'Restaurant Website Template',
                                                           'description': 'For cafés', 'text': 'menu'})
        self.assertEqual(cov['title'], 1.0)
        self.assertEqual(cov['description'], 0.0)
        self.assertEqual(seo.parse_draft('Kichwa: A\nMaelezo: B'), ('A', 'B'))
        self.assertEqual(seo.parse_draft('Title: "X"\nDescription: Y'), ('X', 'Y'))


class AuditBase(Base):
    """Data ya pamoja ya ukaguzi: template, makala, ukurasa wa code na Search Console bandia."""

    def setUp(self):
        super().setUp()
        SeoRipoti.objects.all().delete()
        self.ping = mock.patch('apps.indexnow.ping')
        self.pinged = self.ping.start()
        self.addCleanup(self.ping.stop)
        self.tpl = WebsiteTemplate.objects.create(name='Savanna Luxe', category='Tourism',
                                                  description='A safari website.', preview_html='<p>x</p>')
        self.post = BlogPost.objects.create(title='Bei ya website Tanzania', slug='bei-ya-website',
                                            excerpt='Bei.', body='<p>Maelezo ya bei.</p>', status='published')
        base = 'https://www.jamiitek.com'
        self.rows = [
            row('safari website template', f'{base}/templates/savanna-luxe/', 600, 2, 4.0),
            row('bei ya website tanzania', f'{base}/blog/bei-ya-website/', 300, 1, 6.0),
            row('web developer dar es salaam', f'{base}/service/', 250, 0, 12.0),
        ]

    def _gsc(self, start, end, dimensions=('query', 'page'), page=None, **kw):
        """Search Console bandia: jibu kulingana na dimensions za ombi."""
        if page:   # kupima ukurasa mmoja: kabla ya badiliko CTR ndogo, baada kubwa
            after = start > self.now.date()
            return [{'keys': ['2026-10-01'], 'clicks': 24 if after else 3, 'impressions': 600,
                     'ctr': 0, 'position': 5.0 if after else 6.0}]
        current = end >= self.now.date() - timedelta(days=seo.LAG_DAYS)
        if dimensions == ('date',):
            # Jumla halisi ni kubwa kuliko safu za query (maneno yaliyofichwa)
            return [{'keys': ['2026-10-01'], 'clicks': 40 if current else 25, 'impressions': 2000 if current else 1600,
                     'ctr': 0.02, 'position': 9.0}]
        if dimensions == ('page',):
            base = 'https://www.jamiitek.com'
            return ([{'keys': [f'{base}/'], 'clicks': 30 if current else 18, 'impressions': 900, 'ctr': 0, 'position': 3},
                     {'keys': [f'{base}/service/'], 'clicks': 2 if current else 7, 'impressions': 250, 'ctr': 0, 'position': 12}])
        return self.rows if current else []

    def _audit(self, now=None, prev=None):
        page = mock.Mock(status_code=200, text='<title>Services | JamiiTek</title>'
                         '<meta name="description" content="Websites and apps."><p>We build.</p>')
        with mock.patch('apps.seo.gsc.query', side_effect=self._gsc) as q, \
                mock.patch('apps.wafanyakazi.seo.requests.get', return_value=page):
            result = seo.audit(now or self.now)
        return result, q

@GSC
class AuditTest(AuditBase):
    def test_weekly_audit_creates_drafts_and_a_report(self):
        result, q = self._audit()
        self.assertIn('rasimu mpya 3', result['seo'])
        start, end = q.call_args_list[0].args
        self.assertEqual(end, self.now.date() - timedelta(days=seo.LAG_DAYS))
        self.assertEqual((end - start).days, seo.DAYS - 1)

        drafts = Kazi.objects.filter(worker='grace', channel='seo')
        self.assertEqual(drafts.count(), 3)
        for kazi in drafts:
            self.assertEqual(kazi.status, Kazi.AWAITING)
            self.assertIn('Title:', kazi.draft)
            self.assertIn('Description:', kazi.draft)
        self.assertEqual({k.ref for k in drafts}, {f'template:{self.tpl.pk}', f'blog:{self.post.pk}', 'page:/service/'})
        tpl_kazi = drafts.get(ref=f'template:{self.tpl.pk}')
        self.assertIn('safari website template', tpl_kazi.detail)
        self.assertIn('ipo kila mahali', tpl_kazi.detail)          # template_seo tayari inayatumia
        page_kazi = drafts.get(ref='page:/service/')
        self.assertIn('Services | JamiiTek', page_kazi.detail)     # kichwa halisi cha ukurasa
        self.assertIn('haionekani kwenye kichwa, maelezo, maandishi', page_kazi.detail)

        report = SeoRipoti.objects.get()
        # Jumla zinatoka kwa tarehe — si kwa query×page (Google huficha maneno adimu)
        self.assertEqual(report.totals['clicks'], 40)
        self.assertEqual(report.totals['impressions'], 2000)
        self.assertEqual(report.previous['clicks'], 25)
        self.assertEqual(report.movers['up'][0]['page'], 'https://www.jamiitek.com/')
        self.assertEqual(report.movers['up'][0]['change'], 12)
        self.assertEqual(report.movers['down'][0]['change'], -5)
        self.assertEqual(len(report.opportunities), 3)

        # Wiki hiyo hiyo: hakuna ukaguzi wa pili
        again, q2 = self._audit(now=self.now + timedelta(hours=2))
        self.assertEqual(again['seo'], 'tayari wiki hii')
        q2.assert_not_called()

    def test_approving_applies_title_and_pings_search_engines(self):
        self._audit()
        tpl_kazi = Kazi.objects.get(ref=f'template:{self.tpl.pk}')
        ok, msg = actions.approve(tpl_kazi.pk, draft='Title: Safari Website Template — Savanna Luxe\n'
                                                     'Description: A premium safari website template.')
        self.assertTrue(ok, msg)
        self.tpl.refresh_from_db()
        self.assertEqual(self.tpl.seo_title, 'Safari Website Template — Savanna Luxe')
        self.assertEqual(self.tpl.seo_description, 'A premium safari website template.')
        self.pinged.assert_called()

        blog_kazi = Kazi.objects.get(ref=f'blog:{self.post.pk}')
        actions.approve(blog_kazi.pk, draft='Title: Bei ya Website Tanzania 2026\nDescription: Bei halisi.')
        self.post.refresh_from_db()
        self.assertEqual(self.post.meta_title, 'Bei ya Website Tanzania 2026')

        page_kazi = Kazi.objects.get(ref='page:/service/')
        ok, msg = actions.approve(page_kazi.pk)
        self.assertTrue(ok)
        self.assertIn('kwenye code', msg)
        page_kazi.refresh_from_db()
        self.assertEqual(page_kazi.status, Kazi.DONE)

    def test_pages_changed_recently_wait_for_google(self):
        self._audit()
        tpl_kazi = Kazi.objects.get(ref=f'template:{self.tpl.pk}')
        actions.approve(tpl_kazi.pk)
        Alama.put('seo:week', '')                                   # wiki ijayo
        self._audit(now=self.now + timedelta(days=7))
        self.assertEqual(Kazi.objects.filter(ref=f'template:{self.tpl.pk}').count(), 1)
        report = SeoRipoti.objects.order_by('-start').first()
        statuses = {o['path']: o['status'] for o in report.opportunities}
        self.assertEqual(statuses['/templates/savanna-luxe/'], 'inasubiri')

    def test_gsc_error_is_saved_not_raised(self):
        with mock.patch('apps.seo.gsc.query', side_effect=gsc.GSCError('Hakuna ruhusa')):
            result = seo.run(self.now)
        self.assertIn('Hakuna ruhusa', result['seo'])
        self.assertEqual(SeoRipoti.objects.get().error, 'Hakuna ruhusa')

    def test_grace_keeps_seo_drafts_when_old_posts_expire(self):
        self._audit()
        later = self.now + timedelta(days=4)
        with mock.patch('apps.wafanyakazi.seo.audit', return_value={'seo': 'tayari wiki hii'}):
            grace.run(later)
        self.assertEqual(Kazi.objects.filter(channel='seo', status=Kazi.AWAITING).count(), 3)

    def test_report_page(self):
        self.client.force_login(User.objects.create_user('boss', 'b@example.com', 'p', is_staff=True))
        self._audit()
        r = self.client.get('/manage/seo/')
        self.assertContains(r, 'Fursa — mibofyo inayopotea')
        self.assertContains(r, '/templates/savanna-luxe/')
        self.assertContains(r, 'Rasimu mezani')
        d = self.client.get('/manage/wafanyakazi/?w=grace')
        self.assertContains(d, 'Kubali — weka kwenye tovuti')


class NotConfiguredTest(Base):
    def test_audit_skips_and_page_shows_setup_steps(self):
        with override_settings(GSC_SERVICE_ACCOUNT_JSON=''), mock.patch('apps.seo.gsc.query') as q:
            self.assertEqual(seo.audit(self.now)['seo'], 'Search Console haijaunganishwa')
            q.assert_not_called()
            self.client.force_login(User.objects.create_user('boss', 'b@example.com', 'p', is_staff=True))
            r = self.client.get('/manage/seo/')
        self.assertContains(r, 'Unganisha Google Search Console')
        self.assertContains(r, 'GSC_SERVICE_ACCOUNT_JSON')



@GSC
class SmarterGraceTest(AuditBase):
    """Maboresho: makala inasomwa, madai yasiyo kwenye ukurasa, biashara kwanza, matokeo."""

    def test_ai_reads_the_page_and_invented_claims_are_flagged(self):
        snap = {'title': 'Koko Networks wind-down', 'description': 'Creditors take over.',
                'text': 'Koko Networks UK put its carbon credits up for sale but found no buyers. '
                        'Creditors are now winding down the company.'}
        queries = [{'query': 'koko networks carbon credit sale', 'impressions': 1003, 'clicks': 0,
                    'position': 7.7}]
        with mock.patch('apps.wafanyakazi.ai.write',
                        return_value='Title: Koko Networks Carbon Credit Sale Finds No Buyers\n'
                                     'Description: Koko Networks UK carbon credits found no buyers.') as w:
            draft, risky = seo.draft_for(snap, queries)
        prompt = w.call_args.args[1]
        self.assertIn('found no buyers', prompt)                  # AI inaona maudhui
        self.assertIn('usiongeze madai', prompt)
        self.assertIn('Koko Networks Carbon Credit Sale Finds No Buyers', draft)
        self.assertEqual(risky, ['finds'] if 'finds' not in snap['text'] else [])

        with mock.patch('apps.wafanyakazi.ai.write',
                        return_value='Title: Koko Networks Bankruptcy Shocks Kenyan Investors Worldwide\n'
                                     'Description: Billions lost overnight.'):
            draft, risky = seo.draft_for(snap, queries)
        self.assertNotIn('Bankruptcy', draft)                     # mengi mno ya kubuni → toleo salama
        self.assertIn('Koko networks carbon credit sale', draft)

    def test_business_pages_come_before_news(self):
        news = BlogPost.objects.create(title='Koko Networks', slug='koko', excerpt='Habari.', body='<p>x</p>',
                                       status='published', is_news=True)
        self.rows.append(row('koko networks carbon credit sale', 'https://www.jamiitek.com/blog/koko/',
                             1003, 0, 7.7))
        self._audit()
        report = SeoRipoti.objects.get()
        paths = [o['path'] for o in report.opportunities]
        self.assertGreater(paths.index('/blog/koko/'), paths.index('/templates/savanna-luxe/'))
        koko = next(o for o in report.opportunities if o['path'] == '/blog/koko/')
        self.assertEqual(koko['type'], 'habari')
        kazi = Kazi.objects.get(ref=f'blog:{news.pk}')
        self.assertIn('makala ya habari', kazi.detail)

    def test_results_are_measured_before_and_after(self):
        self._audit()
        kazi = Kazi.objects.get(ref=f'template:{self.tpl.pk}')
        actions.approve(kazi.pk, draft='Title: Safari Website Template\nDescription: Premium safari site.')
        change = SeoBadiliko.objects.get()
        self.assertEqual(change.page, 'https://www.jamiitek.com/templates/savanna-luxe/')
        self.assertEqual(change.new_title, 'Safari Website Template')
        self.assertTrue(change.old_title)
        self.assertEqual(change.verdict[0], 'inasubiri')

        with mock.patch('apps.seo.gsc.query', side_effect=self._gsc):
            seo.measure(self.now + timedelta(days=7))           # mapema: "kabla" tu
        change.refresh_from_db()
        self.assertEqual(change.before['clicks'], 3)
        self.assertEqual(change.after, {})

        with mock.patch('apps.seo.gsc.query', side_effect=self._gsc):
            seo.measure(self.now + timedelta(days=40))
        change.refresh_from_db()
        self.assertEqual(change.after['clicks'], 24)
        self.assertEqual(change.verdict[0], 'imeboreka')

        self.client.force_login(User.objects.create_user('boss2', 'b2@example.com', 'p', is_staff=True))
        r = self.client.get('/manage/seo/')
        self.assertContains(r, 'Matokeo ya mabadiliko')
        self.assertContains(r, 'Imeboreka')


class GracePostTest(Base):
    def test_post_rotates_angles_avoids_repeats_and_has_whatsapp(self):
        Kazi.objects.create(worker='grace', key='grace:post:old', channel='social', status=Kazi.SENT,
                            title='Post', draft='Je, wateja wanakupata Google?\nMaelezo…')
        with mock.patch('apps.wafanyakazi.ai.write', return_value='Post mpya') as w:
            grace._caption('JamiiBot inajibu wateja WhatsApp.', 'https://www.jamiitek.com/bot/', day=0)
            first = w.call_args.args[1]
            grace._caption('JamiiBot inajibu wateja WhatsApp.', 'https://www.jamiitek.com/bot/', day=1)
            second = w.call_args.args[1]
        self.assertIn('TATIZO', first)
        self.assertIn('MATOKEO', second)
        self.assertIn('Je, wateja wanakupata Google?', first)   # isirudie mwanzo wa karibuni
        self.assertIn('wa.me/255629712678', first)
        self.assertIn('LinkedIn', first)
        with mock.patch('apps.wafanyakazi.ai.write', return_value=''):
            fallback = grace._caption('Huduma za JamiiTek.', 'https://www.jamiitek.com/service/')
        self.assertIn('wa.me/255629712678', fallback)


class TemplateDescriptionTest(Base):
    """Grace anaandika maelezo ya kipekee ya templates (long_description) — rasimu 2 kwa siku."""

    def setUp(self):
        super().setUp()
        p = mock.patch('apps.indexnow.ping')
        self.pinged = p.start()
        self.addCleanup(p.stop)
        demo = ('<html><body><h1>Wild Heritage Expeditions</h1><h2>Serengeti Migration Safaris</h2>'
                '<h2>Kilimanjaro Treks</h2><p>Small-group safaris with expert guides.</p>'
                '<script>var x=1</script></body></html>')
        self.tpls = [WebsiteTemplate.objects.create(name=f'Wild Heritage {i}', category='Tourism',
                                                    description='Safari company website.', preview_html=demo)
                     for i in range(3)]
        self.done = WebsiteTemplate.objects.create(name='Done', category='Tourism', description='x',
                                                   preview_html='<p>x</p>', long_description='x' * 400)
        self.text = ('Wild Heritage Expeditions is a safari website template built around Serengeti '
                     'Migration Safaris and Kilimanjaro Treks, with a bold hero and small-group tours.\n\n'
                     'Each section is ready for a tour operator to list itineraries, guides and departure '
                     'dates, so travellers can plan a safari and contact you directly from any phone.')

    def test_drafts_two_per_day_from_the_real_demo(self):
        from . import maelezo
        with mock.patch('apps.wafanyakazi.ai.write', return_value=self.text) as w:
            result = maelezo.run(self.now)
        self.assertEqual(result['maelezo'], 'rasimu mpya 2')
        prompt = w.call_args.args[1]
        self.assertIn('Serengeti Migration Safaris', prompt)        # vichwa vya demo
        self.assertNotIn('var x=1', prompt)                          # script haisomwi
        self.assertIn('Usibuni bei', prompt)
        drafts = Kazi.objects.filter(ref__startswith='tpldesc:')
        self.assertEqual(drafts.count(), 2)
        self.assertFalse(drafts.filter(ref=f'tpldesc:{self.done.pk}').exists())   # tayari ina maelezo
        self.assertEqual(drafts.first().status, Kazi.AWAITING)

        with mock.patch('apps.wafanyakazi.ai.write', return_value=self.text):
            self.assertEqual(maelezo.run(self.now)['maelezo'], 'rasimu mpya 0')    # siku hiyo hiyo

    def test_no_ai_no_generic_draft(self):
        from . import maelezo
        with mock.patch('apps.wafanyakazi.ai.write', return_value=''):
            self.assertEqual(maelezo.run(self.now)['maelezo'], 'rasimu mpya 0')
        self.assertFalse(Kazi.objects.filter(ref__startswith='tpldesc:').exists())

    def test_approving_puts_text_on_the_template_page(self):
        from . import maelezo
        with mock.patch('apps.wafanyakazi.ai.write', return_value=self.text):
            maelezo.run(self.now)
        kazi = Kazi.objects.filter(ref__startswith='tpldesc:').first()
        ok, msg = actions.approve(kazi.pk)
        self.assertTrue(ok, msg)
        tpl = WebsiteTemplate.objects.get(pk=kazi.ref.split(':')[1])
        self.assertEqual(tpl.long_description, self.text)
        self.pinged.assert_called()
        self.assertContains(self.client.get(tpl.get_absolute_url()), 'Kilimanjaro Treks, with a bold hero')

        # Iliyokataliwa hairudi
        other = Kazi.objects.filter(ref__startswith='tpldesc:').exclude(pk=kazi.pk).first()
        actions.dismiss(other.pk)
        later = self.now + timedelta(days=1)
        with mock.patch('apps.wafanyakazi.ai.write', return_value=self.text):
            maelezo.run(later)
        self.assertEqual(Kazi.objects.filter(ref=other.ref).count(), 1)

    def test_desk_explains_the_draft(self):
        from . import maelezo
        with mock.patch('apps.wafanyakazi.ai.write', return_value=self.text):
            maelezo.run(self.now)
        self.client.force_login(User.objects.create_user('boss', 'b@example.com', 'p', is_staff=True))
        r = self.client.get('/manage/wafanyakazi/?w=grace')
        self.assertContains(r, 'Maelezo ya kipekee: Wild Heritage')
        self.assertContains(r, 'Google isiuone ukurasa wake kama nakala')
