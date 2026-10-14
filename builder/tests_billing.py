"""Malipo ya Builder (builder/billing.py): template inayouzwa, Remove logo, "Made with JamiiTek"."""
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
        self.assertNotIn('jt-made-with', html)
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
    def test_free_site_publishes_free_and_shows_made_with_jamiitek(self):
        site = self.make_site(is_free=True)
        self.c.post(f'/builder/site/{site.id}/publish/')
        site.refresh_from_db()
        self.assertTrue(site.is_published)
        html = Client().get('/', HTTP_HOST=HOST).content.decode()
        self.assertIn('id="jt-made-with"', html)
        self.assertLess(html.index('jt-made-with'), html.lower().rindex('</body>'))
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
        self.assertNotIn('jt-made-with', Client().get('/', HTTP_HOST=HOST).content.decode())
        r = self.c.get(f'/builder/site/{site.id}/?paid=1')
        self.assertContains(r, 'Your website is online!')

    def test_old_free_sites_get_the_logo_only_from_the_chosen_date(self):
        site = self.make_site(is_free=True)
        ClientWebsite.objects.filter(pk=site.pk).update(legacy_free=True, is_published=True)
        html = lambda: Client().get('/', HTTP_HOST=HOST).content.decode()
        self.assertNotIn('jt-made-with', html())                        # tarehe haijawekwa
        soon = timezone.localdate() + timedelta(days=7)
        BuilderPricing.objects.update_or_create(pk=1, defaults={'badge_old_sites_from': soon})
        self.assertNotIn('jt-made-with', html())
        self.assertContains(self.c.get(f'/builder/site/{site.id}/'), 'free websites show')
        BuilderPricing.objects.filter(pk=1).update(badge_old_sites_from=timezone.localdate())
        self.assertIn('jt-made-with', html())

    def test_badge_notice_emails_each_owner_once(self):
        from django.core import mail
        from django.core.management import call_command
        site = self.make_site(is_free=True)
        ClientWebsite.objects.filter(pk=site.pk).update(legacy_free=True, is_published=True)
        BuilderPricing.objects.update_or_create(pk=1, defaults={
            'badge_old_sites_from': timezone.localdate() + timedelta(days=7), 'remove_logo_price': 30000})
        call_command('badge_notice', stdout=mock.MagicMock())
        call_command('badge_notice', stdout=mock.MagicMock())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('dukaletu.jamiitek.com', mail.outbox[0].body)
        self.assertIn('TSh 30,000', mail.outbox[0].body)
