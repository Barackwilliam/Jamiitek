"""
Ukaguzi wa SEO wa Grace (Google Search Console), sasa hivi:

    python manage.py seo_ukaguzi
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.wafanyakazi import seo


class Command(BaseCommand):
    help = 'Endesha ukaguzi wa SEO wa Search Console sasa hivi (hata kama wiki hii umeshafanyika).'

    def handle(self, *args, **options):
        result = seo.audit(timezone.localtime(), force=True)
        for key, value in result.items():
            self.stdout.write(f'{key}: {value}')
