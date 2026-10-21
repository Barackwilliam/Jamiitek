"""
Mafaili ya website ya static ya mteja (Hosting → ManagedWebsite, site_type='static').

Website iko kwenye repo ya GitHub ambayo Render inaichapisha kila commit inapoingia.
Mteja anasimamia mafaili yake kwenye Portal → My Websites → Files: kupakia, kupakia
.zip nzima, kuhariri html/css na kufuta. Kila badiliko ni commit MOJA kwenye repo,
kisha Render inaichapisha ndani ya dakika 1–2. Mteja haoni GitHub wala Render.

Token ya GitHub (fine-grained, repo hiyo tu, "Contents: Read and write") inawekwa na
staff kwenye /manage/ → Websites → website → Files (GitHub), na inakaa imesimbwa
(StaticSiteRepo.credentials, apps/crypto.py).

Usalama: njia za mafaili zinasafishwa (hakuna ../, hakuna mafaili/folda zinazoanza na
nukta kama .github — GitHub Actions haziwezi kuwekwa na mteja), aina za mafaili
zinazoruhusiwa tu, na vikomo vya ukubwa (hata kwa .zip iliyobanwa sana).
"""
import base64
import os
import posixpath
import re
import zipfile

import requests

API = os.getenv('GITHUB_API_URL', 'https://api.github.com').rstrip('/')
TIMEOUT = 20

TEXT_EXT = {'html', 'htm', 'css', 'js', 'mjs', 'json', 'txt', 'xml', 'svg', 'md',
            'webmanifest', 'map', 'csv'}
ALLOWED_EXT = TEXT_EXT | {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'ico', 'bmp',
    'woff', 'woff2', 'ttf', 'otf', 'eot',
    'pdf', 'mp4', 'webm', 'mp3', 'ogg', 'wav',
}
MAX_FILE = 10 * 1024 * 1024        # faili moja
MAX_ZIP = 25 * 1024 * 1024         # .zip iliyopakiwa
MAX_UNZIPPED = 60 * 1024 * 1024    # jumla baada ya kufungua .zip
MAX_FILES = 500
MAX_EDIT = 1024 * 1024             # kihariri cha maandishi

_SEGMENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,99}$')
PROTECTED = {'index.html'}


class FilesError(Exception):
    """Kosa ambalo ujumbe wake unaweza kuonyeshwa kwa mteja moja kwa moja."""


def ext_of(path):
    return path.rsplit('.', 1)[-1].lower() if '.' in path.rsplit('/', 1)[-1] else ''


def is_text(path):
    return ext_of(path) in TEXT_EXT


def clean_path(raw, folder=''):
    """'Images\\Logo.png' + folder 'assets' → 'assets/Images/Logo.png'. Kosa kama si salama."""
    raw = (raw or '').replace('\\', '/').strip()
    folder = (folder or '').replace('\\', '/').strip().strip('/')
    path = posixpath.join(folder, raw.lstrip('/')) if folder else raw.lstrip('/')
    parts = [p for p in path.split('/') if p != '']
    if not parts or len(path) > 200:
        raise FilesError('Invalid file name.')
    for p in parts:
        if p in ('.', '..') or not _SEGMENT.match(p):
            raise FilesError(f'"{p}" is not allowed in a file name. Use letters, numbers, - and _.')
    path = '/'.join(parts)
    if ext_of(path) not in ALLOWED_EXT:
        raise FilesError(f'File type ".{ext_of(path) or "?"}" is not allowed on a static website.')
    return path


def visible(path):
    """Mafaili ya website tu — si .github/, .gitignore wala mengineyo ya ndani."""
    return not any(p.startswith('.') for p in path.split('/'))


def read_zip(fileobj):
    """
    .zip → {path: bytes}, na orodha ya mafaili yaliyorukwa.
    Folda moja ya juu (mf. 'website/index.html') inaondolewa ili index.html ikae juu.
    """
    if getattr(fileobj, 'size', 0) > MAX_ZIP:
        raise FilesError('The .zip is larger than 25 MB.')
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise FilesError('This is not a valid .zip file.')
    infos = [i for i in zf.infolist() if not i.is_dir()
             and not i.filename.startswith('__MACOSX/') and visible(i.filename)]
    if not infos:
        raise FilesError('The .zip is empty.')
    if len(infos) > MAX_FILES:
        raise FilesError(f'The .zip has more than {MAX_FILES} files.')
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise FilesError('The .zip is larger than 60 MB when extracted.')

    names = [i.filename for i in infos]
    tops = {n.split('/', 1)[0] for n in names}
    strip = len(tops) == 1 and all('/' in n for n in names)

    files, skipped = {}, []
    for info in infos:
        name = info.filename.split('/', 1)[1] if strip else info.filename
        try:
            path = clean_path(name)
        except FilesError:
            skipped.append(name)
            continue
        if info.file_size > MAX_FILE:
            skipped.append(name)
            continue
        files[path] = zf.read(info)
    return files, skipped


