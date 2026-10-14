"""
JamiiTek Website Builder — Models
=================================
Kila website ya mteja ni data tu (JSON) ndani ya database moja ya JamiiTek.
Hakuna tables mpya zinazoundwa kwa kila mteja — "structure" ya kila aina ya
website inatoka kwenye schema (builder/schemas/*.json) ambayo inaunda
Pages na Collections automatic wakati wa signup.
"""
import re
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

SCHEMAS_DIR = Path(__file__).resolve().parent / 'schemas'

# Subdomains ambazo mteja HARUHUSIWI kuchukua
RESERVED_SUBDOMAINS = {
    'www', 'admin', 'api', 'mail', 'smtp', 'ftp', 'app', 'dashboard',
    'panel', 'cpanel', 'blog', 'shop', 'store', 'help', 'support',
    'docs', 'status', 'dev', 'staging', 'test', 'demo', 'jamiitek',
    'static', 'media', 'cdn', 'assets', 'ussd', 'portal',
}

SUBDOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{1,48}[a-z0-9])?$')


def load_site_schema(website_type: str) -> dict:
    """Soma schema ya aina ya website. Ikikosekana, tumia default."""
    path = SCHEMAS_DIR / f'{website_type}.json'
    if not path.exists():
        path = SCHEMAS_DIR / 'default.json'
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def available_website_types():
    """Orodha ya aina za website zilizopo (kutoka schemas dir)."""
    types = []
    for p in sorted(SCHEMAS_DIR.glob('*.json')):
        if p.stem == 'default':
            continue
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
            types.append({'key': p.stem, 'label': data.get('label', p.stem.title())})
        except (json.JSONDecodeError, OSError):
            continue
    return types


def validate_subdomain(value: str):
    value = value.lower().strip()
    if value in RESERVED_SUBDOMAINS:
        raise ValidationError('This name is reserved by the system. Choose another one.')
    if not SUBDOMAIN_RE.match(value):
        raise ValidationError(
            'Subdomain must use lowercase letters, numbers and "-" only (3–50 chars), '
            'and cannot start or end with "-".'
        )


