# apps/receipt_models.py
"""
Development receipts — proof of payment for building a client's website.

Different from Invoice: an Invoice asks for money at the client level, a
Receipt confirms money already received for one specific ManagedWebsite.
A client can have several websites, so each website carries its own receipts.

Add to apps/models.py (bottom):

    from .receipt_models import DevelopmentReceipt   # noqa: F401
"""

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date


class DevelopmentReceipt(models.Model):

    METHODS = [
        ('mpesa',     'M-Pesa'),
        ('tigopesa',  'Tigo Pesa'),
        ('airtel',    'Airtel Money'),
        ('halopesa',  'HaloPesa'),
        ('bank',      'Bank Transfer'),
        ('cash',      'Cash'),
        ('other',     'Other'),
    ]

    KINDS = [
        ('full',     'Full payment'),
        ('deposit',  'Deposit / Advance'),
        ('balance',  'Balance / Final'),
        ('partial',  'Part payment'),
    ]

    # Website ni hiari. Risiti nyingi ni za kazi zisizo na tovuti kwenye
    # mfumo — app, mafunzo, ushauri, au mteja wa mara moja.
    website = models.ForeignKey(
        'ManagedWebsite', on_delete=models.SET_NULL, related_name='receipts',
        null=True, blank=True,
        help_text='Optional. Leave blank for work not tied to a managed website.')

    # Mteja wa moja kwa moja. Inatumika pale risiti haiambatani na tovuti
    # yoyote, lakini bado mteja ana akaunti ya portal — mfano mradi wa app
    # au mafunzo. Bila hii, risiti hiyo isingeonekana kabisa kwenye portal
    # yake, kwa sababu portal ilikuwa inachuja kwa website__client pekee.
    client = models.ForeignKey(
        'Client', on_delete=models.SET_NULL, related_name='direct_receipts',
        null=True, blank=True,
        help_text='Optional. Set this so the receipt appears in the client '
                  'portal when it is not linked to a website.')

    # Zinatumika pale website wala mteja hawapo.
    client_name_manual = models.CharField(
        'Client name', max_length=160, blank=True)
    client_company_manual = models.CharField(
        'Client company', max_length=160, blank=True)
    client_email_manual = models.EmailField('Client email', blank=True)
    client_phone_manual = models.CharField(
        'Client phone', max_length=40, blank=True)
    project_label = models.CharField(
        max_length=200, blank=True,
        help_text='What this receipt is for, when no website is linked. '
                  'e.g. "Africanberty Tips — Mobile App"')

    receipt_number = models.CharField(
        max_length=40, blank=True, help_text='Auto: RCP-YYYY-NNNN if left blank')
    token = models.CharField(max_length=48, unique=True, editable=False, db_index=True)

    kind = models.CharField(max_length=10, choices=KINDS, default='full')
    title = models.CharField(max_length=200, default='Website Development Payment')
    description = models.TextField(
        blank=True, help_text='Short summary of what was built')

    # [{"desc": "...", "qty": 1, "unit_price": 150000, "amount": 150000}]
    line_items = models.JSONField(default=list, blank=True)

    currency = models.CharField(max_length=8, default='TZS')
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='e.g. 18 for 18% VAT. Leave blank for none.')
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)

    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='How much the client actually paid on this receipt')

    payment_method = models.CharField(max_length=12, choices=METHODS, default='mpesa')
    payment_reference = models.CharField(
        max_length=120, blank=True, help_text='M-Pesa / bank transaction reference')
    payment_date = models.DateField(default=timezone.now)

    received_by = models.CharField(max_length=120, default='W. Chipindi')
    notes = models.TextField(blank=True)

    is_published = models.BooleanField(
        default=True, help_text='Untick to hide this receipt from the client portal')

    # ── Electronic signature (filled by the client at download time) ──
    require_signature = models.BooleanField(
        default=True,
        help_text='Ask the client to sign before the PDF downloads')
    signature_data = models.TextField(
        blank=True, help_text='Base64 PNG of the drawn signature')
    signature_name = models.CharField(max_length=160, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_ip = models.GenericIPAddressField(null=True, blank=True)

    # ── Uthibitisho kwa kifaa (WebAuthn) ──
    # Mteja anathibitisha kwa alama ya kidole / Face ID / PIN ya simu yake.
    # Alama ya kidole HAIJI kwetu kamwe — inabaki ndani ya simu. Tunapokea
    # uthibitisho wa kidijitali kwamba mwenye kifaa amekifungua, na
    # tunahifadhi kitambulisho cha ufunguo huo (credential id) kama ushahidi.
    SIGN_METHODS = [
        ('device', "Confirmed on client's device"),
        ('drawn',  'Drawn signature'),
        ('typed',  'Typed name'),
    ]
    signature_method = models.CharField(
        max_length=10, choices=SIGN_METHODS, blank=True)
    signature_device = models.CharField(
        max_length=160, blank=True, help_text='e.g. "Android · Chrome"')
    signature_credential = models.CharField(
        max_length=255, blank=True,
        help_text='WebAuthn credential id (base64url) used to confirm')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']
        verbose_name = 'Development Receipt'

    def __str__(self):
        return f'{self.receipt_number or "Receipt"} — {self.subject_name}'

    @property
    def subject_name(self):
        """Kichwa cha risiti: jina la tovuti, la mradi, au la mteja."""
        if self.website_id and self.website:
            return self.website.name
        return (self.project_label or self.client_company_manual
                or self.client_name_manual or 'Receipt')

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)
        if not self.receipt_number and self.pk:
            paid_on = self.payment_date
            if isinstance(paid_on, str):
                paid_on = parse_date(paid_on)
            year = (paid_on or timezone.now().date()).year
            number = f'RCP-{year}-{self.pk:04d}'
            DevelopmentReceipt.objects.filter(pk=self.pk).update(receipt_number=number)
            self.receipt_number = number

    # ── client shortcuts ──────────────────────────────────────
    @property
    def client_obj(self):
        """Mteja halisi: wa tovuti, au aliyewekwa moja kwa moja."""
        if self.website_id and self.website:
            return self.website.client
        return self.client if self.client_id else None

    @property
    def client_name(self):
        return getattr(self.client_obj, 'name', '') or self.client_name_manual

    @property
    def client_company(self):
        return getattr(self.client_obj, 'company', '') or self.client_company_manual

    @property
    def client_email(self):
        return getattr(self.client_obj, 'email', '') or self.client_email_manual

    @property
    def client_phone(self):
        return getattr(self.client_obj, 'phone', '') or self.client_phone_manual

    # ── money ─────────────────────────────────────────────────
    @property
    def subtotal(self):
        total = 0
        for item in self.line_items or []:
            try:
                total += float(item.get('amount') or 0)
            except (TypeError, ValueError):
                continue
        return total

    @property
    def discounted_subtotal(self):
        total = self.subtotal - float(self.discount_amount or 0)
        return max(0, total)

    @property
    def tax_amount(self):
        if not self.tax_percent:
            return 0
        return self.discounted_subtotal * float(self.tax_percent) / 100

    @property
    def grand_total(self):
        return self.discounted_subtotal + self.tax_amount

    @property
    def balance_due(self):
        return max(0, self.grand_total - float(self.amount_paid or 0))

    @property
    def is_fully_paid(self):
        return self.grand_total > 0 and self.balance_due <= 0

    @property
    def status_label(self):
        if self.is_fully_paid:
            return 'PAID IN FULL'
        if float(self.amount_paid or 0) > 0:
            return 'PART PAYMENT'
        return 'UNPAID'

    # ── signature / verification ──────────────────────────────
    @property
    def is_signed(self):
        return bool(self.signed_at and (
            self.signature_data or self.signature_name
            or self.signature_method == 'device'))

    @property
    def signed_label(self):
        """Maneno mafupi ya jinsi mteja alivyothibitisha."""
        if self.signature_method == 'device':
            return "Confirmed on client's device"
        if self.signature_data:
            return 'Signed by hand'
        if self.signature_name:
            return f'Signed as {self.signature_name}'
        return ''

    @property
    def needs_signature(self):
        return self.require_signature and not self.is_signed

    @property
    def public_url(self):
        return f'/receipt/{self.token}/'

    @property
    def verify_path(self):
        return f'/receipt/verify/{self.token}/'

    @property
    def verify_url(self):
        base = getattr(settings, 'SITE_URL', 'https://jamiitek.com').rstrip('/')
        return f'{base}{self.verify_path}'

    @property
    def verify_base(self):
        """
        Host + path without the scheme, e.g. 'jamiitek.com/receipt/verify/'.
        Printed on its own line so the 32-character token can sit below it —
        the full URL is 68 characters and will not fit on an 80mm roll.
        """
        base = getattr(settings, 'SITE_URL', 'https://jamiitek.com').rstrip('/')
        host = base.split('//')[-1]
        return f'{host}/receipt/verify/'

    @property
    def barcode_value(self):
        """Code 128-B only handles ASCII 32..126, so keep it plain."""
        return (self.receipt_number or f'RCP{self.pk or 0}')[:32]

    @property
    def filename(self):
        safe = ''.join(c for c in self.subject_name if c.isalnum() or c in ' -_').strip()
        safe = safe.replace(' ', '-') or 'receipt'
        return f'{self.receipt_number or "receipt"}-{safe}.pdf'