"""Kasi ya tovuti: picha zinapunguzwa, kurasa za umma zinatoka cache, HTML inabanwa."""
from io import BytesIO
from unittest import mock

from django.core.cache import caches
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from PIL import Image

from apps import storage
from apps.models import Service


def _jpeg(w=3200, h=2400):
    import random
    img = Image.new('RGB', (w, h))
    px = img.load()
    for x in range(0, w, 8):                     # maudhui yenye kelele kama picha halisi
        for y in range(0, h, 8):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=95)
    return buf.getvalue()


class OptimizeImageTest(TestCase):
    def test_big_photo_becomes_smaller_webp_within_2000px(self):
        data = _jpeg()
        new, ext = storage.optimize_image(data, 'jpg')
        self.assertEqual(ext, 'webp')
        self.assertLess(len(new), len(data))
        self.assertLessEqual(max(Image.open(BytesIO(new)).size), storage.OPTIMIZE_MAX_SIDE)

    def test_gps_and_exif_are_removed(self):
        img = Image.new('RGB', (2400, 1600), 'orange')
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'                 # Make
        buf = BytesIO()
        img.save(buf, 'JPEG', quality=95, exif=exif.tobytes())
        new, ext = storage.optimize_image(buf.getvalue(), 'jpg')
        self.assertEqual(ext, 'webp')
        self.assertFalse(dict(Image.open(BytesIO(new)).getexif()))

    def test_gif_pdf_and_broken_files_are_left_alone(self):
        self.assertEqual(storage.optimize_image(b'GIF89a...', 'gif'), (b'GIF89a...', 'gif'))
        self.assertEqual(storage.optimize_image(b'%PDF-1.4', 'pdf'), (b'%PDF-1.4', 'pdf'))
        self.assertEqual(storage.optimize_image(b'\xff\xd8\xffjunk', 'jpg'), (b'\xff\xd8\xffjunk', 'jpg'))

    def test_tiny_png_kept_when_webp_would_not_help(self):
        buf = BytesIO()
        Image.new('RGBA', (40, 40), (0, 0, 0, 0)).save(buf, 'PNG')
        data = buf.getvalue()
        self.assertEqual(storage.optimize_image(data, 'png'), (data, 'png'))

    @mock.patch.object(storage, 'is_configured', return_value=True)
    @mock.patch.object(storage, '_put', side_effect=lambda path, data, ct: {
        'success': True, 'url': path, 'path': path, 'size': len(data), 'ct': ct})
    def test_upload_stores_optimized_webp(self, _put, _cfg):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile('photo.jpg', _jpeg(), content_type='image/jpeg')
        r = storage.upload(f, folder='portfolio')
        self.assertTrue(r['success'])
        self.assertTrue(r['path'].endswith('.webp'))
        self.assertEqual(r['ct'], 'image/webp')


@override_settings(SUPABASE_URL='https://proj.supabase.co', SUPABASE_BUCKET='media')
class OptimizeImagesCommandTest(TestCase):
    def setUp(self):
        self.url = 'https://proj.supabase.co/storage/v1/object/public/media/services/2026/01/a.jpg'
        self.svc = Service.objects.create(service_type='Web', description='x', image=self.url)

    def _get(self, *a, **k):
        return mock.Mock(content=_jpeg(), headers={'Content-Type': 'image/jpeg'},
                         raise_for_status=lambda: None)

    def test_dry_run_changes_nothing(self):
        with mock.patch('requests.get', side_effect=self._get):
            call_command('optimize_images', stdout=BytesIO_text())
        self.svc.refresh_from_db()
        self.assertEqual(self.svc.image, self.url)

    def test_apply_uploads_and_updates_url(self):
        with mock.patch('requests.get', side_effect=self._get), \
             mock.patch.object(storage, 'is_configured', return_value=True), \
             mock.patch.object(storage, 'upload_bytes',
                               return_value={'success': True, 'url': 'https://proj.supabase.co/storage/v1/object/public/media/optimized/service/x.webp'}) as up:
            call_command('optimize_images', '--apply', stdout=BytesIO_text())
        self.svc.refresh_from_db()
        self.assertTrue(self.svc.image.endswith('.webp'))
        self.assertEqual(up.call_args[0][2], 'webp')

    def test_foreign_urls_are_ignored(self):
        Service.objects.filter(pk=self.svc.pk).update(image='https://elsewhere.com/a.jpg')
        with mock.patch('requests.get') as get:
            call_command('optimize_images', stdout=BytesIO_text())
        get.assert_not_called()


