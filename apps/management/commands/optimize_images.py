"""
Punguza picha ZILIZOKWISHA pakiwa Supabase (picha mpya zinapunguzwa zenyewe
wakati wa kupakia — angalia apps/storage.py → optimize_image).

    python manage.py optimize_images            # angalia tu: itaokoa kiasi gani
    python manage.py optimize_images --apply    # fanya kweli

Kwa kila picha: inapakua, inapunguza (≤2000px, WebP, bila EXIF), inapakia
kama faili JIPYA, kisha inabadilisha URL kwenye database. Faili la zamani
HALIFUTWI — kama kuna kitu kinachorejelea URL ya zamani (k.m. HTML ya ukurasa
wa builder), bado kitafanya kazi.

Inagusa tu picha zilizo kwenye bucket yetu ya Supabase. Picha ikiwa tayari
ndogo (punguzo < 15%), inaachwa kama ilivyo.
"""
from django.apps import apps
from django.core.management.base import BaseCommand

from apps import storage

# (model, field) — kila sehemu inayohifadhi URL ya picha
TARGETS = [
    ('apps.HeroSlide', 'image'),
    ('apps.PortfolioItem', 'image'),
    ('apps.Testimonial', 'image'),
    ('apps.Service', 'image'),
    ('apps.Team', 'image'),
    ('apps.BlogAuthor', 'photo'),
    ('apps.BlogPost', 'cover_image'),
    ('apps.CompanyProfile', 'logo_url'),
    ('builder.ClientWebsite', 'logo_url'),
    ('builder.SiteItem', 'image_url'),
]

MIN_SAVING = 0.15

# Upande mrefu zaidi kwa sehemu zinazoonyeshwa ndogo (nyingine zote: storage.OPTIMIZE_MAX_SIDE).
# Kadi ya portfolio ni ≤650px (1200 inatosha skrini za 2x); picha ya testimonial ni 46px.
MAX_SIDE = {
    'apps.PortfolioItem': 1200,
    'apps.Testimonial': 320,
}


def shrink(url, label, max_side=None, apply=False):
    """Pakua picha, ipunguze, na (apply=True) pakia toleo jipya.

    Rudisha (status, ukubwa_wa_zamani, ukubwa_mpya, url_mpya au ujumbe wa kosa).
    status: 'ok' | 'skip' | 'error'. URL ya zamani haiguswi.
    """
    import requests

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.content
    except Exception as e:
        return 'error', 0, 0, f'haikupakuliwa ({e})'

    ext = url.rsplit('.', 1)[-1].lower().split('?')[0]
    ext = 'jpg' if ext == 'jpeg' else ext
    new, new_ext = storage.optimize_image(data, ext, max_side or MAX_SIDE.get(label, storage.OPTIMIZE_MAX_SIDE))
    if len(new) > len(data) * (1 - MIN_SAVING):
        return 'skip', len(data), len(data), ''
    if not apply:
        return 'ok', len(data), len(new), ''

    res = storage.upload_bytes(new, f'optimized/{label.split(".")[-1].lower()}',
                               new_ext, 'image/webp' if new_ext == 'webp' else resp.headers.get('Content-Type', ''))
    if not res.get('success'):
        return 'error', len(data), len(new), f'upload: {res.get("error")}'
    return 'ok', len(data), len(new), res['url']


class Command(BaseCommand):
    help = 'Punguza picha zilizopo Supabase (WebP, ≤2000px). Bila --apply inaonyesha tu.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Pakia matoleo madogo na ubadilishe URL kwenye database.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Shughulikia picha hizi tu (0 = zote).')

    def handle(self, *args, **opts):
        apply, limit = opts['apply'], opts['limit']
        if apply and not storage.is_configured():
            self.stderr.write('Supabase haijawekwa (SUPABASE_URL / funguo za S3).')
            return

        prefix = storage.public_url('x')[:-1]          # .../object/public/<bucket>/
        if not prefix.startswith('http'):
            self.stderr.write('SUPABASE_URL haijawekwa — siwezi kutambua picha zetu.')
            return

        seen = {}                       # url ya zamani -> mpya (picha moja, sehemu nyingi)
        before = after = done = skipped = failed = 0

        for label, field in TARGETS:
            try:
                Model = apps.get_model(label)
            except LookupError:
                continue
            rows = (Model.objects.exclude(**{f'{field}__isnull': True})
                    .exclude(**{field: ''}).values_list('pk', field))
            for pk, url in rows:
                if limit and done + skipped + failed >= limit:
                    break
                if not url or not url.startswith(prefix):
                    continue
                if url in seen:
                    if seen[url] and apply:
                        Model.objects.filter(pk=pk).update(**{field: seen[url]})
                    continue

                status, old_size, new_size, result = shrink(url, label, apply=apply)
                if status == 'error':
                    failed += 1
                    self.stdout.write(f'  ✗ {label}#{pk}: {result}')
                    seen[url] = None
                    continue
                if status == 'skip':
                    skipped += 1
                    seen[url] = None
                    continue

                before += old_size
                after += new_size
                done += 1
                self.stdout.write(f'  {label}#{pk}: {old_size//1024} KB → {new_size//1024} KB')
                if apply:
                    Model.objects.filter(pk=pk).update(**{field: result})
                seen[url] = result or None

        mb = lambda n: f'{n / 1024 / 1024:.1f} MB'
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Picha {done}: {mb(before)} → {mb(after)} '
            f'(zimeokolewa {mb(before - after)}). Zilizoachwa (tayari ndogo): {skipped}. '
            f'Zilizoshindwa: {failed}.'))
        if not apply and done:
            self.stdout.write('Hakuna kilichobadilishwa. Endesha tena na --apply kufanya kweli.')
