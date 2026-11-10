"""
Ankara za renewal (hosting, domain, email hosting) + vikumbusho vyake.

    python manage.py renewal_invoices            # tengeneza, tuma, kumbusha
    python manage.py renewal_invoices --dry      # onyesha tu kitakachotengenezwa
    python manage.py renewal_invoices --no-send  # tengeneza bila kutuma

Inaendeshwa kila siku na apps/daily_tasks.py. Maelezo yote: apps/renewals.py.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create renewal invoices for services ending soon, and send reminders'

    def add_arguments(self, parser):
        parser.add_argument('--dry', action='store_true')
        parser.add_argument('--no-send', action='store_true')
        parser.add_argument('--quiet', action='store_true')
        parser.add_argument('--fix-only', action='store_true',
                            help='Only correct old invoices billed for many months (runs every 30 min)')

    def handle(self, *args, **opts):
        from apps import renewals

        if opts['dry']:
            for client, items in renewals.create_invoices(dry_run=True):
                self.stdout.write(f'{client.name}:')
                for i in items:
                    self.stdout.write(f'   {i["desc"]} — TZS {i["amount"]:,.0f}')
            return

        fixed = renewals.fix_overbilled(send=not opts['no_send'])
        if fixed:
            self.stdout.write(self.style.WARNING(
                f'Corrected {len(fixed)} renewal invoice(s) to one month: '
                + ', '.join(i.invoice_number for i in fixed)))
        stale = renewals.cancel_stale()
        if stale and not opts['quiet']:
            self.stdout.write(f'{stale} renewal invoice(s) closed — service was renewed another way.')
        if opts['fix_only']:
            return
        made = renewals.create_invoices(send=not opts['no_send'])
        reminded = renewals.send_reminders() if not opts['no_send'] else 0
        if not opts['quiet'] or made or reminded:
            self.stdout.write(self.style.SUCCESS(
                f'Renewal invoices: {len(made)} created, {reminded} reminders sent.'))
