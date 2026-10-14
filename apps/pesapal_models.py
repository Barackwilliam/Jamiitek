"""
Pesapal transactions — injini moja ya malipo kwa mfumo mzima wa JamiiTek.

Transaction moja inaweza kuwakilisha malipo ya kitu chochote kinacholipika:
chatbot subscription, hosting renewal, au invoice. `purpose` + `target_id`
ndio vinavyoelekeza "fulfillment handler" sahihi baada ya malipo kukamilika.

Muundo huu ni wa jumla (generic) ili tusijirudie kila mahali. Haibadilishi
model zilizopo — inaongeza safu mpya tu.
"""
import secrets

from django.db import models


class PesapalTransaction(models.Model):
    # ── Kile kinacholipiwa ────────────────────────────────
    PURPOSE = [
        ('chatbot_subscription', 'Chatbot Subscription'),
        ('hosting_renewal',      'Hosting Renewal'),
        ('invoice',              'Invoice Payment'),
        # Builder (builder/billing.py) — target_id = ClientWebsite.pk
        ('builder_template',     'Website Template'),      # plan_id = WebsiteTemplate.pk
        ('builder_logo',         'Remove JamiiTek Logo'),
        ('builder_renew',        'Website Hosting (1 year)'),
        ('build_request',        'We Build Your Website'),   # target_id = BuildRequest.token
    ]

    # ── Hali ya malipo (inafuata Pesapal status_code) ─────
    STATUS = [
        ('pending',   'Pending'),
        ('completed', 'Completed'),
        ('failed',    'Failed'),
        ('reversed',  'Reversed'),
        ('invalid',   'Invalid'),
    ]

    # Namba yetu ya kumbukumbu — tunaituma Pesapal kama merchant_reference
    merchant_reference = models.CharField(max_length=50, unique=True, db_index=True)
    # Namba ya Pesapal — inarudi baada ya SubmitOrderRequest
    order_tracking_id  = models.CharField(max_length=100, blank=True, db_index=True)

    purpose   = models.CharField(max_length=40, choices=PURPOSE)
    # pk au token ya kitu kinacholipiwa (BotSubscription.id / ManagedWebsite.pk / Invoice.token / ClientWebsite.pk)
    target_id = models.CharField(max_length=64, db_index=True)

    amount      = models.DecimalField(max_digits=12, decimal_places=2)
    currency    = models.CharField(max_length=8, default='TZS')
    months      = models.PositiveSmallIntegerField(default=1)
    # Mpango wa JamiiBot uliolipiwa. Awali haukuhifadhiwa popote: mteja
    # aliyelipia Enterprise (bila kikomo) alibaki kwenye Starter (jumbe
    # 5,000), na bot yake ilisimama alipofikia kikomo alicholipia kuondoa.
    plan_id     = models.PositiveIntegerField(null=True, blank=True)
    description = models.CharField(max_length=200, blank=True)

    # ── Mlipaji ───────────────────────────────────────────
    email      = models.EmailField(blank=True)
    phone      = models.CharField(max_length=30, blank=True)
    first_name = models.CharField(max_length=80, blank=True)
    last_name  = models.CharField(max_length=80, blank=True)

    # ── Hali ──────────────────────────────────────────────
    status            = models.CharField(max_length=20, choices=STATUS, default='pending')
    status_code       = models.IntegerField(null=True, blank=True,
                                            help_text='Pesapal: 0 INVALID, 1 COMPLETED, 2 FAILED, 3 REVERSED')
    payment_method    = models.CharField(max_length=40, blank=True)
    confirmation_code = models.CharField(max_length=60, blank=True)
    redirect_url      = models.URLField(max_length=600, blank=True)

    # Kinga ya kujirudia — fulfillment ifanyike mara MOJA tu
    fulfilled = models.BooleanField(default=False)

    raw_status   = models.JSONField(default=dict, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Pesapal Transaction'
        verbose_name_plural = 'Pesapal Transactions'

    def __str__(self):
        return f'{self.merchant_reference} — {self.currency} {self.amount:,.0f} [{self.status}]'

    def save(self, *args, **kwargs):
        if not self.merchant_reference:
            short = {
                'chatbot_subscription': 'SUB',
                'hosting_renewal': 'HOST',
                'invoice': 'INV',
                'builder_template': 'TPL',
                'builder_logo': 'LOGO',
                'builder_renew': 'RNW',
                'build_request': 'BLD',
            }.get(self.purpose, 'PAY')
            self.merchant_reference = f'JT-{short}-{secrets.token_hex(6).upper()}'
        super().save(*args, **kwargs)

    @property
    def is_completed(self):
        return self.status == 'completed'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()