class ClientWebsite(models.Model):
    """Website moja ya mteja — inaonekana kwenye {subdomain}.jamiitek.com"""
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='websites'
    )
    subdomain = models.SlugField(
        max_length=50, unique=True, validators=[validate_subdomain]
    )
    website_type = models.CharField(max_length=50, default='companyprofile')
    site_name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=200, blank=True)
    logo_url = models.URLField(blank=True)           # Supabase Storage URL
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_address = models.CharField(max_length=200, blank=True)
    whatsapp_number = models.CharField(max_length=30, blank=True)
    theme_settings = models.JSONField(default=dict, blank=True)

    NAV_STYLES = [
        ('top', 'Top Navbar (classic)'),
        ('glass', 'Floating Glass Navbar'),
        ('side', 'Side Navbar (dashboard style)'),
        ('center', 'Centered Minimal'),
    ]
    nav_style = models.CharField(max_length=12, choices=NAV_STYLES, default='glass')
    accent_color = models.CharField(max_length=9, default='#e8a13c')
    dark_nav = models.BooleanField(default=True)
    # inaongezeka kila content (pages/items/settings) inapobadilika — kwa cache invalidation
    content_version = models.PositiveIntegerField(default=1)

    # ── Premium: custom domain (mfano dukalangu.co.tz) ──
    # Inawashwa na malipo (builder/billing.py): kununua template inayouzwa, au
    # "Remove JamiiTek logo". Premium = hakuna "Developed by JamiiTek" + domain yake.
    is_premium = models.BooleanField(
        default=False, help_text='Premium sites can connect a custom domain.')

    # ── Malipo (builder/billing.py) ──
    # Template ya marketplace iliyolipiwa — kuchapisha template inayouzwa kunahitaji hii
    paid_template_id = models.PositiveIntegerField(null=True, blank=True)
    hosting_until = models.DateField(null=True, blank=True,
                                     help_text='Hosting iliyolipiwa inaisha lini (mwaka 1 baada ya kulipa).')

    custom_domain = models.CharField(
        max_length=120, unique=True, null=True, blank=True,
        help_text='e.g. www.mybusiness.co.tz — bila http://')

    # ── Hali ya domain ya mteja (/manage/domains/) ─────────────
    # pending -> DNS bado haijaelekezwa kwetu
    # dns_ok  -> DNS iko sawa, Render bado inatengeneza SSL
    # active  -> https://domain inafunguka na inaonyesha website hii
    # error   -> kuna tatizo (angalia domain_message)
    DOMAIN_STATUS = [('pending', 'Inasubiri DNS'), ('dns_ok', 'DNS sawa — SSL inatengenezwa'),
                     ('active', 'Live'), ('error', 'Tatizo')]
    domain_status = models.CharField(max_length=10, choices=DOMAIN_STATUS, blank=True, default='')
    domain_message = models.CharField(max_length=300, blank=True, default='')
    domain_added_at = models.DateTimeField(null=True, blank=True)
    domain_checked_at = models.DateTimeField(null=True, blank=True)
    template_key = models.CharField(max_length=50, default='clean_start')
    nav_layout = models.CharField(
        max_length=10, default='topnav',
        choices=[('topnav', 'Top Navigation'), ('sidenav', 'Side Navigation')],
    )
    global_css = models.TextField(blank=True)   # design system ya template
    custom_nav_html = models.TextField(blank=True)   # navbar ya mteja mwenyewe (au tupu = default)
    custom_footer_html = models.TextField(blank=True) # footer ya mteja mwenyewe
    # Muundo wa header/footer kutoka builder/layouts.py. Site MPYA zinaanza na
    # top bar (Floating Glass); '' = muonekano wa zamani wa base.html.
    nav_preset = models.CharField(max_length=20, default='top_glass', blank=True)
    footer_preset = models.CharField(max_length=20, default='f_columns', blank=True)
    is_published = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)  # kwa admin wa JamiiTek
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.site_name} ({self.subdomain}.jamiitek.com)'

    @property
    def public_url(self):
        return f'https://{self.subdomain}.jamiitek.com'

    def save(self, *args, **kwargs):
        self.subdomain = self.subdomain.lower().strip()
        if self.custom_domain:
            self.custom_domain = (self.custom_domain.lower().strip()
                                  .replace('https://', '').replace('http://', '')
                                  .rstrip('/')) or None
        if self.pk and not kwargs.get('update_fields'):
            # Usirudishe nyuma content_version ya zamani iliyo kwenye memory —
            # inabadilishwa na bump_version() (F expression) tu.
            kwargs['update_fields'] = [
                f.name for f in self._meta.fields
                if f.name not in ('id', 'content_version', 'created_at')
            ]
        super().save(*args, **kwargs)

    def bump_version(self):
        from django.db.models import F
        ClientWebsite.objects.filter(pk=self.pk).update(
            content_version=F('content_version') + 1
        )

    def bootstrap_from_schema(self):
        """
        Unda pages na collections za default kutoka schema ya website_type.
        Hii ndiyo 'structure inayojitengeneza automatic kulingana na nature'.
        Inaitwa mara moja tu, wakati wa kuunda website.
        """
        schema = load_site_schema(self.website_type)

        for page_def in schema.get('pages', []):
            SitePage.objects.get_or_create(
                website=self,
                slug=page_def['slug'],
                defaults={
                    'title': page_def.get('title', page_def['slug'].title()),
                    'sort_order': page_def.get('order', 0),
                    'html_cache': page_def.get('starter_html', ''),
                    'css_cache': page_def.get('starter_css', ''),
                },
            )

        for col_def in schema.get('collections', []):
            SiteCollection.objects.get_or_create(
                website=self,
                slug=col_def['slug'],
                defaults={
                    'name': col_def.get('name', col_def['slug'].title()),
                    'name_singular': col_def.get('singular', col_def['slug'].title()),
                    'icon': col_def.get('icon', '📦'),
                    'fields': col_def.get('fields', []),
                },
            )


