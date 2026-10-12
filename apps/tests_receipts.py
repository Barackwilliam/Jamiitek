"""Risiti: kuthibitisha, kupakua PDF haraka (cache), na risiti bila website."""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps import receipt_views
from apps.receipt_models import DevelopmentReceipt


class ReceiptDownloadTest(TestCase):
    def setUp(self):
        cache.clear()
        self.r = DevelopmentReceipt.objects.create(
            client_name_manual='Hibrahim Haule',
            client_company_manual='WEMASA Tanzania',
            project_label='WEMASA Tanzania — NGO',
            kind='deposit',
            amount_paid=Decimal('240000'),
            payment_reference='TRT-10000ERT',
            line_items=[{'desc': 'NGO website', 'qty': 1,
                         'unit_price': 600000, 'amount': 600000}],
            is_published=True,
            require_signature=False,
        )

    def test_verify_page_shows_manual_client_and_versioned_link(self):
        resp = self.client.get(self.r.verify_path)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'This receipt is genuine')
        self.assertContains(resp, 'Hibrahim Haule')
        self.assertContains(resp, 'WEMASA Tanzania — NGO')
        self.assertContains(resp, 'data-download=')
        self.assertContains(resp, receipt_views.receipt_pdf_url(self.r).replace('&', '&amp;'))
        # Hakuna kusubiri Google Fonts
        self.assertNotContains(resp, 'fonts.googleapis.com')

    def test_pdf_is_built_once_then_served_from_cache(self):
        url = receipt_views.receipt_pdf_url(self.r)
        real = receipt_views._html_to_pdf
        with mock.patch.object(receipt_views, '_html_to_pdf', side_effect=real) as build:
            first = self.client.get(url)
            second = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first['Content-Type'], 'application/pdf')
        self.assertEqual(first.content, second.content)
        self.assertEqual(build.call_count, 1)

    def test_editing_receipt_changes_version(self):
        before = receipt_views.receipt_pdf_url(self.r)
        DevelopmentReceipt.objects.filter(pk=self.r.pk).update(
            updated_at=self.r.updated_at.replace(year=self.r.updated_at.year + 1))
        self.r.refresh_from_db()
        self.assertNotEqual(before, receipt_views.receipt_pdf_url(self.r))

    def test_unpublished_receipt_is_not_downloadable(self):
        self.r.is_published = False
        self.r.save()
        resp = self.client.get(receipt_views.receipt_pdf_url(self.r))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.client.get(self.r.verify_path).status_code, 404)


