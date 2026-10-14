"""Malipo ya Builder (builder/billing.py): template inayouzwa, Remove logo, "Developed by JamiiTek"."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from apps.models import WebsiteTemplate
from apps.pesapal_fulfill import fulfill
from apps.pesapal_models import PesapalTransaction
from builder.models import BuilderPricing, ClientWebsite
from builder.template_bridge import create_site_from_template

HOST = 'dukaletu.jamiitek.com'
DOC = '<!doctype html><html><head><title>Duka</title></head><body><section><h1>Karibu Duka</h1></section></body></html>'


def _pesapal():
    client = mock.MagicMock()
    client.configured = True
    client.get_ipn_id.return_value = 'ipn-1'
    client.submit_order.return_value = {'order_tracking_id': 'trk-1', 'redirect_url': 'https://pay.pesapal.test/x'}
    return mock.patch('apps.pesapal_views.PesapalClient', return_value=client)


class BillingBase(TestCase):
    def setUp(self):
        ping = mock.patch('apps.indexnow.ping')
        ping.start()
        self.addCleanup(ping.stop)
        self.user = User.objects.create_user('mteja', email='mteja@example.com', password='Siri#123456')
        self.c = Client()
        self.c.force_login(self.user)

    def make_site(self, **tpl_kw):
        data = dict(name='Duka Glass', category='shop', description='Shop.', preview_html=DOC)
        data.update(tpl_kw)
        self.tpl = WebsiteTemplate.objects.create(**data)
        site, _ = create_site_from_template(self.user, self.tpl, 'Duka Letu', 'dukaletu')
        ts = dict(site.theme_settings)
        ts['studio_done'] = ['business', 'pages']          # Studio imekamilika — iko tayari kuchapishwa
        site.theme_settings = ts
        site.save()
        return site

    def pay(self, site, kind):
        with _pesapal():
            r = self.c.post(f'/builder/site/{site.id}/pay/{kind}/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://pay.pesapal.test/x')
        tx = PesapalTransaction.objects.get(target_id=str(site.pk))
        tx.status = 'completed'
        tx.save()
        with mock.patch('apps.pesapal_receipt.issue_receipt'):
            with self.captureOnCommitCallbacks(execute=True):
                fulfill(tx)
        site.refresh_from_db()
        return tx


class PaidTemplateTest(BillingBase):
    def test_publish_goes_to_checkout_then_payment_puts_site_online(self):
        site = self.make_site(price=80000)
        r = self.c.post(f'/builder/site/{site.id}/publish/')
        self.assertRedirects(r, f'/builder/site/{site.id}/pay/template/', fetch_redirect_response=False)
        site.refresh_from_db()
        self.assertFalse(site.is_published)                  # haiendi hewani bila kulipa

        page = self.c.get(f'/builder/site/{site.id}/pay/template/').content.decode()
        self.assertIn('TSh 80,000', page)
        self.assertIn('Pay now', page)

        tx = self.pay(site, 'template')
        self.assertEqual((tx.purpose, tx.amount, tx.plan_id), ('builder_template', 80000, self.tpl.pk))
        self.assertTrue(tx.merchant_reference.startswith('JT-TPL-'))
        self.assertTrue(site.is_published)
        self.assertTrue(site.is_premium)
        self.assertEqual(site.paid_template_id, self.tpl.pk)
        self.assertEqual(site.hosting_until, timezone.localdate() + timedelta(days=365))
        # Imelipiwa: hakuna alama, na Publish haitaki malipo tena
        html = Client().get('/', HTTP_HOST=HOST).content.decode()
        self.assertIn('Karibu Duka', html)
        self.assertNotIn('jamiitek-badge', html)                    # imelipiwa: hakuna "Developed by JamiiTek"
        self.assertNotContains(self.c.get(f'/builder/site/{site.id}/'), 'Pay now')

    def test_amount_comes_from_the_server_not_the_form(self):
        site = self.make_site(price=80000)
        with _pesapal():
            self.c.post(f'/builder/site/{site.id}/pay/template/', {'amount': '1'})
        self.assertEqual(PesapalTransaction.objects.get().amount, 80000)

    def test_studio_publish_sends_to_payment(self):
        site = self.make_site(price=80000)
        r = self.c.post(f'/builder/site/{site.id}/studio/publish/', HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()['pay_url'], f'/builder/site/{site.id}/pay/template/')

    def test_someone_else_cannot_pay_or_see_checkout(self):
        site = self.make_site(price=80000)
        User.objects.create_user('mwingine', password='Siri#123456')
        other = Client()
        other.login(username='mwingine', password='Siri#123456')
        self.assertEqual(other.get(f'/builder/site/{site.id}/pay/template/').status_code, 404)

    def test_paying_for_a_deleted_site_alerts_jamiitek(self):
        site = self.make_site(price=80000)
        with _pesapal():
            self.c.post(f'/builder/site/{site.id}/pay/template/')
        tx = PesapalTransaction.objects.get()
        site.delete()
        tx.status = 'completed'
        tx.save()
        with mock.patch('apps.pesapal_receipt.issue_receipt'), mock.patch('apps.notify.notify') as notify:
            with self.captureOnCommitCallbacks(execute=True):
                fulfill(tx)
        self.assertIn('MALIPO BILA HUDUMA', notify.call_args[0][0])


class FreeTemplateTest(BillingBase):
    def test_free_site_publishes_free_and_shows_developed_by_jamiitek(self):
        site = self.make_site(is_free=True)
        self.c.post(f'/builder/site/{site.id}/publish/')
        site.refresh_from_db()
        self.assertTrue(site.is_published)
        html = Client().get('/', HTTP_HOST=HOST).content.decode()
        self.assertEqual(html.count('<jamiitek-badge'), 1)          # alama MOJA tu
        self.assertLess(html.index('<jamiitek-badge'), html.lower().rindex('</body>'))
        # Bei ya "Remove logo" haijawekwa → hakuna kitufe wala ukurasa wa malipo
        self.assertNotContains(self.c.get(f'/builder/site/{site.id}/'), 'Remove logo')
        self.assertEqual(self.c.get(f'/builder/site/{site.id}/pay/logo/').status_code, 302)

    def test_remove_logo_payment(self):
        BuilderPricing.objects.update_or_create(pk=1, defaults={'remove_logo_price': 30000})
        site = self.make_site(is_free=True)
        self.c.post(f'/builder/site/{site.id}/publish/')
        self.assertContains(self.c.get(f'/builder/site/{site.id}/'), 'Remove logo')
        tx = self.pay(site, 'logo')
        self.assertEqual((tx.purpose, tx.amount), ('builder_logo', 30000))
        self.assertTrue(site.is_premium)
        self.assertNotIn('jamiitek-badge', Client().get('/', HTTP_HOST=HOST).content.decode())
        r = self.c.get(f'/builder/site/{site.id}/?paid=1')
        self.assertContains(r, 'Your website is online!')

    def test_studio_preview_matches_the_live_site(self):
        site = self.make_site(is_free=True)
        self.assertContains(self.c.get(f'/builder/site/{site.id}/studio/preview/'), '<jamiitek-badge')
        ClientWebsite.objects.filter(pk=site.pk).update(is_premium=True)
        self.assertNotContains(self.c.get(f'/builder/site/{site.id}/studio/preview/'), '<jamiitek-badge')


class HostingRenewalTest(BillingBase):
    def setUp(self):
        super().setUp()
        BuilderPricing.objects.update_or_create(pk=1, defaults={'yearly_hosting_price': 40000})

    def bought_site(self, days_left):
        site = self.make_site(price=80000)
        self.pay(site, 'template')
        ClientWebsite.objects.filter(pk=site.pk).update(
            hosting_until=timezone.localdate() + timedelta(days=days_left))
        site.refresh_from_db()
        return site

    def test_reminders_are_sent_once_on_the_right_days(self):
        from django.core import mail
        from django.core.management import call_command
        site = self.bought_site(7)
        call_command('builder_hosting', stdout=mock.MagicMock())
        call_command('builder_hosting', stdout=mock.MagicMock())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('in 7 days', mail.outbox[0].subject)
        self.assertIn(f'/builder/site/{site.id}/pay/renew/', mail.outbox[0].body)
        self.assertIn('TSh 40,000', mail.outbox[0].body)
        ClientWebsite.objects.filter(pk=site.pk).update(hosting_until=timezone.localdate() + timedelta(days=12))
        call_command('builder_hosting', stdout=mock.MagicMock())   # siku 12 — si siku ya ukumbusho
        self.assertEqual(len(mail.outbox), 1)

    def test_unpaid_bought_site_pauses_after_grace_and_renewal_brings_it_back(self):
        site = self.bought_site(-3)                    # ndani ya siku 7 za ziada — bado iko hewani
        self.assertContains(Client().get('/', HTTP_HOST=HOST), 'Karibu Duka')
        self.assertContains(self.c.get(f'/builder/site/{site.id}/'), 'Your hosting has ended')
        ClientWebsite.objects.filter(pk=site.pk).update(hosting_until=timezone.localdate() - timedelta(days=8))
        r = Client().get('/', HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 503)
        self.assertNotContains(r, 'Karibu Duka', status_code=503)
        self.assertContains(self.c.get(f'/builder/site/{site.id}/'), 'Your website is paused')

        PesapalTransaction.objects.all().delete()
        tx = self.pay(site, 'renew')
        self.assertEqual((tx.purpose, tx.amount), ('builder_renew', 40000))
        self.assertTrue(tx.merchant_reference.startswith('JT-RNW-'))
        self.assertEqual(site.hosting_until, timezone.localdate() + timedelta(days=365))
        self.assertContains(Client().get('/', HTTP_HOST=HOST), 'Karibu Duka')

    def test_early_renewal_adds_a_year_to_the_end_date(self):
        site = self.bought_site(20)
        end = site.hosting_until
        PesapalTransaction.objects.all().delete()
        self.pay(site, 'renew')
        self.assertEqual(site.hosting_until, end + timedelta(days=365))

    def test_unpaid_remove_logo_goes_back_to_free(self):
        from django.core.management import call_command
        BuilderPricing.objects.filter(pk=1).update(remove_logo_price=30000)
        site = self.make_site(is_free=True)
        self.c.post(f'/builder/site/{site.id}/publish/')
        self.pay(site, 'logo')
        ClientWebsite.objects.filter(pk=site.pk).update(hosting_until=timezone.localdate() - timedelta(days=8))
        call_command('builder_hosting', stdout=mock.MagicMock())
        site.refresh_from_db()
        self.assertFalse(site.is_premium)
        html = Client().get('/', HTTP_HOST=HOST)
        self.assertEqual(html.status_code, 200)                       # haisimami — logo inarudi tu
        self.assertContains(html, '<jamiitek-badge')

    def test_no_yearly_price_means_hosting_never_ends(self):
        BuilderPricing.objects.filter(pk=1).update(yearly_hosting_price=0)
        site = self.bought_site(-30)
        self.assertEqual(Client().get('/', HTTP_HOST=HOST).status_code, 200)
        self.assertEqual(self.c.get(f'/builder/site/{site.id}/pay/renew/').status_code, 302)


class BuildForMeTest(TestCase):
    """ "Unahitaji tukutengenezee?" — builder/build_request.py """
    def setUp(self):
        ping = mock.patch('apps.indexnow.ping')
        ping.start()
        self.addCleanup(ping.stop)
        from django.core.cache import cache
        cache.clear()
        self.tpl = WebsiteTemplate.objects.create(name='Duka Glass', category='shop', description='Shop.',
                                                  preview_html=DOC, price=80000)
        self.url = f'/templates/{self.tpl.slug}/build-for-me/'
        self.data = {'business_name': 'Duka Letu', 'name': 'Asha Juma', 'phone': '0712 345 678',
                     'email': 'asha@example.com', 'about': 'We sell phones in Kariakoo.'}

    def test_without_a_fee_the_button_still_goes_to_the_proposal(self):
        r = self.client.get(self.url)
        self.assertRedirects(r, f'/proposals/?template={self.tpl.pk}', fetch_redirect_response=False)
        self.assertContains(self.client.get(self.tpl.get_absolute_url()), f'/proposals/?template={self.tpl.pk}')

    def test_pay_template_price_plus_fee_then_team_is_told(self):
        from django.core import mail
        from builder.models import BuildRequest
        BuilderPricing.objects.update_or_create(pk=1, defaults={'build_fee': 100000})
        self.assertContains(self.client.get(self.tpl.get_absolute_url()), self.url)
        page = self.client.get(self.url)
        self.assertContains(page, 'Unahitaji tukutengenezee?')
        self.assertContains(page, 'TSh 180,000')

        with _pesapal():
            r = self.client.post(self.url, self.data)
        self.assertEqual(r['Location'], 'https://pay.pesapal.test/x')
        br = BuildRequest.objects.get()
        tx = PesapalTransaction.objects.get()
        self.assertEqual((br.status, br.amount, br.template_price, br.build_fee), ('new', 180000, 80000, 100000))
        self.assertEqual((tx.purpose, tx.target_id, tx.amount), ('build_request', br.token, 180000))
        self.assertTrue(tx.merchant_reference.startswith('JT-BLD-'))
        self.assertContains(self.client.get(f'/build/{br.token}/'), 'Waiting for your payment')

        tx.status = 'completed'
        tx.save()
        with mock.patch('apps.pesapal_receipt.issue_receipt'), mock.patch('apps.notify.notify') as notify:
            with self.captureOnCommitCallbacks(execute=True):
                fulfill(tx)
        br.refresh_from_db()
        self.assertEqual(br.status, 'paid')
        self.assertIn('Duka Letu', notify.call_args[0][0])
        self.assertIn('0712 345 678', notify.call_args[0][0])
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(self.client.get(f'/build/{br.token}/'), 'Payment received')

    def test_free_design_pays_only_the_fee(self):
        BuilderPricing.objects.update_or_create(pk=1, defaults={'build_fee': 100000})
        WebsiteTemplate.objects.filter(pk=self.tpl.pk).update(is_free=True)
        with _pesapal():
            self.client.post(self.url, self.data)
        self.assertEqual(PesapalTransaction.objects.get().amount, 100000)

    def test_bad_phone_and_too_many_requests(self):
        from builder.models import BuildRequest
        BuilderPricing.objects.update_or_create(pk=1, defaults={'build_fee': 100000})
        r = self.client.post(self.url, dict(self.data, phone='12'))
        self.assertContains(r, 'phone number')
        self.assertFalse(BuildRequest.objects.exists())
        with _pesapal():
            for _ in range(5):
                self.client.post(self.url, self.data)
            r = self.client.post(self.url, self.data)
        self.assertContains(r, 'Too many requests')
        self.assertEqual(BuildRequest.objects.count(), 4)        # ya kwanza (simu mbaya) ilihesabiwa pia
