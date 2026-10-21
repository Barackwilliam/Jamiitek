"""
Portal → My Websites → Files: mteja anasimamia mafaili ya website yake ya static.
/manage/ → Websites → Files (GitHub): staff anaunganisha repo na token mara moja.
Mantiki ya GitHub na usalama wa mafaili: apps/static_files.py
"""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import static_files as sf
from .client_portal_views import client_required
from .management_views import staff_required
from .models import ManagedWebsite, StaticSiteRepo

LOCKED = ('suspended', 'terminated')


def _client_site(request, pk):
    website = get_object_or_404(ManagedWebsite, pk=pk, client=request.client_profile)
    site_repo = StaticSiteRepo.objects.filter(website=website).first()
    if website.site_type != 'static' or site_repo is None:
        raise Http404
    return website, site_repo


def _files_url(website, path=''):
    url = reverse('portal_site_files', args=[website.pk])
    return f'{url}#{path}' if path else url


def _who(request):
    return request.user.get_full_name() or request.user.username


@client_required
def portal_site_files(request, pk):
    website, site_repo = _client_site(request, pk)
    locked = website.status in LOCKED

    if request.method == 'POST':
        if locked:
            messages.error(request, 'Your hosting is suspended. Renew it to change your website files.')
            return redirect(_files_url(website))
        try:
            note = _handle_post(request, website, site_repo)
            messages.success(request, f'{note} Your website updates in 1–2 minutes.')
        except sf.FilesError as e:
            messages.error(request, str(e))
        return redirect(_files_url(website))

    files, error = [], ''
    try:
        files = sf.Repo.for_site(site_repo).list_files()
    except sf.FilesError as e:
        error = str(e)
    for f in files:
        f['editable'] = sf.is_text(f['path']) and f['size'] <= sf.MAX_EDIT
        f['protected'] = f['path'] in sf.PROTECTED
        f['url'] = website.url.rstrip('/') + '/' + f['path']
    return render(request, 'portal/site_files.html', {
        'title': f'Files — {website.name}',
        'client': request.client_profile,
        'website': website,
        'site_repo': site_repo,
        'files': files,
        'total_size': sum(f['size'] for f in files),
        'error': error,
        'locked': locked,
        'accept': ','.join('.' + e for e in sorted(sf.ALLOWED_EXT)),
    })


def _handle_post(request, website, site_repo):
    action = request.POST.get('action')
    who = _who(request)
    repo = sf.Repo.for_site(site_repo)

    if action == 'upload':
        uploads = request.FILES.getlist('files')
        if not uploads:
            raise sf.FilesError('Choose at least one file.')
        if len(uploads) > 50:
            raise sf.FilesError('Upload at most 50 files at a time, or use a .zip.')
        changes = {}
        for f in uploads:
            if f.size > sf.MAX_FILE:
                raise sf.FilesError(f'"{f.name}" is larger than 10 MB.')
            changes[sf.clean_path(f.name, request.POST.get('folder', ''))] = f.read()
        names = ', '.join(sorted(changes))[:120]
        sf.save(site_repo, changes, f'Upload {names} (Portal: {who})', who)
        return f'{len(changes)} file(s) uploaded.'

    if action == 'zip':
        upload = request.FILES.get('zipfile')
        if not upload:
            raise sf.FilesError('Choose a .zip file.')
        changes, skipped = sf.read_zip(upload)
        replace = request.POST.get('replace') == 'on'
        if replace:
            if 'index.html' not in changes:
                raise sf.FilesError('To replace the whole website, the .zip must contain index.html.')
            for f in repo.list_files():
                changes.setdefault(f['path'], None)          # yasiyokuwemo kwenye .zip yanafutwa
        sf.save(site_repo, changes,
                f'{"Replace website with" if replace else "Upload"} {upload.name} (Portal: {who})', who)
        added = sum(1 for v in changes.values() if v is not None)
        removed = len(changes) - added
        note = f'{added} file(s) from {upload.name} uploaded' + (f', {removed} old file(s) removed.' if removed else '.')
        if skipped:
            note += f' Skipped (type or size not allowed): {", ".join(skipped[:5])}{"…" if len(skipped) > 5 else ""}.'
        return note

    if action == 'delete':
        path = sf.clean_path(request.POST.get('path', ''))
        if path in sf.PROTECTED:
            raise sf.FilesError('index.html is your home page and cannot be deleted. Edit or replace it instead.')
        if path not in {f['path'] for f in repo.list_files()}:
            raise sf.FilesError('That file no longer exists.')
        sf.save(site_repo, {path: None}, f'Delete {path} (Portal: {who})', who)
        return f'{path} deleted.'

    raise sf.FilesError('Unknown action.')