class SitePage(models.Model):
    """Page moja ya website ya mteja. Design nzima (GrapesJS) inakaa hapa."""
    website = models.ForeignKey(
        ClientWebsite, on_delete=models.CASCADE, related_name='pages'
    )
    slug = models.SlugField(max_length=80, default='home')
    title = models.CharField(max_length=200)
    grapes_data = models.JSONField(default=dict, blank=True)  # project data ya GrapesJS
    html_cache = models.TextField(blank=True)   # HTML iliyo-render (kwa speed)
    css_cache = models.TextField(blank=True)    # CSS ya page
    # HTML kamili (<html><head>...</html>) ya page iliyopakiwa kwa ZIP.
    # Ikiwa na kitu, inatolewa kama ilivyo — bila navbar/footer ya JamiiTek.
    # Tazama builder/site_import.py.
    raw_document = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    show_in_nav = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('website', 'slug')
        ordering = ['sort_order', 'slug']

    def __str__(self):
        return f'{self.website.subdomain}/{self.slug}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.website.bump_version()

    def delete(self, *args, **kwargs):
        website = self.website
        super().delete(*args, **kwargs)
        website.bump_version()


class SiteCollection(models.Model):
    """
    Aina ya content iliyo-structured: Packages, Trips, Destinations,
    Menu Items, Products, Rooms n.k. Fields zake zinafafanuliwa na schema
    (JSON) — si Django fields — kwa hiyo kila aina ya website inapata
    structure yake bila migrations.
    """
    website = models.ForeignKey(
        ClientWebsite, on_delete=models.CASCADE, related_name='collections'
    )
    slug = models.SlugField(max_length=60)
    name = models.CharField(max_length=100)            # "Tour Packages"
    name_singular = models.CharField(max_length=100)   # "Package"
    icon = models.CharField(max_length=10, default='📦')
    # fields: [{key, label, type(text|textarea|number|price|image|date|list), required}]
    fields = models.JSONField(default=list)

    class Meta:
        unique_together = ('website', 'slug')
        ordering = ['slug']

    def __str__(self):
        return f'{self.website.subdomain} · {self.name}'


class SiteItem(models.Model):
    """Item moja ndani ya collection — package moja, trip moja, destination moja."""
    collection = models.ForeignKey(
        SiteCollection, on_delete=models.CASCADE, related_name='items'
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    data = models.JSONField(default=dict)      # values za fields za schema
    image_url = models.URLField(blank=True)    # picha kuu (Supabase)
    is_visible = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('collection', 'slug')
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or 'item'
            slug, n = base, 2
            while SiteItem.objects.filter(
                collection=self.collection, slug=slug
            ).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)
        self.collection.website.bump_version()

    def delete(self, *args, **kwargs):
        website = self.collection.website
        super().delete(*args, **kwargs)
        website.bump_version()


class SiteAsset(models.Model):
    """Picha/faili la mteja lililopakiwa Supabase. Tunahifadhi URL tu."""
    website = models.ForeignKey(
        ClientWebsite, on_delete=models.CASCADE, related_name='assets'
    )
    url = models.URLField()
    file_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.file_name or self.url


