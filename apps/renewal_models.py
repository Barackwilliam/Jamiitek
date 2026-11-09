# apps/renewal_models.py
"""
Ankara za renewal (hosting / domain / email hosting) na uthibitisho wa malipo
anaotuma mteja. Mantiki yote iko apps/renewals.py.

RenewalNotice — huduma MOJA kwa kipindi KIMOJA kwenye ankara moja.
    Ufunguo (kind, object_id, period_end) ni wa kipekee: kazi ya kila siku
    ikikimbia mara mbili, haitengenezi ankara ya pili kwa kipindi kilekile.
    Ankara ikilipwa yote, `applied_at` inawekwa baada ya tarehe kusogezwa —
    hivyo muda hauongezwi mara mbili.

PaymentProof — mteja amelipa (M-Pesa/benki) na anatuma ushahidi kutoka
    ukurasa wa ankara. Wewe unahakiki kisha unaidhinisha (inarekodi malipo)
    au unaikataa.
"""
from django.contrib.auth.models import User
from django.db import models


class RenewalNotice(models.Model):
    KINDS = [
        ('hosting', 'Website hosting'),
        ('domain', 'Domain'),
        ('email', 'Email hosting'),
    ]

    kind = models.CharField(max_length=10, choices=KINDS)
    object_id = models.PositiveIntegerField()
    # Tarehe huduma ilipokuwa inaisha wakati ankara inatengenezwa
    period_end = models.DateField()
    # Kipindi kinacholipiwa: miezi (hosting/email) au miaka x12 (domain)
    months = models.PositiveSmallIntegerField(default=12)
    label = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    invoice = models.ForeignKey('Invoice', on_delete=models.CASCADE, related_name='renewals')
    # Hatua ya mwisho ya ukumbusho iliyotumwa (siku zilizobaki: 14, 7, 3, 1, 0)
    last_stage = models.SmallIntegerField(null=True, blank=True)
    last_stage_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['period_end']
        constraints = [
            models.UniqueConstraint(fields=['kind', 'object_id', 'period_end'],
                                    name='renewal_once_per_period'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} #{self.object_id} → {self.period_end}'


class PaymentProof(models.Model):
    STATUS = [
        ('pending', 'Waiting for check'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    invoice = models.ForeignKey('Invoice', on_delete=models.CASCADE, related_name='proofs')
    method = models.CharField(max_length=60, blank=True)
    reference = models.CharField(max_length=120, blank=True,
                                 help_text='Transaction ID from the M-Pesa / bank message')
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payer_name = models.CharField(max_length=120, blank=True)
    payer_phone = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    file_url = models.URLField(max_length=500, blank=True)

    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    review_note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Proof for {self.invoice_id}: {self.reference or "-"} ({self.status})'
