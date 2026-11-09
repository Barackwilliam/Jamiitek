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
        # Mwaka 1 wa hosting (kama malipo ya mwisho) kwa punguzo la 20% + domain
        self.assertEqual(inv.grand_total, 20000 * 12 * 0.8 + 35000)
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
        self.assertEqual(self.site.hosting_end_date, renewals._add_months(old_end, 12))
        self.assertEqual(self.dom.expiry_date, renewals._add_months(old_dom, 12))
        self.assertEqual(HostingPayment.objects.filter(website=self.site).count(), 2)
        self.assertTrue(all(n.applied_at for n in inv.renewals.all()))

        # Kuidhinisha tena hakuongezi muda mara ya pili
        renewals.apply_renewals(inv)
        self.site.refresh_from_db()
        self.assertEqual(self.site.hosting_end_date, renewals._add_months(old_end, 12))

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