class SiteInquiry(models.Model):
    """Booking / inquiry kutoka kwa mgeni wa website ya mteja."""
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ]
    website = models.ForeignKey(
        ClientWebsite, on_delete=models.CASCADE, related_name='inquiries')
    item = models.ForeignKey(
        SiteItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inquiries')  # package/product/dish iliyoulizwa
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    people_count = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Site inquiries'

    def __str__(self):
        return f'{self.name} → {self.website.subdomain}'


class AiUsageLog(models.Model):
    """Rate limiting ya AI assistant (Groq free tier ina limits)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    website = models.ForeignKey(ClientWebsite, on_delete=models.CASCADE, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'created_at'])]


class SiteImport(models.Model):
    """
    ZIP iliyopakiwa ambayo mteja bado hajaithibitisha (builder/site_import.py).

    Iko kwenye database, si cache: bila Redis kila worker wa gunicorn
    ana cache yake, na hakikisho lingepotea ombi la kuthibitisha
    likiangukia worker mwingine.

    `uploaded` ina URL za kila file lililopakiwa Supabase. Command ya
    `prune_site_imports` inazifuta mteja asipothibitisha ndani ya
    IMPORT_TTL_HOURS, au baadaye site isipozitaja tena (ZIP mpya
    imechukua nafasi ya kurasa zote za import hii).
    """
    # SET_NULL, si CASCADE: site ikifutwa, rekodi inabaki ili prune
    # ifute files zake Supabase (vinginevyo zingebaki bila mwenyewe).
    website = models.ForeignKey(
        ClientWebsite, on_delete=models.SET_NULL, null=True, related_name='imports')
    token = models.CharField(max_length=32, unique=True)
    result = models.JSONField(default=dict, blank=True)   # pages, skipped, missing
    uploaded = models.JSONField(default=list, blank=True)
    images = models.JSONField(default=list, blank=True)   # zinaingia SiteAsset zikithibitishwa
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.website.subdomain if self.website else "(site imefutwa)"} import {self.token[:8]}'


class BuilderPricing(models.Model):
    """Bei za jumla za Builder — rekodi MOJA tu (pk=1), inahaririwa kwenye admin."""
    remove_logo_price = models.PositiveIntegerField(
        default=0, verbose_name='Remove JamiiTek logo — price (TSh)',
        help_text='Malipo ya mara moja kwa website ya template ya bure: inaondoa "Developed by JamiiTek" '
                  'na inaruhusu domain yake. 0 = kitufe hakionyeshwi.')
    yearly_hosting_price = models.PositiveIntegerField(
        default=0, verbose_name='Next year hosting — price (TSh)',
        help_text='Ada ya kila mwaka baada ya mwaka wa kwanza (template iliyonunuliwa au Remove logo). '
                  '0 = hosting haiishi.')
    build_fee = models.PositiveIntegerField(
        default=0, verbose_name='"Unahitaji tukutengenezee?" — work fee (TSh)',
        help_text='Ada ya kazi ya timu kujenga website kwa mteja (inaongezwa juu ya bei ya template). '
                  '0 = fomu ya kulipia haipo; kitufe kinaelekeza kwenye proposal kama zamani.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Builder pricing'
        verbose_name_plural = 'Builder pricing'

    def __str__(self):
        return 'Builder pricing'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BuildRequest(models.Model):
    """Ombi la "Unahitaji tukutengenezee?" — mteja analipa (Pesapal), timu inamjengea website."""
    STATUS = [
        ('new', 'Not paid yet'),
        ('paid', 'Paid — start work'),
        ('working', 'Team is working'),
        ('done', 'Done'),
    ]
    token = models.CharField(max_length=32, unique=True, editable=False)
    template = models.ForeignKey('apps.WebsiteTemplate', null=True, blank=True, on_delete=models.SET_NULL)
    template_name = models.CharField(max_length=200, blank=True)

    name = models.CharField('Your name', max_length=120)
    business_name = models.CharField('Business name', max_length=160)
    phone = models.CharField('Phone (WhatsApp)', max_length=30)
    email = models.EmailField(blank=True)
    about = models.TextField('About your business')
    photos = models.JSONField(default=list, blank=True)

    template_price = models.PositiveIntegerField(default=0)
    build_fee = models.PositiveIntegerField(default=0)
    amount = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=10, choices=STATUS, default='new')
    notes = models.TextField(blank=True, help_text='Maelezo ya ndani ya timu.')
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Build request (Tukutengenezee)'
        verbose_name_plural = 'Build requests (Tukutengenezee)'

    def __str__(self):
        return f'{self.business_name} — {self.template_name or "template"} [{self.get_status_display()}]'

    def save(self, *args, **kwargs):
        if not self.token:
            import secrets
            self.token = secrets.token_urlsafe(16)[:24]
        super().save(*args, **kwargs)