class Repo:
    """Repo moja ya GitHub, kupitia REST API (Git Data API kwa commit moja ya mafaili mengi)."""

    def __init__(self, repo, branch, token):
        self.repo, self.branch, self.token = repo.strip().strip('/'), (branch or 'main').strip(), token

    @classmethod
    def for_site(cls, site_repo):
        return cls(site_repo.repo, site_repo.branch, site_repo.token)

    def _req(self, method, path, **kw):
        try:
            r = requests.request(method, f'{API}/repos/{self.repo}{path}', timeout=TIMEOUT, headers={
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            }, **kw)
        except requests.RequestException:
            raise FilesError('Could not reach the file server. Please try again in a minute.')
        if r.status_code in (401, 403):
            raise FilesError('File access is not authorised. Please contact JamiiTek support.')
        if r.status_code == 404:
            raise FilesError('Not found.')
        if r.status_code == 409 and path.startswith('/git/'):
            raise FilesError('The website has no files yet. Please contact JamiiTek support.')
        if r.status_code == 422 and path.startswith('/git/refs'):
            raise FilesError('Another change was saved at the same moment. Please try again.')
        if r.status_code >= 400:
            raise FilesError(f'The file server returned an error ({r.status_code}). Please try again.')
        return r.json() if r.content else {}

    # ── Kusoma ──────────────────────────────────────────────────
    def check(self):
        """Kwa staff: repo ipo, token inaweza kuandika, na branch ipo."""
        info = self._req('GET', '')
        if not (info.get('permissions') or {}).get('push'):
            raise FilesError('The token can read this repo but cannot write to it '
                             '(needs "Contents: Read and write").')
        self._req('GET', f'/git/ref/heads/{self.branch}')
        return info

    def list_files(self):
        tree = self._req('GET', f'/git/trees/{self.branch}', params={'recursive': '1'})
        files = [{'path': t['path'], 'size': t.get('size') or 0}
                 for t in tree.get('tree', []) if t.get('type') == 'blob' and visible(t['path'])]
        return sorted(files, key=lambda f: (f['path'].count('/'), f['path'].lower()))

    def read_text(self, path):
        data = self._req('GET', f'/contents/{path}', params={'ref': self.branch})
        if (data.get('size') or 0) > MAX_EDIT:
            raise FilesError('This file is too large to edit here. Upload a new version instead.')
        raw = base64.b64decode(data.get('content') or '')
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            raise FilesError('This file is not plain text.')

    # ── Kuandika: commit moja kwa mabadiliko yote ───────────────
    def commit(self, changes, message, author):
        """changes = {path: bytes (weka/badilisha) au None (futa)} → sha ya commit mpya."""
        if not changes:
            raise FilesError('Nothing to save.')
        head = self._req('GET', f'/git/ref/heads/{self.branch}')['object']['sha']
        base_tree = self._req('GET', f'/git/commits/{head}')['tree']['sha']
        entries = []
        for path, content in sorted(changes.items()):
            if content is None:
                entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
                continue
            blob = self._req('POST', '/git/blobs', json={
                'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        tree = self._req('POST', '/git/trees', json={'base_tree': base_tree, 'tree': entries})
        commit = self._req('POST', '/git/commits', json={
            'message': message, 'tree': tree['sha'], 'parents': [head],
            'author': {'name': author[:80] or 'JamiiTek Portal', 'email': 'noreply@jamiitek.com'},
        })
        self._req('PATCH', f'/git/refs/heads/{self.branch}', json={'sha': commit['sha']})
        return commit['sha']


def save(site_repo, changes, message, author):
    """Commit + kumbukumbu ya mwisho kwenye StaticSiteRepo (inaonyeshwa kwa mteja na staff)."""
    from django.utils import timezone
    sha = Repo.for_site(site_repo).commit(changes, message, author)
    site_repo.last_commit_sha = sha
    site_repo.last_commit_at = timezone.now()
    site_repo.last_commit_message = message[:200]
    site_repo.save(update_fields=['last_commit_sha', 'last_commit_at', 'last_commit_message', 'updated_at'])
    return sha
