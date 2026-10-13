from django.db import models
from django.utils import timezone

from .team import CHOICES


class Kazi(models.Model):
    """
    Kazi moja ya mfanyakazi. `key` inazuia kazi ileile kuundwa mara mbili:
    invoice moja iliyochelewa ni kazi moja, hata mzunguko ukipita mara 50.
    """

    OPEN, AWAITING, SENT, DONE, DISMISSED = 'open', 'awaiting', 'sent', 'done', 'dismissed'
    STATUS = [
        (OPEN, 'Inafanyiwa kazi'),
        (AWAITING, 'Inasubiri idhini yako'),
        (SENT, 'Imetumwa'),
        (DONE, 'Imekamilika'),
        (DISMISSED, 'Imeachwa'),
    ]
    LIVE = (OPEN, AWAITING)

    CHANNELS = [
        ('none', '—'),
        ('email', 'Email'),
        ('whatsapp', 'WhatsApp'),
        ('social', 'Mitandao ya kijamii'),
        ('faq', 'FAQ ya JamiiBot'),
        ('seo', 'SEO ya Google'),
    ]
    PRIORITY = [(1, 'Juu'), (2, 'Kawaida'), (3, 'Chini')]

    worker = models.CharField(max_length=20, choices=CHOICES, db_index=True)
    key = models.CharField(max_length=120, unique=True)
    ref = models.CharField(max_length=60, blank=True, db_index=True,
                           help_text='Kitu kinachohusika, mfano invoice:12')
    title = models.CharField(max_length=200)
    detail = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(choices=PRIORITY, default=2)
    status = models.CharField(max_length=12, choices=STATUS, default=OPEN, db_index=True)
    link = models.CharField(max_length=300, blank=True)

    channel = models.CharField(max_length=10, choices=CHANNELS, default='none')
    recipient_name = models.CharField(max_length=160, blank=True)
    recipient_email = models.EmailField(blank=True)
    recipient_phone = models.CharField(max_length=40, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    draft = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    reminders = models.PositiveSmallIntegerField(default=0)
    pushed_at = models.DateTimeField(null=True, blank=True,
                                     help_text='Ilipotumwa wILife kuomba idhini')
    wilife_code = models.CharField(max_length=12, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ['priority', '-created_at']
        indexes = [models.Index(fields=['worker', 'status'], name='wf_kazi_worker_status')]
        verbose_name = 'Kazi'
        verbose_name_plural = 'Kazi'

    def __str__(self):
        return f'{self.worker}: {self.title}'

    @property
    def is_live(self):
        return self.status in self.LIVE

    @property
    def needs_approval(self):
        return self.status == self.AWAITING

    def close(self, status, result=''):
        self.status = status
        self.result = (result or '')[:400]
        self.closed_at = timezone.now()
        self.save(update_fields=['status', 'result', 'closed_at', 'updated_at'])


class Ripoti(models.Model):
    """Ripoti ya William — moja kwa kila aina kwa siku."""

    KINDS = [('asubuhi', 'Mpango wa asubuhi'), ('jioni', 'Ripoti ya jioni')]

    kind = models.CharField(max_length=10, choices=KINDS)
    date = models.DateField()
    text = models.TextField()
    delivered = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        constraints = [models.UniqueConstraint(fields=['kind', 'date'], name='wf_ripoti_kind_date')]
        verbose_name = 'Ripoti'
        verbose_name_plural = 'Ripoti'

    def __str__(self):
        return f'{self.get_kind_display()} {self.date}'


class Alama(models.Model):
    """Kumbukumbu ndogo za timu: alama ya mwisho kusomwa, mzunguko wa mwisho..."""

    key = models.CharField(max_length=80, unique=True)
    value = models.CharField(max_length=400, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Alama'
        verbose_name_plural = 'Alama'

    def __str__(self):
        return f'{self.key}={self.value}'

    @classmethod
    def get(cls, key, default=''):
        row = cls.objects.filter(key=key).first()
        return row.value if row else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={'value': str(value)[:400]})


class Mtihani(models.Model):
    """
    Mtihani wa umahiri: timu inafanya kazi kwenye data halisi, lakini kila
    kitu kinarudishwa nyuma (rollback) — hakuna kazi inayohifadhiwa wala
    ujumbe unaotumwa. Kinachobaki ni rasimu zao za mfano na ukaguzi wake.
    """

    RUNNING, DONE, FAILED = 'running', 'done', 'failed'
    STATUS = [(RUNNING, 'Unaendelea'), (DONE, 'Umekamilika'), (FAILED, 'Umeshindwa')]

    status = models.CharField(max_length=10, choices=STATUS, default=RUNNING)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Mtihani wa umahiri'
        verbose_name_plural = 'Mitihani ya umahiri'

    def __str__(self):
        return f'Mtihani {self.created_at:%d/%m %H:%M} ({self.status})'


class SeoRipoti(models.Model):
    """
    Ukaguzi wa SEO wa wiki moja (Grace, apps/wafanyakazi/seo.py): jumla ya
    Search Console kwa siku 28, ikilinganishwa na siku 28 zilizotangulia, na
    fursa zilizopatikana (maneno yenye impressions nyingi lakini clicks chache).
    """

    week = models.CharField(max_length=10, unique=True, help_text='Mfano 2026-W41')
    start = models.DateField()
    end = models.DateField()
    totals = models.JSONField(default=dict, blank=True)
    previous = models.JSONField(default=dict, blank=True)
    opportunities = models.JSONField(default=list, blank=True)
    movers = models.JSONField(default=dict, blank=True)
    top_queries = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start', '-created_at']
        verbose_name = 'Ripoti ya SEO'
        verbose_name_plural = 'Ripoti za SEO'

    def __str__(self):
        return f'SEO {self.week}'


class SeoBadiliko(models.Model):
    """
    Kichwa/maelezo ya SEO yaliyokubaliwa — na matokeo yake. Grace anapima
    ukurasa huo siku 28 KABLA na siku 28 BAADA ya badiliko (Search Console),
    ili ujue kama mapendekezo yake yanasaidia au yanaharibu.
    """

    kazi = models.OneToOneField(Kazi, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='seo_badiliko')
    page = models.CharField(max_length=500, help_text='URL kamili kama Search Console inavyoiona')
    old_title = models.CharField(max_length=200, blank=True)
    old_description = models.CharField(max_length=300, blank=True)
    new_title = models.CharField(max_length=200, blank=True)
    new_description = models.CharField(max_length=300, blank=True)
    applied_at = models.DateTimeField()
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-applied_at']
        verbose_name = 'Badiliko la SEO'
        verbose_name_plural = 'Mabadiliko ya SEO'

    def __str__(self):
        return f'{self.page} ({self.applied_at:%d/%m/%Y})'

    @property
    def verdict(self):
        """('imeboreka'|'imeshuka'|'sawa'|'data-ndogo'|'inasubiri', maelezo)."""
        if not self.after:
            return 'inasubiri', 'Inapimwa siku 31 baada ya badiliko'
        b, a = self.before or {}, self.after
        if b.get('impressions', 0) < 20 and a.get('impressions', 0) < 20:
            return 'data-ndogo', 'Impressions chache mno kuamua'
        b_ctr, a_ctr = b.get('ctr', 0), a.get('ctr', 0)
        b_clk, a_clk = b.get('clicks', 0), a.get('clicks', 0)
        if a_clk > b_clk and a_ctr >= b_ctr:
            return 'imeboreka', 'Clicks na CTR zimepanda'
        if a_clk < b_clk * 0.8 and a_ctr < b_ctr:
            return 'imeshuka', 'Clicks na CTR zimeshuka — fikiria kurudisha kichwa cha zamani'
        return 'sawa', 'Hakuna tofauti kubwa'
