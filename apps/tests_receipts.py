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
