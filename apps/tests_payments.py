"""Majaribio ya malipo — kila moja ni bug iliyopatikana na kurekebishwa.

Pesapal inaigwa (hakuna mtandao). Kila jaribio linathibitisha tabia ambayo
awali ilikuwa mbaya; kwenye code ya zamani, yanashindwa.
"""
import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client as TC, TestCase, SimpleTestCase
from django.utils import timezone

from apps import pesapal_client as pc
from apps.chatbot.billing import clean_months, parse_amount
from apps.pesapal_models import PesapalTransaction

H = {'HTTP_HOST': 'jamiitek.com'}


def _pesapal(test, status_code=1):
    """Iga Pesapal kwa jaribio zima."""
    n = [0]

    def submit_order(self, **kw):
        n[0] += 1
        return {'order_tracking_id': f'TRK{n[0]}', 'redirect_url': f'https://pay.test/{n[0]}'}

    patches = [
        mock.patch.object(pc.PesapalClient, 'configured', new_callable=mock.PropertyMock, return_value=True),
        mock.patch.object(pc.PesapalClient, 'get_ipn_id', return_value='ipn'),
        mock.patch.object(pc.PesapalClient, 'submit_order', submit_order),
        mock.patch.object(pc.PesapalClient, 'get_status',
                          lambda self, t: {'status_code': status_code, 'payment_method': 'M-Pesa',
                                           'confirmation_code': 'MP' + t}),
    ]
    for p in patches:
        p.start()
        test.addCleanup(p.stop)


def _pay(client, tx):
    """Mteja anarudi kutoka Pesapal."""
    return client.get(f'/pay/callback/?OrderTrackingId={tx.order_tracking_id}', **H)


class ParsingTest(SimpleTestCase):
    def test_months(self):
        self.assertEqual([clean_months(x) for x in ('3', 6, '12', ' 1 ')], [3, 6, 12, 1])
        # 'abc' ilileta Server Error; '500' iliunda agizo la TZS 25,000,000
        self.assertEqual([clean_months(x) for x in ('abc', '0', '-5', '500', None, '2')], [1] * 6)

    def test_amount(self):
        # "15,000" ilileta Server Error kwenye fomu ya mteja
        for raw in ('15,000', '15000', 'TZS 15,000', '15 000', '15000.00'):
            self.assertEqual(parse_amount(raw), 15000, raw)
        for raw in ('', 'abc', '0', None, '1.2.3'):
            self.assertIsNone(parse_amount(raw), raw)


class HostingPaymentTest(TestCase):
    def setUp(self):
        from apps.models import Client, ManagedWebsite
        _pesapal(self)
        self.today = timezone.now().date()
        self.user = User.objects.create_user('ben', 'b@x.com', 'p')
        self.client_obj = Client.objects.create(user=self.user, name='Benon', email='b@x.com')
        self.site = ManagedWebsite.objects.create(
            client=self.client_obj, name='Mbossai', url='https://x.co.tz', status='active',
            monthly_cost=50000, hosting_start_date=self.today - datetime.timedelta(days=300),
            hosting_end_date=self.today + datetime.timedelta(days=5))
        self.c = TC()
        self.c.force_login(self.user)

    def test_bad_months_never_crash_or_inflate(self):
        for m in ('abc', '500', '-3'):
            r = self.c.post(f'/pay/hosting/{self.site.pk}/', {'months': m}, **H)
            self.assertEqual(r.status_code, 302, m)
            tx = PesapalTransaction.objects.latest('pk')
            self.assertEqual((tx.months, float(tx.amount)), (1, 50000.0), m)

    def test_paid_hosting_extends_from_old_end_date(self):
        self.c.post(f'/pay/hosting/{self.site.pk}/', {'months': '3'}, **H)
        tx = PesapalTransaction.objects.latest('pk')
        _pay(self.c, tx)
        self.site.refresh_from_db()
        from dateutil.relativedelta import relativedelta
        self.assertEqual(self.site.hosting_end_date,
                         self.today + datetime.timedelta(days=5) + relativedelta(months=3))

    def test_staff_recording_same_ref_twice_extends_once(self):
        from apps.models import HostingPayment
        staff = TC()
        staff.force_login(User.objects.create_superuser('w', 'w@x.com', 'x'))
        form = {'amount': '50,000', 'payment_date': str(self.today), 'months_covered': '1',
                'payment_method': 'M-Pesa', 'transaction_ref': 'QWE1', 'extend_hosting': 'on'}
        staff.post(f'/manage/websites/{self.site.pk}/payments/add/', form, **H)
        self.site.refresh_from_db()
        first = self.site.hosting_end_date
        staff.post(f'/manage/websites/{self.site.pk}/payments/add/', form, **H)
        self.site.refresh_from_db()
        self.assertEqual(self.site.hosting_end_date, first)
        self.assertEqual(HostingPayment.objects.filter(website=self.site).count(), 1)


