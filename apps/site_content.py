# apps/site_content.py
"""
Content models for the public homepage sliders.

Images are stored as full Supabase Storage URLs (same pattern as Service / Team
use in models.py), so the CDN handles resizing, format negotiation and quality.
Nothing is hardcoded in the template — everything below is editable from admin.

Add to apps/models.py:

    from .site_content import HeroSlide, PortfolioItem, Testimonial   # noqa

...or just paste these classes at the bottom of models.py. Then:

    python manage.py makemigrations apps
    python manage.py migrate
"""

from django.db import models

# (uploadcare_widget imeondolewa — hakuna image za zamani za kubadilisha)


# ──────────────────────────────────────────────────────────────
# Shared image helper (Supabase Storage)
# ──────────────────────────────────────────────────────────────
class ImageMixin(models.Model):
    """
    Image field + helpers.

    Inahifadhi URL KAMILI ya Supabase Storage.

    Zamani ilikuwa `UploadcareImageMixin` na ilihifadhi UUID pekee;
    `save()` ilikata kila kitu kuwa UUID. Mixin ni abstract, kwa hiyo
    kubadilisha jina hakuhitaji migration — models zinabeba fields
    zao wenyewe.
    """

    image = models.CharField(
        max_length=255, blank=True,
        help_text='URL kamili ya image. Tumia kitufe cha kupakia.',
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # URL ya zamani ya Uploadcare (UUID tu) inabadilishwa kuwa URL
        # kamili ili templates zisiwe na hali mbili za kushughulikia.
        val = (self.image or '').strip()
        if val and not val.startswith('http'):
            uuid = extract_uuid(val)
            val = f'{cdn_base()}/{uuid}/' if uuid else ''
        self.image = val
        return super().save(*args, **kwargs)

    # -- Helpers (majina yamebaki ili templates zisibadilike) ---------
    def cdn(self, width=None, height=None, quality='smart', crop_faces=False):
        """
        Inarudisha URL ya image.

        `width` inapuuzwa. Uploadcare ilifanya resize kwenye CDN yake
        (`-/resize/800x/`). Supabase ina transformation pia, lakini ni
        ya plan ya kulipia — kwenye free tier inarudisha 400.

        Kwa hiyo tunarudisha image kama ilivyo, na ukubwa unashughulikiwa
        na CSS. Ikiwa utahamia plan ya kulipia, hapa ndipo pa kuongeza
        `/render/image/public/...?width=`.
        """
        return self.image or ''

    def srcset(self, widths, height_ratio=None, crop_faces=False):
        """Tupu — hakuna ukubwa tofauti bila transformation."""
        return ''

    # -- Template-friendly properties (no-arg, callable from Django) ---
    @property
    def url(self):
        return self.cdn(1600)

    @property
    def url_wide(self):
        return self.cdn(1920)

    @property
    def srcset_wide(self):
        return self.srcset([640, 960, 1280, 1600, 1920])

    @property
    def url_card(self):
        return self.cdn(800)

    @property
    def srcset_card(self):
        return self.srcset([400, 600, 800, 1200])

    @property
    def url_avatar(self):
        return self.cdn(160)


# ──────────────────────────────────────────────────────────────
# Hero slider
# ──────────────────────────────────────────────────────────────
class HeroSlide(ImageMixin):
    """Full-bleed photo slides at the top of the homepage."""

    eyebrow = models.CharField(
        max_length=80, blank=True,
        help_text='Small label above the headline, e.g. "Web Development"',
    )
    headline = models.CharField(
        max_length=120,
        help_text='Wrap the accented words in *asterisks*, e.g. "That *Drive Success*"',
    )
    subheadline = models.CharField(max_length=260, blank=True)

    cta_label = models.CharField(max_length=40, blank=True, default='Start Your Project')
    cta_url = models.CharField(max_length=300, blank=True, default='/get-started/')
    cta2_label = models.CharField(max_length=40, blank=True)
    cta2_url = models.CharField(max_length=300, blank=True)

    focal = models.CharField(
        max_length=20, default='center',
        choices=[('center', 'Center'), ('top', 'Top'), ('bottom', 'Bottom'),
                 ('left', 'Left'), ('right', 'Right')],
        help_text='Which part of the photo stays visible when cropped',
    )

    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)

    def headline_html(self):
        """*word* -> <em>word</em>, escaped everywhere else."""
        from django.utils.html import escape
        from django.utils.safestring import mark_safe
        import re
        safe = escape(self.headline)
        return mark_safe(re.sub(r'\*(.+?)\*', r'<em>\1</em>', safe))

    def __str__(self):
        return self.headline[:60]

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Hero Slide'


# ──────────────────────────────────────────────────────────────
# Portfolio / work slider
# ──────────────────────────────────────────────────────────────
class PortfolioItem(ImageMixin):
    """Real client work. Use a screenshot of the live site, 1600x1200 or wider."""

    title = models.CharField(max_length=120)
    client = models.CharField(max_length=120, blank=True)
    category = models.CharField(
        max_length=60, blank=True,
        help_text='e.g. E-Commerce, School System, Tourism',
    )
    summary = models.CharField(max_length=200, blank=True)
    live_url = models.URLField(blank=True, help_text='Link to the live site')
    year = models.CharField(max_length=9, blank=True)

    is_featured = models.BooleanField(default=True, help_text='Show in the homepage slider')
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.title} — {self.client}' if self.client else self.title

    # Onyesho la tovuti (HTML/CSS) kwa kazi isiyo na screenshot — au picha ikivunjika.
    MOCKS = [
        ('shop',   ('pos', 'shop', 'store', 'duka', 'market', 'commerce', 'retail')),
        ('safari', ('tour', 'travel', 'safari', 'hotel', 'lodge', 'tourism')),
        ('estate', ('estate', 'property', 'house', 'nyumba', 'rental', 'apartment')),
        ('school', ('school', 'education', 'academy', 'shule', 'college', 'university')),
        ('food',   ('restaurant', 'food', 'cafe', 'kitchen', 'chakula')),
    ]

    @property
    def mock(self):
        text = f'{self.category} {self.title} {self.summary}'.lower()
        for kind, words in self.MOCKS:
            if any(w in text for w in words):
                return kind
        return 'biz'

    class Meta:
        ordering = ['order', '-created_at']
        verbose_name = 'Portfolio Item'


# ──────────────────────────────────────────────────────────────
# Testimonials
# ──────────────────────────────────────────────────────────────
class Testimonial(ImageMixin):
    """Real client quotes with real photos."""

    quote = models.TextField(max_length=400)
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=140, blank=True, help_text='e.g. CEO, Mushi Traders')
    rating = models.IntegerField(default=5, choices=[(n, f'{n} stars') for n in range(1, 6)])

    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)

    @property
    def initials(self):
        bits = [p for p in self.name.split() if p]
        return ''.join(p[0] for p in bits[:2]).upper() or '?'

    def __str__(self):
        return f'{self.name} ({self.rating}★)'

    class Meta:
        ordering = ['order', 'id']