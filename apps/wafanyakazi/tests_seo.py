import base64
import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import override_settings

from apps.models import BlogPost, WebsiteTemplate
from apps.seo import gsc

from . import actions, grace, seo
from .models import Alama, Kazi, SeoRipoti
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


@GSC
class AuditTest(Base):
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

    def _gsc(self, start, end, dimensions=('query', 'page'), **kw):
        """Search Console bandia: jibu kulingana na dimensions za ombi."""
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
