"""Portal → Files ya website ya static (apps/static_files.py + static_files_views.py)."""
import base64
import datetime
import hashlib
import io
import zipfile
from unittest import mock
from urllib.parse import urlsplit

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from .models import Client, ManagedWebsite, StaticSiteRepo


class FakeGitHub:
    """GitHub ya kumbukumbu: endpoints zile tu ambazo apps/static_files.py inatumia."""

    def __init__(self, files, push=True):
        self.push, self.blobs, self.trees, self.commits = push, {}, {}, {}
        self.head = self._commit(dict(files), 'init')
        self.messages = []

    @staticmethod
    def _sha(*parts):
        return hashlib.sha1(repr(parts).encode()).hexdigest()

    def _commit(self, files, message):
        tree = self._sha('tree', sorted(files.items()))
        self.trees[tree] = files
        sha = self._sha('commit', tree, message, len(self.commits))
        self.commits[sha] = tree
        return sha

    @property
    def files(self):
        return self.trees[self.commits[self.head]]

    def handle(self, method, url, params=None, json_body=None):
        path = urlsplit(url).path.split('/repos/o/site', 1)[1]
        if method == 'GET' and path == '':
            return 200, {'full_name': 'o/site', 'permissions': {'push': self.push}}
        if method == 'GET' and path == '/git/ref/heads/main':
            return 200, {'object': {'sha': self.head}}
        if method == 'GET' and path.startswith('/git/commits/'):
            return 200, {'tree': {'sha': self.commits[path.rsplit('/', 1)[1]]}}
        if method == 'GET' and path == '/git/trees/main':
            return 200, {'tree': [{'path': p, 'type': 'blob', 'size': len(c)} for p, c in self.files.items()]}
        if method == 'GET' and path.startswith('/contents/'):
            p = path[len('/contents/'):]
            if p not in self.files:
                return 404, {}
            return 200, {'size': len(self.files[p]), 'content': base64.b64encode(self.files[p]).decode()}
        if method == 'POST' and path == '/git/blobs':
            data = base64.b64decode(json_body['content'])
            sha = self._sha('blob', data)
            self.blobs[sha] = data
            return 201, {'sha': sha}
        if method == 'POST' and path == '/git/trees':
            files = dict(self.trees[json_body['base_tree']])
            for e in json_body['tree']:
                if e['sha'] is None:
                    if e['path'] not in files:
                        return 422, {}                     # GitHub haikubali kufuta kisichokuwepo
                    del files[e['path']]
                else:
                    files[e['path']] = self.blobs[e['sha']]
            sha = self._sha('tree', sorted(files.items()))
            self.trees[sha] = files
            return 201, {'sha': sha}
        if method == 'POST' and path == '/git/commits':
            assert json_body['parents'] == [self.head]
            sha = self._sha('commit', json_body['tree'], json_body['message'], len(self.commits))
            self.commits[sha] = json_body['tree']
            self.messages.append(json_body['message'])
            return 201, {'sha': sha}
        if method == 'PATCH' and path == '/git/refs/heads/main':
            self.head = json_body['sha']
            return 200, {'object': {'sha': self.head}}
        return 404, {}

    def request(self, method, url, timeout=None, headers=None, params=None, json=None):
        assert headers['Authorization'] == 'Bearer tok-123'
        status, body = self.handle(method, url, params, json)
        r = mock.Mock(status_code=status)
        r.content = b'{}' if body is not None else b''
        r.json.return_value = body
        return r


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return SimpleUploadedFile('site.zip', buf.getvalue(), content_type='application/zip')


