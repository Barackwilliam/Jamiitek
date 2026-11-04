"""Kumbukumbu ya matukio ya mfumo (apps/activity.py): nani alifanya nini, na lini."""
from django.db import models


class ActivityEvent(models.Model):
    CUSTOMER, STAFF, SYSTEM = 'customer', 'staff', 'system'
    ACTORS = [(CUSTOMER, 'Customer'), (STAFF, 'You / staff'), (SYSTEM, 'System')]
    LEVELS = [('info', 'Info'), ('success', 'Success'), ('warning', 'Warning'), ('danger', 'Problem')]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=60, db_index=True)
    actor_kind = models.CharField(max_length=10, choices=ACTORS, default=SYSTEM, db_index=True)
    actor_name = models.CharField(max_length=150, blank=True)
    actor_email = models.CharField(max_length=254, blank=True)
    title = models.CharField(max_length=255)
    rows = models.JSONField(default=list, blank=True, help_text="[[label, value], ...] kwa email")
    link = models.CharField(max_length=500, blank=True)
    level = models.CharField(max_length=10, choices=LEVELS, default='info')
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    mode = models.CharField(max_length=10, default='digest')          # instant | digest | off (wakati wa tukio)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Activity'
        verbose_name_plural = 'Activity'

    def __str__(self):
        return f'{self.created_at:%d %b %H:%M} · {self.get_actor_kind_display()} · {self.title}'


class ActivityRule(models.Model):
    """Mmiliki anachagua kila aina ya tukio: email ya papo hapo, kwenye muhtasari wa siku, au kimya."""
    MODES = [('instant', 'Email right away'), ('digest', 'Daily summary only'), ('off', 'Off (log only)')]
    action = models.CharField(max_length=60, unique=True)
    label = models.CharField(max_length=120, blank=True)
    mode = models.CharField(max_length=10, choices=MODES, default='digest')

    class Meta:
        ordering = ['action']
        verbose_name = 'Activity setting'
        verbose_name_plural = 'Activity settings'

    def __str__(self):
        return f'{self.label or self.action}: {self.get_mode_display()}'


class ActivityDigest(models.Model):
    date = models.DateField(unique=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    events = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-date']