@client_required
def portal_site_file_edit(request, pk):
    website, site_repo = _client_site(request, pk)
    try:
        path = sf.clean_path(request.GET.get('path') or request.POST.get('path', ''))
    except sf.FilesError as e:
        messages.error(request, str(e))
        return redirect(_files_url(website))
    if not sf.is_text(path):
        messages.error(request, 'Only text files (HTML, CSS, JS…) can be edited here.')
        return redirect(_files_url(website))
    repo = sf.Repo.for_site(site_repo)
    try:
        # Orodha isipopatikana, faili lililopo lisionekane jipya — Save ingelifuta
        exists = path in {f['path'] for f in repo.list_files()}
    except sf.FilesError as e:
        messages.error(request, str(e))
        return redirect(_files_url(website))

    if request.method == 'POST':
        content = request.POST.get('content', '').replace('\r\n', '\n')
        if website.status in LOCKED:
            messages.error(request, 'Your hosting is suspended. Renew it to change your website files.')
        elif len(content.encode()) > sf.MAX_EDIT:
            messages.error(request, 'The file is larger than 1 MB. Upload it instead.')
        else:
            try:
                who = _who(request)
                sf.save(site_repo, {path: content.encode()},
                        f'{"Edit" if exists else "Create"} {path} (Portal: {who})', who)
                messages.success(request, f'{path} saved. Your website updates in 1–2 minutes.')
                return redirect(_files_url(website, path))
            except sf.FilesError as e:
                messages.error(request, str(e))
    else:
        content = ''
        if exists:
            try:
                content = repo.read_text(path)
            except sf.FilesError as e:
                messages.error(request, str(e))
                return redirect(_files_url(website))

    return render(request, 'portal/site_file_edit.html', {
        'title': f'Edit {path}',
        'client': request.client_profile,
        'website': website,
        'path': path,
        'content': content,
        'exists': exists,
        'locked': website.status in LOCKED,
        'live_url': website.url.rstrip('/') + '/' + path,
    })


@staff_required
@require_POST
def static_repo_save(request, pk):
    """Staff: unganisha / badilisha / ondoa repo ya GitHub ya website ya static."""
    website = get_object_or_404(ManagedWebsite, pk=pk)
    back = reverse('website_detail', args=[pk]) + '#files'
    site_repo = StaticSiteRepo.objects.filter(website=website).first()

    if request.POST.get('remove') and site_repo:
        site_repo.delete()
        messages.success(request, 'GitHub repo disconnected. The client can no longer manage files.')
        return redirect(back)

    repo = request.POST.get('repo', '').strip()
    repo = repo.removeprefix('https://github.com/').removesuffix('.git').strip('/')
    branch = request.POST.get('branch', '').strip() or 'main'
    token = request.POST.get('token', '').strip() or (site_repo.token if site_repo else '')
    if repo.count('/') != 1 or not token:
        messages.error(request, 'Enter the repo as owner/name and a GitHub token.')
        return redirect(back)
    try:
        sf.Repo(repo, branch, token).check()
    except sf.FilesError as e:
        messages.error(request, f'GitHub check failed for {repo}@{branch}: {e}')
        return redirect(back)

    from .crypto import encryption_available
    if not encryption_available():
        messages.error(request, 'FERNET_KEY is not set on the server, so the token cannot be stored safely.')
        return redirect(back)
    site_repo = site_repo or StaticSiteRepo(website=website)
    site_repo.repo, site_repo.branch, site_repo.credentials = repo, branch, {'token': token}
    site_repo.save()
    if website.site_type != 'static':
        website.site_type = 'static'
        website.save(update_fields=['site_type', 'updated_at'])
    messages.success(request, f'Connected to {repo}@{branch}. The client now sees a Files button in the portal.')
    return redirect(back)