@override_settings(SUPABASE_URL='https://proj.supabase.co', SUPABASE_BUCKET='media')
class PortfolioImageShrinkTest(TestCase):
    """Picha za portfolio (PNG 300-600KB) zinapunguzwa hadi ≤1200px — kadi ni ≤650px."""
    URL = 'https://proj.supabase.co/storage/v1/object/public/media/portfolio/2026/01/a.png'
    NEW = 'https://proj.supabase.co/storage/v1/object/public/media/optimized/portfolioitem/b.webp'

    def _get(self, *a, **k):
        return mock.Mock(content=_jpeg(), headers={'Content-Type': 'image/png'},
                         raise_for_status=lambda: None)

    def test_portfolio_images_are_capped_at_1200px(self):
        from apps.management.commands.optimize_images import shrink
        with mock.patch('requests.get', side_effect=self._get), \
             mock.patch.object(storage, 'upload_bytes', return_value={'success': True, 'url': self.NEW}) as up:
            status, old, new, url = shrink(self.URL.replace('.png', '.jpg'), 'apps.PortfolioItem', apply=True)
        self.assertEqual((status, url), ('ok', self.NEW))
        self.assertLess(new, old)
        self.assertEqual(max(Image.open(BytesIO(up.call_args[0][0])).size), 1200)

    def test_admin_action_replaces_url_and_clears_home_cache(self):
        from django.contrib.admin.sites import site
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from apps import public_cache
        from apps.site_content import PortfolioItem

        item = PortfolioItem.objects.create(title='Shop', image=self.URL.replace('.png', '.jpg'))
        static = PortfolioItem.objects.get(live_url__icontains='wemasatanzania.org')   # picha ya /static/
        request = RequestFactory().post('/')
        request.user = get_user_model().objects.create_superuser('a', 'a@x.tz', 'p')
        admin = site._registry[PortfolioItem]
        with mock.patch('requests.get', side_effect=self._get), \
             mock.patch.object(storage, 'is_configured', return_value=True), \
             mock.patch.object(storage, 'upload_bytes', return_value={'success': True, 'url': self.NEW}), \
             mock.patch.object(admin, 'message_user'):
            before = public_cache._version()
            admin.optimize_images(request, PortfolioItem.objects.filter(pk__in=[item.pk, static.pk]))
        item.refresh_from_db()
        static.refresh_from_db()
        self.assertEqual(item.image, self.NEW)
        self.assertIn('/static/', static.image)
        self.assertNotEqual(public_cache._version(), before)        # ukurasa wa mwanzo utajengwa upya


def BytesIO_text():
    from io import StringIO
    return StringIO()


class PublicCacheTest(TestCase):
    def setUp(self):
        caches['local'].clear()

    def test_home_served_from_cache_then_refreshed_on_admin_edit(self):
        svc = Service.objects.create(service_type='Websites', description='d', show_on_home=True,
                                     summary='Old card', order=-1)
        self.client.get('/')                                   # inajaza cache
        with CaptureQueriesContext(connection) as q:
            resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(q), 0, [x['sql'] for x in q.captured_queries])

        svc.summary = 'Fresh card text'
        svc.save()                                             # admin anahariri
        self.assertContains(self.client.get('/'), 'Fresh card text')

    def test_about_and_services_also_cached(self):
        for url in ('/About/', '/service/'):
            self.client.get(url)
            with CaptureQueriesContext(connection) as q:
                self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(len(q), 0, url)


class CompressionTest(TestCase):
    def test_html_is_gzipped_for_browsers_that_accept_it(self):
        resp = self.client.get('/', HTTP_ACCEPT_ENCODING='gzip, br')
        self.assertEqual(resp.get('Content-Encoding'), 'gzip')
        plain = self.client.get('/')
        self.assertIsNone(plain.get('Content-Encoding'))
