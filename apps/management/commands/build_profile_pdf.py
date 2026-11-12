"""
Tengeneza upya PDF ya company profile (brochure ya kurasa 12).

    python manage.py build_profile_pdf

Inachora template ileile ya /company-profile/ kwa Chromium (Playwright), kwa
hiyo PDF inafanana na ukurasa wa web. Iendeshe kwenye kompyuta yako (si
Render) baada ya kubadilisha timu, bei au mawasiliano, kisha commit faili
apps/static/profile/JamiiTek-Company-Profile.pdf.

Inahitaji:  pip install playwright && playwright install chromium
"""
import re
import tempfile
from pathlib import Path

from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string

from apps.docs_views import brochure_pdf_path
from apps.models import CompanyProfile
from apps.profile_brochure import brochure_context


class Command(BaseCommand):
    help = 'Build the company profile PDF from the brochure template (needs Playwright).'

    def add_arguments(self, parser):
        parser.add_argument('--out', help='Where to write the PDF (default: apps/static/profile/...)')
        parser.add_argument('--lang', choices=['en', 'sw', 'all'], default='all',
                            help='Lugha ya PDF (default: zote mbili)')
        parser.add_argument('--chromium', help='Path to a Chromium binary (optional)')

    def handle(self, *args, **opts):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CommandError('Playwright haipo. Endesha: pip install playwright && playwright install chromium')

        profile = CompanyProfile.objects.filter(is_active=True).first()
        if profile is None:
            # Hakuna profile kwenye database hii — tumia za msingi.
            profile = CompanyProfile(phone='255750910158', period='2025 — 2026')
            self.stdout.write('Hakuna profile hai; natumia data za msingi.')

        langs = ['en', 'sw'] if opts['lang'] == 'all' else [opts['lang']]
        if opts['out'] and len(langs) > 1:
            raise CommandError('--out inahitaji --lang en au --lang sw')
        for lang in langs:
            self._build(profile, lang, opts)

    def _build(self, profile, lang, opts):
        from playwright.sync_api import sync_playwright
        html = render_to_string('docs/profile_brochure.html', brochure_context(profile, lang))

        # Static URLs → njia za faili, ili Chromium izisome bila server.
        def to_file(m):
            path = finders.find(m.group(2))
            return f'{m.group(1)}{Path(path).as_uri() if path else m.group(0)}'
        html = re.sub(r'((?:src=|url\()["\']?)/static/([^"\')]+)', to_file, html)

        out = Path(opts['out'] or Path(finders.find('profile/logo.png')).parent / Path(brochure_pdf_path(lang)).name)
        with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8') as fh:
            fh.write(html)
            tmp = Path(fh.name)
        try:
            with sync_playwright() as p:
                launch = {'executable_path': opts['chromium']} if opts['chromium'] else {}
                browser = p.chromium.launch(**launch)
                page = browser.new_page()
                page.goto(tmp.as_uri(), wait_until='networkidle')
                page.evaluate('document.fonts.ready')
                page.emulate_media(media='print')
                page.pdf(path=str(out), prefer_css_page_size=True, print_background=True)
                browser.close()
        finally:
            tmp.unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(f'PDF imeandikwa: {out} ({out.stat().st_size // 1024} KB)'))
