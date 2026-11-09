"""Ankara za renewal: kutengeneza, kutuma, uthibitisho wa mteja, risiti yenye sahihi, kuongeza muda."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps import renewals
from apps.models import (Client, DevelopmentReceipt, DomainRecord, HostingPayment, Invoice,
                         ManagedWebsite, PaymentProof, RenewalNotice)

NO_2FA = [m for m in __import__('django.conf', fromlist=['settings']).settings.MIDDLEWARE
          if 'TwoFactor' not in m]


@override_settings(MIDDLEWARE=NO_2FA, SITE_URL='https://www.jamiitek.com')
@mock.patch('apps.renewals.send_whatsapp', return_value=True)
class RenewalFlowTest(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.cl = Client.objects.create(name='Asha Ltd', email='asha@example.com', phone='0712345678')
        self.site = ManagedWebsite.objects.create(
            client=self.cl, name='Asha Shop', url='https://asha.co.tz', status='active',
            monthly_cost=20000, hosting_start_date=self.today - timedelta(days=360),
            hosting_end_date=self.today + timedelta(days=5))
        HostingPayment.objects.create(website=self.site, amount=192000, months_covered=12,
                                      payment_date=self.today - timedelta(days=360))
        self.dom = DomainRecord.objects.create(
            website=self.site, domain_name='asha.co.tz', registration_date=self.today - timedelta(days=340),
            expiry_date=self.today + timedelta(days=25), renewal_cost=35000)
        self.staff = User.objects.create_user('w', password='x', is_staff=True)

    def _make(self):
        made = renewals.create_invoices(today=self.today)
        self.assertEqual(len(made), 1)
        return made[0]

    # ── kutengeneza ──
    def test_one_invoice_per_client_with_hosting_and_domain(self, wa):
        inv = self._make()
        self.assertEqual(inv.client, self.cl)
        self.assertEqual(inv.payment_mode, 'manual')
        self.assertEqual(inv.status, 'sent')
        # Hosting ni mwezi MMOJA (hata kama malipo ya mwisho yalikuwa ya mwaka) + domain mwaka 1
        self.assertEqual(inv.grand_total, 20000 + 35000)
        self.assertEqual(inv.due_date, self.site.hosting_end_date)
        self.assertEqual(sorted(inv.renewals.values_list('kind', flat=True)), ['domain', 'hosting'])
        # Email + WhatsApp zimetumwa
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(inv.public_url, mail.outbox[0].alternatives[0][0])
        self.assertTrue(wa.called)
        self.assertIn(inv.public_url, wa.call_args[0][1])

    def test_no_duplicate_and_not_too_early(self, wa):
        self._make()
        self.assertEqual(renewals.create_invoices(today=self.today), [])
        self.site.hosting_end_date = self.today + timedelta(days=20)
        self.site.save()
        RenewalNotice.objects.all().delete()
        Invoice.objects.all().delete()
        # Hosting siku 20 bado ni mapema; domain (siku 25) inaingia
        inv = renewals.create_invoices(today=self.today)[0]
        self.assertEqual(list(inv.renewals.values_list('kind', flat=True)), ['domain'])

    def test_old_warning_skipped_when_invoice_open(self, wa):
        from apps.utils.email_notifications import send_bulk_expiry_warnings
        self._make()
        mail.outbox.clear()
        self.site.last_warning_stage = None
        self.site.save()
        send_bulk_expiry_warnings()
        self.assertEqual(mail.outbox, [])

    def test_reminders_once_per_stage(self, wa):
        inv = self._make()
        mail.outbox.clear()
        later = self.today + timedelta(days=3)          # siku 2 zimebaki → hatua ya 3
        self.assertEqual(renewals.send_reminders(today=later), 1)
        self.assertEqual(renewals.send_reminders(today=later), 0)
        self.assertEqual(renewals.send_reminders(today=self.today + timedelta(days=4)), 1)  # siku 1
        inv.refresh_from_db()
        self.assertEqual(len(mail.outbox), 2)

    # ── mteja anatuma uthibitisho ──
    def test_client_sends_proof(self, wa):
        inv = self._make()
        page = self.client.get(f'/invoice/{inv.token}/paid/')
        self.assertContains(page, 'Send proof of payment')
        self.assertContains(page, 'accept="image/*,application/pdf"')
        r = self.client.post(f'/invoice/{inv.token}/paid/', {'method': 'M-Pesa', 'reference': 'TK47XYZ',
                                                            'amount': '227000'})
        self.assertRedirects(r, f'/invoice/{inv.token}/paid/?sent=1')
        p = PaymentProof.objects.get()
        self.assertEqual((p.status, p.reference, p.amount), ('pending', 'TK47XYZ', Decimal('227000')))
        self.assertContains(self.client.get(r['Location']), 'Proof received')
        # Ankara ni Kiingereza pekee, hata ?lang=sw
        inv_page = self.client.get(f'/invoice/{inv.token}/?lang=sw').content.decode()
        self.assertIn('We are checking your payment', inv_page)
        self.assertNotIn('Tunahakiki', inv_page)

    def test_proof_with_pdf_document(self, wa):
        from django.core.files.uploadedfile import SimpleUploadedFile
        inv = self._make()
        pdf = SimpleUploadedFile('bank-slip.pdf', b'%PDF-1.4 test', content_type='application/pdf')
        with mock.patch('apps.storage.upload', return_value={'success': True, 'url': 'https://x/slip.pdf'}) as up:
            r = self.client.post(f'/invoice/{inv.token}/paid/', {'method': 'Bank transfer', 'file': pdf})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(up.called)
        self.assertEqual(PaymentProof.objects.get().file_url, 'https://x/slip.pdf')

    def test_proof_needs_reference_or_file(self, wa):
        inv = self._make()
        r = self.client.post(f'/invoice/{inv.token}/paid/', {'method': 'M-Pesa', 'reference': ''})
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'Enter the transaction ID', status_code=400)
        self.assertFalse(PaymentProof.objects.exists())

    # ── wewe unaidhinisha → risiti yenye sahihi + muda unaongezwa ──
    def test_approve_proof_receipt_needs_signature_and_extends(self, wa):
        inv = self._make()
        self.site.status = 'suspended'
        self.site.save()
        old_end, old_dom = self.site.hosting_end_date, self.dom.expiry_date
        proof = PaymentProof.objects.create(invoice=inv, method='M-Pesa', reference='TK47XYZ',
                                            amount=inv.grand_total)
        mail.outbox.clear()
        self.client.force_login(self.staff)
        r = self.client.post(f'/manage/invoices/{inv.pk}/proofs/{proof.pk}/approve/', {})
        self.assertEqual(r.status_code, 302)

        inv.refresh_from_db()
        proof.refresh_from_db()
        self.assertEqual((inv.status, proof.status), ('paid', 'approved'))

        rc = DevelopmentReceipt.objects.get()
        self.assertTrue(rc.require_signature)
        self.assertTrue(rc.needs_signature)
        self.assertEqual(rc.amount_paid, inv.grand_total)
        self.assertEqual(inv.payments[-1]['receipt'], rc.receipt_number)

        # Link iliyotumwa ni ya KUTHIBITISHA, si ya risiti yenyewe
        body = mail.outbox[-1].alternatives[0][0]
        self.assertIn(f'/receipt/verify/{rc.token}/#confirm', body)
        self.assertNotIn(f'/receipt/{rc.token}/', body)
        self.assertIn(f'/receipt/verify/{rc.token}/#confirm', wa.call_args[0][1])
        # Mteja asipothibitisha, link ya risiti inamrudisha kwenye kuthibitisha
        self.client.logout()
        self.assertIn('/receipt/verify/', self.client.get(rc.public_url)['Location'])

        self.site.refresh_from_db()
        self.dom.refresh_from_db()
        self.assertEqual(self.site.status, 'active')
        self.assertEqual(self.site.hosting_end_date, renewals._add_months(old_end, 1))
        self.assertEqual(self.dom.expiry_date, renewals._add_months(old_dom, 12))
        self.assertEqual(HostingPayment.objects.filter(website=self.site).count(), 2)
        self.assertTrue(all(n.applied_at for n in inv.renewals.all()))

        # Kuidhinisha tena hakuongezi muda mara ya pili
        renewals.apply_renewals(inv)
        self.site.refresh_from_db()
        self.assertEqual(self.site.hosting_end_date, renewals._add_months(old_end, 1))

    def test_no_payment_history_is_still_one_month(self, wa):
        HostingPayment.objects.all().delete()
        self.dom.delete()
        inv = self._make()
        self.assertEqual(inv.grand_total, 20000)
        self.assertIn('1 month (', inv.items[0]['desc'])

    def test_old_overbilled_invoice_is_corrected_and_resent(self, wa):
        inv = self._make()
        # Hali ya ankara ya zamani: hosting ya miezi 12
        n = inv.renewals.get(kind='hosting')
        n.months, n.amount = 12, Decimal('192000')
        n.save()
        inv.line_items = [{'desc': 'Website hosting – Asha Shop · 12 months', 'qty': 1, 'unit_price': 192000,
                           'amount': 192000}, {'desc': 'Domain', 'qty': 1, 'unit_price': 35000, 'amount': 35000}]
        inv.save()
        mail.outbox.clear()
        fixed = renewals.fix_overbilled()
        self.assertEqual(fixed, [inv])
        inv.refresh_from_db()
        self.assertEqual(inv.grand_total, 20000 + 35000)
        self.assertEqual(inv.renewals.get(kind='hosting').months, 1)
        self.assertIn('Corrected invoice', mail.outbox[-1].subject)
        self.assertIn('TZS 55,000', mail.outbox[-1].subject)
        self.assertIn('wrong', wa.call_args[0][1])
        # Mara ya pili hakuna cha kurekebisha (hakuna email ya pili)
        self.assertEqual(renewals.fix_overbilled(), [])

    def test_overbilled_invoice_with_payment_is_left_alone(self, wa):
        inv = self._make()
        n = inv.renewals.get(kind='hosting')
        n.months = 12
        n.save()
        inv.record_payment(10000, method='M-Pesa')
        inv.save()
        total = inv.grand_total
        self.assertEqual(renewals.fix_overbilled(), [])
        inv.refresh_from_db()
        self.assertEqual(inv.grand_total, total)

    def test_pay_ahead_options_are_advice_not_debt(self, wa):
        inv = self._make()
        self.assertEqual(inv.grand_total, 20000 + 35000)          # ankara bado ni mwezi 1
        opts = {o['months']: o for o in renewals.pay_ahead_options(inv)}
        self.assertEqual(sorted(opts), [2, 3, 4, 6, 12])
        self.assertEqual(opts[2]['hosting'], 40000)                # miezi 2: hakuna punguzo
        self.assertEqual(opts[3]['hosting'], 57000)                # 60,000 - 5%
        self.assertEqual(opts[4]['hosting'], 80000)
        self.assertEqual(opts[6]['hosting'], 114000)               # 120,000 - 5%
        self.assertEqual(opts[12]['hosting'], 228000)              # 240,000 - 5%
        self.assertEqual(opts[12]['total'], 228000 + 35000)        # pamoja na domain ya ankara
        self.assertEqual(opts[12]['saving'], 12000)
        # Email inataja chaguo lakini kiasi cha kulipa ni cha mwezi mmoja
        body = mail.outbox[0].body
        self.assertIn('Tip (optional)', body)
        self.assertIn('Amount to pay: TZS 55,000', body)
        page = self.client.get(inv.public_url).content.decode()
        self.assertIn('pay ahead and save', page)
        self.assertIn('not money you owe', page)

    def test_client_pays_ahead_and_approval_extends_by_those_months(self, wa):
        inv = self._make()
        old_end = self.site.hosting_end_date
        self.client.post(f'/invoice/{inv.token}/paid/', {'method': 'M-Pesa', 'reference': 'AHEAD6',
                                                        'months': '6', 'amount': '149000'})
        proof = PaymentProof.objects.get()
        self.assertEqual(proof.months, 6)
        self.client.force_login(self.staff)
        self.client.post(f'/manage/invoices/{inv.pk}/proofs/{proof.pk}/approve/', {})
        inv.refresh_from_db()
        self.assertEqual(inv.grand_total, 114000 + 35000)
        self.assertEqual(inv.status, 'paid')
        self.site.refresh_from_db()
        self.assertEqual(self.site.hosting_end_date, renewals._add_months(old_end, 6))
        # Ankara iliyochaguliwa na mteja haiguswi na "fix_overbilled"
        self.assertEqual(renewals.fix_overbilled(), [])

    def test_discounts_are_five_percent(self, wa):
        site = ManagedWebsite.objects.create(
            client=self.cl, name='New', url='https://n.co.tz', monthly_cost=10000,
            hosting_start_date=self.today, hosting_end_date=self.today + timedelta(days=60))
        self.assertEqual([float(site.discount_for(m)) for m in (1, 2, 3, 4, 6, 12)], [0, 0, 5, 0, 5, 5])

    def test_mark_paid_creates_receipt_for_any_invoice(self, wa):
        inv = Invoice.objects.create(client_name='Juma', client_email='juma@example.com', status='sent',
                                     line_items=[{'desc': 'Logo', 'qty': 1, 'unit_price': 50000}])
        self.client.force_login(self.staff)
        r = self.client.post(f'/manage/invoices/{inv.pk}/mark-paid/', {'amount': '20000', 'method': 'M-Pesa',
                                                                       'reference': 'AB12'})
        d = r.json()
        self.assertTrue(d['ok'])
        rc = DevelopmentReceipt.objects.get(receipt_number=d['receipt'])
        self.assertEqual((rc.kind, rc.amount_paid, rc.payment_method), ('partial', Decimal('20000'), 'mpesa'))
        self.assertTrue(d['receipt_sent']['email'])
        self.assertIn('#confirm', mail.outbox[-1].alternatives[0][0])

    def test_reject_records_nothing(self, wa):
        inv = self._make()
        proof = PaymentProof.objects.create(invoice=inv, reference='FAKE')
        self.client.force_login(self.staff)
        self.client.post(f'/manage/invoices/{inv.pk}/proofs/{proof.pk}/reject/', {'note': 'Not found'})
        inv.refresh_from_db()
        proof.refresh_from_db()
        self.assertEqual((proof.status, inv.paid_total), ('rejected', 0))
        self.assertFalse(DevelopmentReceipt.objects.exists())


class PhoneDigitsTest(TestCase):
    def test_tz_numbers(self):
        self.assertEqual(renewals.phone_digits('0712 345 678'), '255712345678')
        self.assertEqual(renewals.phone_digits('+255 712 345 678'), '255712345678')
        self.assertEqual(renewals.phone_digits('712345678'), '255712345678')