class ReceiptConfirmTest(TestCase):
    """Mteja anathibitisha kupokea risiti — kidole/Face ID au sahihi, MARA MOJA."""

    def setUp(self):
        cache.clear()
        self.r = DevelopmentReceipt.objects.create(
            client_name_manual='Hibrahim Haule', project_label='WEMASA NGO',
            amount_paid=Decimal('240000'), is_published=True, require_signature=True,
            line_items=[{'desc': 'Website', 'qty': 1, 'unit_price': 600000, 'amount': 600000}],
        )
        self.base = f'{self.r.public_url}confirm/'
        self.ua = {'HTTP_USER_AGENT': 'Mozilla/5.0 (Linux; Android 14) Chrome/129.0 Mobile'}

    def test_unconfirmed_receipt_asks_first_and_blocks_pdf(self):
        page = self.client.get(self.r.verify_path)
        self.assertContains(page, 'Confirm with fingerprint')
        self.assertContains(page, 'data-needs-confirm')
        resp = self.client.get(receipt_views.receipt_pdf_url(self.r))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('#confirm', resp['Location'])

    def test_view_page_is_locked_until_confirmed(self):
        # "View" ilikuwa mlango wa nyuma: ukurasa wa risiti una kitufe chake
        # cha PDF na unaweza kuchapishwa.
        resp = self.client.get(self.r.public_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('#confirm', resp['Location'])
        self.client.post(self.base + 'sign/', {'signature_name': 'Hibrahim Haule'})
        self.assertEqual(self.client.get(self.r.public_url).status_code, 200)

    def test_staff_can_still_download_unconfirmed(self):
        from django.contrib.auth.models import User
        staff = User.objects.create_user('s', password='x', is_staff=True)
        self.client.force_login(staff)
        with mock.patch('apps.two_factor.StaffTwoFactorMiddleware.__call__',
                        lambda self, request: self.get_response(request)):
            resp = self.client.get(receipt_views.receipt_pdf_url(self.r))
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_options_give_a_platform_challenge_requiring_user_verification(self):
        resp = self.client.post(self.base + 'options/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['challenge'])
        self.assertEqual(data['rp']['id'], 'testserver')
        self.assertEqual(data['authenticatorSelection']['userVerification'], 'required')
        self.assertEqual(data['authenticatorSelection']['authenticatorAttachment'], 'platform')

    def _fake_verified(self, uv=True):
        return mock.patch('webauthn.verify_registration_response',
                          return_value=mock.Mock(user_verified=uv, credential_id=b'cred-123'))

    def test_device_confirmation_once_only(self):
        self.client.post(self.base + 'options/')
        with self._fake_verified():
            resp = self.client.post(self.base + 'device/', data='{}',
                                    content_type='application/json', **self.ua)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.r.refresh_from_db()
        self.assertTrue(self.r.is_signed)
        self.assertEqual(self.r.signature_method, 'device')
        self.assertEqual(self.r.signature_device, 'Android · Chrome')
        self.assertTrue(self.r.signature_credential)
        self.assertFalse(self.r.signature_data)          # hakuna biometric
        self.assertEqual(body['pdf_url'], receipt_views.receipt_pdf_url(self.r))

        # Mara ya pili: inakataliwa, na ukurasa haumwombi tena
        self.assertEqual(self.client.post(self.base + 'options/').status_code, 409)
        self.assertEqual(self.client.post(self.base + 'sign/', {'signature_name': 'X Y'}).status_code, 409)
        page = self.client.get(self.r.verify_path)
        self.assertNotContains(page, 'Confirm with fingerprint')
        self.assertContains(page, "Confirmed on client")
        pdf = self.client.get(body['pdf_url'])
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_device_without_user_verification_is_rejected(self):
        self.client.post(self.base + 'options/')
        with self._fake_verified(uv=False):
            resp = self.client.post(self.base + 'device/', data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.r.refresh_from_db()
        self.assertFalse(self.r.is_signed)

    def test_device_without_challenge_is_rejected(self):
        with self._fake_verified():
            resp = self.client.post(self.base + 'device/', data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'expired')

    def test_challenge_cannot_be_reused(self):
        self.client.post(self.base + 'options/')
        with mock.patch('webauthn.verify_registration_response', side_effect=ValueError('bad')):
            self.client.post(self.base + 'device/', data='{}', content_type='application/json')
        with self._fake_verified():
            resp = self.client.post(self.base + 'device/', data='{}', content_type='application/json')
        self.assertEqual(resp.json()['error'], 'expired')

    def test_typed_name_fallback(self):
        resp = self.client.post(self.base + 'sign/', {'signature_name': 'Hibrahim Haule'}, **self.ua)
        self.assertTrue(resp.json()['ok'])
        self.r.refresh_from_db()
        self.assertEqual(self.r.signature_method, 'typed')
        self.assertEqual(self.r.signature_name, 'Hibrahim Haule')

    def test_empty_signature_rejected(self):
        resp = self.client.post(self.base + 'sign/', {'signature_name': ' '})
        self.assertEqual(resp.status_code, 400)

    def test_unpublished_receipt_cannot_be_confirmed(self):
        self.r.is_published = False
        self.r.save()
        self.assertEqual(self.client.post(self.base + 'options/').status_code, 404)