class StaticFilesTest(TestCase):

    def setUp(self):
        from cryptography.fernet import Fernet
        from apps import crypto
        patcher = mock.patch.dict('os.environ', {'FERNET_KEY': Fernet.generate_key().decode(),
                                                 'STAFF_2FA_REQUIRED': 'false'})
        patcher.start()
        self.addCleanup(patcher.stop)
        crypto._CHECKED, crypto._FERNET = False, None
        self.addCleanup(lambda: setattr(crypto, '_CHECKED', False))

        self.gh = FakeGitHub({'index.html': b'<h1>Karibu</h1>', 'style.css': b'body{}',
                              '.github/workflows/x.yml': b'on: push'})
        p = mock.patch('apps.static_files.requests.request', side_effect=self.gh.request)
        p.start()
        self.addCleanup(p.stop)

        today = timezone.now().date()
        self.owner = User.objects.create_user('juma', 'j@x.com', 'p')
        client = Client.objects.create(user=self.owner, name='Juma', email='j@x.com')
        self.site = ManagedWebsite.objects.create(
            client=client, name='Duka la Juma', url='https://dukalajuma.co.tz', site_type='static',
            status='active', monthly_cost=20000, hosting_start_date=today - datetime.timedelta(days=10),
            hosting_end_date=today + datetime.timedelta(days=20))
        self.repo = StaticSiteRepo.objects.create(website=self.site, repo='o/site', branch='main',
                                                  credentials={'token': 'tok-123'})
        self.url = f'/portal/websites/{self.site.pk}/files/'

    def _post(self, data):
        self.client.force_login(self.owner)
        return self.client.post(self.url, data, follow=True)

    def _msgs(self, r):
        return [str(m) for m in r.context['messages']]

    # ── Staff ──────────────────────────────────────────────────
    def test_staff_connects_repo_and_token_is_stored_encrypted(self):
        self.repo.delete()
        staff = User.objects.create_user('boss', 'b@x.com', 'p', is_staff=True)
        self.client.force_login(staff)
        save = f'/manage/websites/{self.site.pk}/files-repo/'

        self.gh.push = False
        r = self.client.post(save, {'repo': 'o/site', 'token': 'tok-123'}, follow=True)
        self.assertIn('cannot write', ' '.join(self._msgs(r)))
        self.assertFalse(StaticSiteRepo.objects.exists())

        self.gh.push = True
        r = self.client.post(save, {'repo': 'https://github.com/o/site.git', 'branch': '', 'token': 'tok-123'},
                             follow=True)
        self.assertIn('Connected to o/site@main', ' '.join(self._msgs(r)))
        repo = StaticSiteRepo.objects.get()
        self.assertEqual(repo.token, 'tok-123')
        from django.db import connection
        with connection.cursor() as c:
            c.execute('SELECT credentials FROM apps_staticsiterepo')
            self.assertNotIn('tok-123', c.fetchone()[0])        # imesimbwa kwenye database
        page = self.client.get(f'/manage/websites/{self.site.pk}/').content.decode()
        self.assertIn('Files (GitHub)', page)
        self.assertNotIn('tok-123', page)

        # Kubadilisha branch bila kuandika token upya kunaitunza token ya zamani
        self.client.post(save, {'repo': 'o/site', 'branch': 'main', 'token': ''})
        self.assertEqual(StaticSiteRepo.objects.get().token, 'tok-123')

    # ── Kuona ──────────────────────────────────────────────────
    def test_owner_sees_website_files_but_not_internal_ones(self):
        self.client.force_login(self.owner)
        detail = self.client.get(f'/portal/websites/{self.site.pk}/').content.decode()
        self.assertIn(self.url, detail)
        self.assertIn(self.url, self.client.get('/portal/websites/').content.decode())
        page = self.client.get(self.url).content.decode()
        self.assertIn('index.html', page)
        self.assertIn('style.css', page)
        self.assertNotIn('.github', page)

    def test_other_clients_and_sites_without_repo_get_404(self):
        other = User.objects.create_user('mwingine', 'o@x.com', 'p')
        Client.objects.create(user=other, name='Mwingine', email='o@x.com')
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.repo.delete()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    # ── Kupakia ────────────────────────────────────────────────
    def test_upload_into_folder_is_one_commit(self):
        r = self._post({'action': 'upload', 'folder': 'images',
                        'files': [SimpleUploadedFile('logo.png', b'PNG'), SimpleUploadedFile('a.jpg', b'JPG')]})
        self.assertIn('2 file(s) uploaded', ' '.join(self._msgs(r)))
        self.assertEqual(self.gh.files['images/logo.png'], b'PNG')
        self.assertEqual(len(self.gh.messages), 1)
        self.assertIn('Portal: juma', self.gh.messages[0])
        self.repo.refresh_from_db()
        self.assertEqual(self.repo.last_commit_sha, self.gh.head)

    def test_unsafe_names_and_types_are_refused(self):
        before = dict(self.gh.files)
        for name, folder in (('x.php', ''), ('x.html', '../..'), ('x.yml', '.github/workflows'),
                             ('.htaccess', '')):
            r = self._post({'action': 'upload', 'folder': folder, 'files': [SimpleUploadedFile(name, b'x')]})
            self.assertTrue(any('not allowed' in m for m in self._msgs(r)), (name, self._msgs(r)))
        self.assertEqual(self.gh.files, before)

    def test_zip_upload_strips_top_folder_and_can_replace_everything(self):
        z = _zip({'site/index.html': b'<h1>Mpya</h1>', 'site/about.html': b'about',
                  'site/run.php': b'<?php', '__MACOSX/site/._index.html': b'junk'})
        r = self._post({'action': 'zip', 'zipfile': z, 'replace': 'on'})
        msg = ' '.join(self._msgs(r))
        self.assertIn('2 file(s) from site.zip uploaded, 1 old file(s) removed', msg)
        self.assertIn('Skipped', msg)
        self.assertEqual(set(self.gh.files), {'index.html', 'about.html', '.github/workflows/x.yml'})
        self.assertEqual(self.gh.files['index.html'], b'<h1>Mpya</h1>')

    def test_replace_zip_without_index_is_refused(self):
        r = self._post({'action': 'zip', 'zipfile': _zip({'about.html': b'x'}), 'replace': 'on'})
        self.assertIn('must contain index.html', ' '.join(self._msgs(r)))
        self.assertNotIn('about.html', self.gh.files)

    # ── Kufuta na kuhariri ─────────────────────────────────────
    def test_delete_file_but_never_the_home_page(self):
        r = self._post({'action': 'delete', 'path': 'index.html'})
        self.assertIn('cannot be deleted', ' '.join(self._msgs(r)))
        self._post({'action': 'delete', 'path': 'style.css'})
        self.assertEqual(set(self.gh.files), {'index.html', '.github/workflows/x.yml'})

    def test_edit_existing_and_create_new_page(self):
        self.client.force_login(self.owner)
        edit = f'/portal/websites/{self.site.pk}/files/edit/'
        self.assertContains(self.client.get(edit, {'path': 'index.html'}), '&lt;h1&gt;Karibu&lt;/h1&gt;')
        self.client.post(edit, {'path': 'index.html', 'content': '<h1>Habari</h1>\r\n'})
        self.assertEqual(self.gh.files['index.html'], b'<h1>Habari</h1>\n')
        self.client.post(edit, {'path': 'contact.html', 'content': 'simu'})
        self.assertEqual(self.gh.files['contact.html'], b'simu')
        self.assertTrue(self.gh.messages[-1].startswith('Create contact.html'))
        r = self.client.get(edit, {'path': 'logo.png'}, follow=True)
        self.assertIn('Only text files', ' '.join(self._msgs(r)))

    def test_editor_never_opens_an_existing_page_as_blank_when_github_is_down(self):
        self.client.force_login(self.owner)
        with mock.patch('apps.static_files.requests.request', side_effect=__import__('requests').ConnectionError):
            r = self.client.get(f'/portal/websites/{self.site.pk}/files/edit/', {'path': 'index.html'}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], self.url)
        self.assertIn('Could not reach', ' '.join(self._msgs(r)))

    def test_suspended_hosting_is_read_only(self):
        ManagedWebsite.objects.filter(pk=self.site.pk).update(status='suspended')
        r = self._post({'action': 'delete', 'path': 'style.css'})
        self.assertIn('suspended', ' '.join(self._msgs(r)))
        self.assertIn('style.css', self.gh.files)
        self.assertContains(self.client.get(self.url), 'Files are read-only')
        self.client.post(f'/portal/websites/{self.site.pk}/files/edit/', {'path': 'style.css', 'content': 'x'})
        self.assertEqual(self.gh.files['style.css'], b'body{}')
