"""
Kumbusho za duka la JamiiBot (apps/chatbot/shop.send_reminders).

    saa 1 / saa 24 — mteja aliyeagiza bila kulipa anakumbushwa (na njia za malipo)
    saa 2          — mteja alisema amelipa, mmiliki anakumbushwa kuhakiki na kubonyeza Mark paid

Hakuna kinachowekwa "Paid" hapa — mmiliki ndiye anathibitisha malipo.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Kumbusha wateja wasiolipa na wamiliki wasiothibitisha malipo"

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        from apps.chatbot.shop import send_reminders
        sent = send_reminders()
        if not opts['quiet']:
            self.stdout.write(f"Kumbusho: wateja {sent['customers']} · wamiliki {sent['owners']}")
