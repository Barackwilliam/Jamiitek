"""
Nyaraka rasmi za kampuni (cheti cha BRELA, TIN, leseni, n.k.).

Zinahifadhiwa NDANI YA DATABASE, si Supabase Storage: bucket ya Supabase ni
ya umma (yeyote mwenye link anafungua), na cheti chenye sahihi ya msajili
hakipaswi kukaa hapo. Hapa zinafunguliwa tu na staff aliyeingia Manage.
"""
from django.conf import settings
from django.db import models


class CompanyDocument(models.Model):
    CATEGORIES = [
        ('registration', 'Usajili (BRELA)'),
        ('tax', 'Kodi (TRA / TIN)'),
        ('license', 'Leseni ya biashara'),
        ('bank', 'Benki'),
        ('contract', 'Mikataba'),
        ('other', 'Nyingine'),
    ]

    title = models.CharField(max_length=160)
    category = models.CharField(max_length=20, choices=CATEGORIES, default='other')
    number = models.CharField('Namba ya hati', max_length=80, blank=True)
    issued_on = models.DateField('Tarehe ya kutolewa', null=True, blank=True)
    expires_on = models.DateField('Inaisha', null=True, blank=True)
    notes = models.TextField(blank=True)

    file_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=60)
    size = models.PositiveIntegerField(default=0)
    data = models.BinaryField(editable=False)

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', '-issued_on', '-uploaded_at']
        verbose_name = 'Company document'

    def __str__(self):
        return self.title

    @property
    def is_pdf(self):
        return self.content_type == 'application/pdf'
