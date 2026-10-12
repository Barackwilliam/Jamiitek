"""Ankara: hesabu, malipo, hali, na kurasa za mteja/mfanyakazi."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.models import Invoice

NO_2FA = [m for m in __import__('django.conf', fromlist=['settings']).settings.MIDDLEWARE
          if 'TwoFactor' not in m]


def make(**kw):
    data = dict(client_name='Asha', client_email='asha@example.com', status='sent', currency='TZS',
                line_items=[{'desc': 'Website', 'qty': 1, 'unit_price': 1000000, 'amount': 1000000}])
    data.update(kw)
    return Invoice.objects.create(**data)


class InvoiceLogicTest(TestCase):
    def test_items_accept_description_key_and_missing_amount(self):
        inv = make(line_items=[{'description': 'Hosting', 'amount': 18000},
                               {'desc': 'Domain', 'qty': 2, 'unit_price': '35,000'}])
        self.assertEqual([i['desc'] for i in inv.items], ['Hosting', 'Domain'])
        self.assertEqual(inv.subtotal, 88000)

    def test_payments_add_up_and_drive_status(self):
        inv = make()
        inv.record_payment(400000, method='M-Pesa', reference='ABC')
        self.assertEqual((inv.status, inv.balance_due, inv.paid_percent), ('partial', 600000, 40))
        inv.record_payment('600,000', method='Bank')
        self.assertEqual(inv.status, 'paid')
        self.assertEqual(len(inv.payments), 2)
        self.assertIsNotNone(inv.paid_at)

    def test_overdue_excludes_draft_cancelled_and_paid(self):
        past = timezone.localdate() - timedelta(days=3)
        self.assertTrue(make(due_date=past).is_overdue)
        self.assertEqual(make(due_date=past).days_overdue, 3)
        for st in ('draft', 'cancelled', 'paid'):
            self.assertFalse(make(due_date=past, status=st).is_overdue, st)

    def test_default_payment_methods(self):
        details = [m['details'] for m in Invoice.DEFAULT_PAYMENT_METHODS]
        self.assertIn('0750910158 - WILLIAM CHIPINDI', details)
        self.assertIn('0152566355900 - WILLIAM CHIPINDI', details)


@override_settings(MIDDLEWARE=NO_2FA, SITE_URL='https://www.jamiitek.com')
class InvoiceStaffViewsTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('w', password='x', is_staff=True)
        self.client.force_login(self.staff)

    def post(self, inv, **data):
        return self.client.post(f'/manage/invoices/{inv.pk}/edit/', data, HTTP_X_REQUESTED_WITH='fetch', secure=True)

    def test_new_invoice_has_defaults(self):
        self.client.get('/manage/invoices/new/', secure=True)
        inv = Invoice.objects.latest('pk')
        self.assertEqual(inv.payment_methods, Invoice.DEFAULT_PAYMENT_METHODS)
        self.assertEqual(inv.payment_mode, 'manual')
        self.assertEqual(inv.due_date - inv.issue_date, timedelta(days=14))

    def test_save_recomputes_amounts_and_rejects_bad_numbers(self):
        inv = make()
        r = self.post(inv, line_items='[{"desc":"Hosting","qty":"12","unit_price":"30000","amount":"1"}]',
                      tax_percent='abc', payment_mode='both', status='sent')
        self.assertEqual(r.status_code, 400)
        self.assertIn('VAT', r.json()['errors'][0])
        inv.refresh_from_db()
        self.assertEqual(inv.line_items[0]['amount'], 360000)
        self.assertEqual(inv.payment_mode, 'both')
        self.assertIsNone(inv.tax_percent)

    def test_duplicate_invoice_number_refused(self):
        a, b = make(), make()
        r = self.post(b, invoice_number=a.invoice_number)
        self.assertEqual(r.status_code, 400)
        b.refresh_from_db()
        self.assertNotEqual(b.invoice_number, a.invoice_number)

    def test_status_paid_records_remaining_balance(self):
        inv = make()
        inv.record_payment(250000)
        inv.save()
        self.post(inv, status='paid')
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.balance_due, len(inv.payments)), ('paid', 0, 2))

    def test_mark_paid_adds_instead_of_replacing(self):
        inv = make()
        for amount in ('300000', '200000'):
            self.client.post(f'/manage/invoices/{inv.pk}/mark-paid/', {'amount': amount, 'method': 'M-Pesa'}, secure=True)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal('500000'))
        self.assertEqual(inv.status, 'partial')
        r = self.client.post(f'/manage/invoices/{inv.pk}/payments/0/remove/', secure=True)
        self.assertTrue(r.json()['ok'])
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal('200000'))

    def test_send_email_marks_sent_and_uses_official_link(self):
        inv = make(status='draft', payment_methods=Invoice.DEFAULT_PAYMENT_METHODS)
        r = self.client.post(f'/manage/invoices/{inv.pk}/send/', {'lang': 'sw'}, secure=True)
        self.assertTrue(r.json()['ok'])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')
        self.assertEqual(mail.outbox[0].to, ['asha@example.com'])
        self.assertIn(f'https://www.jamiitek.com{inv.public_url}', mail.outbox[0].body)
        self.assertIn('0750910158 - WILLIAM CHIPINDI', mail.outbox[0].body)

    def test_staff_preview_does_not_mark_viewed(self):
        inv = make()
        self.client.get(inv.public_url, secure=True)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')

    def test_deposit_typed_as_amount_paid_can_be_cleared(self):
        # INV-2026-0028: hakuna items, 250,000 iliwekwa kwenye "Amount paid" ya zamani
        inv = make(line_items=[], amount_paid=Decimal('250000'), invoice_type='deposit')
        self.assertEqual(inv.unlogged_paid, 250000)
        r = self.client.post(f'/manage/invoices/{inv.pk}/payments/earlier/remove/', secure=True)
        self.assertTrue(r.json()['ok'])
        inv.refresh_from_db()
        self.assertIsNone(inv.amount_paid)
        self.assertEqual(inv.status, 'sent')

    def test_zero_total_cannot_be_sent_or_paid(self):
        inv = make(status='draft', line_items=[])
        r = self.post(inv, status='sent')
        self.assertEqual(r.status_code, 400)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'draft')
        self.assertFalse(self.client.post(f'/manage/invoices/{inv.pk}/send/', secure=True).json()['ok'])
        self.assertFalse(self.client.post(f'/manage/invoices/{inv.pk}/mark-paid/', {'amount': '1000'}, secure=True).json()['ok'])

    def test_payment_above_balance_refused(self):
        inv = make()
        r = self.client.post(f'/manage/invoices/{inv.pk}/mark-paid/', {'amount': '1500000'}, secure=True)
        self.assertEqual(r.status_code, 400)
        inv.refresh_from_db()
        self.assertIsNone(inv.amount_paid)

    def test_list_filters(self):
        make(due_date=timezone.localdate() - timedelta(days=2))
        make(status='draft')
        r = self.client.get('/manage/invoices/?show=overdue', secure=True)
        self.assertEqual(len(r.context['invoices']), 1)
        self.assertEqual(r.context['counts']['draft'], 1)


@override_settings(MIDDLEWARE=NO_2FA, PESAPAL_ENABLED=True)
class InvoicePublicViewTest(TestCase):
    def test_client_view_marks_viewed_and_shows_methods(self):
        inv = make(payment_methods=Invoice.DEFAULT_PAYMENT_METHODS)
        r = self.client.get(inv.public_url + '?lang=sw', secure=True)
        self.assertContains(r, '0750910158 - WILLIAM CHIPINDI')
        self.assertNotContains(r, 'Lipa sasa')          # manual: hakuna Pesapal
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'viewed')

    def test_payment_mode_controls_what_client_sees(self):
        inv = make(payment_mode='pesapal', payment_methods=Invoice.DEFAULT_PAYMENT_METHODS)
        r = self.client.get(inv.public_url + '?lang=sw', secure=True)
        self.assertContains(r, 'Lipa sasa')
        self.assertNotContains(r, '0750910158 - WILLIAM CHIPINDI')
        inv.payment_mode = 'both'
        inv.save()
        r = self.client.get(inv.public_url + '?lang=sw', secure=True)
        self.assertContains(r, 'Lipa sasa')
        self.assertContains(r, '0750910158 - WILLIAM CHIPINDI')

    def test_draft_and_cancelled_hidden_from_client(self):
        for st in ('draft', 'cancelled'):
            inv = make(status=st)
            self.assertEqual(self.client.get(inv.public_url, secure=True).status_code, 404)
            self.assertEqual(self.client.get(inv.public_url + 'pdf/', secure=True).status_code, 404)
            self.assertEqual(self.client.post(f'/pay/invoice/{inv.token}/', secure=True).status_code, 404)

    def test_pdf_renders_with_history(self):
        inv = make()
        inv.record_payment(100000, method='M-Pesa', reference='QK1')
        inv.save()
        r = self.client.get(inv.public_url + 'pdf/', secure=True)
        self.assertEqual(r['Content-Type'], 'application/pdf')