class BotSubscriptionPaymentTest(TestCase):
    def setUp(self):
        from apps.chatbot.models import (BotConfig, BotSubscription, ChatbotClient, SubscriptionPlan)
        _pesapal(self)
        self.today = timezone.now().date()
        # Mipango inaundwa na migration — tumia iliyopo (nafuu zaidi / ghali zaidi)
        plans = list(SubscriptionPlan.objects.filter(is_active=True).order_by('price_tzs'))
        self.starter, self.enterprise = plans[0], plans[-1]
        self.user = User.objects.create_user('duka', 'd@x.com', 'p')
        cl = ChatbotClient.objects.create(user=self.user, full_name='Mama Duka', business_name='Duka', email='d@x.com')
        self.bot = BotConfig.objects.create(client=cl, bot_name='DukaBot', business_name='Duka',
                                            status='suspended', is_active=False)
        self.sub = BotSubscription.objects.create(bot=self.bot, plan=self.starter, status='trial',
                                                  end_date=self.today - datetime.timedelta(days=20))
        self.sub.messages_used = 5000
        self.sub.save()
        self.c = TC()
        self.c.force_login(self.user)

    def test_pesapal_applies_the_plan_paid_for(self):
        """Awali: amelipia Enterprise, akabaki Starter — bot ikasimama kwenye jumbe 5,000."""
        self.c.post('/pay/subscription/', {'plan_id': self.enterprise.pk, 'months': '1'}, **H)
        tx = PesapalTransaction.objects.latest('pk')
        self.assertEqual(float(tx.amount), float(self.enterprise.price_tzs))
        _pay(self.c, tx)
        self.sub.refresh_from_db()
        self.bot.refresh_from_db()
        self.assertEqual(self.sub.plan, self.enterprise)
        self.assertEqual(self.sub.messages_used, 0)
        self.assertEqual(self.bot.status, 'active')

    def test_manual_payment_with_comma_and_duplicate_ref(self):
        from apps.chatbot.models import SubscriptionPayment
        price = f'{int(self.enterprise.price_tzs):,}'      # mf. "15,000" — na koma
        form = {'transaction_ref': 'MPX1', 'amount': price, 'months': '1', 'plan_id': self.enterprise.pk}
        r = self.c.post('/chatbot/billing/', form, **H)
        self.assertEqual(r.status_code, 302)               # si Server Error
        self.c.post('/chatbot/billing/', form, **H)        # namba ile ile tena
        pays = SubscriptionPayment.objects.filter(transaction_ref='MPX1')
        self.assertEqual(pays.count(), 1)
        self.assertEqual((pays[0].amount, pays[0].plan), (int(self.enterprise.price_tzs), self.enterprise))

    def test_verify_twice_extends_once_and_revives_bot(self):
        from apps.chatbot.models import SubscriptionPayment
        pay = SubscriptionPayment.objects.create(subscription=self.sub, plan=self.enterprise,
                                                 amount=15000, months_covered=1, transaction_ref='X1')
        staff = TC()
        staff.force_login(User.objects.create_superuser('w', 'w@x.com', 'x'))
        staff.post(f'/manage/chatbot/payments/{pay.id}/verify/', {'months': '1'}, **H)
        self.sub.refresh_from_db()
        first = self.sub.end_date
        staff.post(f'/manage/chatbot/payments/{pay.id}/verify/', {'months': '1'}, **H)
        self.sub.refresh_from_db()
        self.bot.refresh_from_db()
        from dateutil.relativedelta import relativedelta
        self.assertEqual(first, self.today + relativedelta(months=1))   # kuanzia LEO, si tarehe iliyopita
        self.assertEqual(self.sub.end_date, first)                       # si miezi miwili
        self.assertEqual(self.sub.plan, self.enterprise)
        self.assertEqual((self.bot.status, self.bot.is_active), ('active', True))


class InvoiceAndSafetyTest(TestCase):
    def setUp(self):
        _pesapal(self)

    def _invoice(self, total):
        from apps.models import Invoice
        inv = Invoice.objects.create(client_name_manual='Tryvis', currency='TZS') \
            if 'client_name_manual' in [f.name for f in Invoice._meta.fields] else Invoice.objects.create(currency='TZS')
        return inv

    def test_invoice_changed_after_order_is_partial(self):
        from decimal import Decimal
        from apps.models import Invoice
        tx = PesapalTransaction.objects.create(purpose='invoice', target_id='TOK1', amount=Decimal('100000'),
                                               order_tracking_id='TRK-INV', status='pending')
        inv = Invoice.objects.create(token='TOK1', currency='TZS', status='sent',
                                     line_items=[{'desc': 'Website', 'qty': 1, 'unit_price': 150000, 'amount': 150000}])
        from apps.pesapal_fulfill import _fulfill_invoice
        _fulfill_invoice(tx)
        inv.refresh_from_db()
        # Awali: amount_paid = grand_total na status 'paid' — salio la 50,000 likapotea
        self.assertEqual(float(inv.amount_paid), 100000.0)
        self.assertEqual(inv.balance_due, 50000)
        self.assertEqual(inv.payments[0]['source'], 'pesapal')
        self.assertEqual(inv.status, 'partial')

    def test_paid_but_target_missing_alerts_owner(self):
        tx = PesapalTransaction.objects.create(purpose='hosting_renewal', target_id='99999', amount=50000,
                                               months=1, order_tracking_id='TRK-X', status='completed',
                                               first_name='Juma', phone='+255700')
        with mock.patch('apps.notify.notify') as notify, \
             self.captureOnCommitCallbacks(execute=True):
            from apps.pesapal_fulfill import fulfill
            fulfill(tx)
        self.assertTrue(notify.called)
        self.assertIn('MALIPO BILA HUDUMA', notify.call_args[0][0])
