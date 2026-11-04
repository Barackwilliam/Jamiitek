"""
Ukaguzi wa afya ya sessions za WhatsApp.

KWA NINI HII IPO

Tarehe 15 Sep 2026, session ya Tembo ilikufa. Dashboard ilionyesha
kijani. Bridge ilisema `IMEUNGANISHWA`. Hakuna ujumbe uliofika kwa
saa kadhaa, na hakuna aliyejua — tuligundua kwa uchunguzi wa mkono.

`BotConfig.connection_status` ilikuwa inasasishwa **mtu akifungua
ukurasa** pekee. Hakuna anayefungua ukurasa saa nne usiku.

MAMBO MAWILI TOFAUTI YANAYOANGALIWA

1. Session iko chini — status si `connected`. Rahisi kuona.

2. Session ni MAITI — `connected` lakini WhatsApp haiongei nayo.
   Hii ndiyo hatari zaidi, kwa sababu kila kiashiria kinaonyesha
   afya njema. Tunaigundua kwa `silent_seconds`: socket hai daima
   ina kelele (presence, receipts, chats.update) hata bila mtu
   kuandika. Ikinyamaza dakika 30+, imekufa.

TAARIFA MOJA, SI KILA DAKIKA 15

`alerted_at` inazuia kurudia. Taarifa inatumwa mara moja session
inaposhuka, na mara moja tena inaporudi. Kati ya hapo, kimya —
taarifa inayorudia kila dakika 15 inafundisha mtu kuipuuza.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

# Dakika za kunyamaza kabla tuseme session ni maiti
ZOMBIE_MINUTES = 30

# Dakika za kuwa chini kabla ya kutuma taarifa. Reconnect ya kawaida
# inachukua sekunde; kutuma taarifa mara moja kungezalisha kelele.
ALERT_AFTER_MINUTES = 10


class Command(BaseCommand):
    help = "Vuta hali halisi ya sessions kutoka bridge, tuma taarifa zikishuka"

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true')
        parser.add_argument('--force-alert', action='store_true',
                            help='Tuma taarifa hata kama imeshatumwa (kwa majaribio)')

    def handle(self, *args, **opts):
        from apps.chatbot.models import BotConfig
        from apps.chatbot import bridge
        from apps import notify

        quiet = opts['quiet']

        if not bridge.is_configured():
            if not quiet:
                self.stdout.write(self.style.WARNING('Bridge haijasanidiwa — imerukwa.'))
            return

        data = bridge.list_sessions()
        if not data.get('success'):
            # Bridge yenyewe haipatikani — hiyo ni tatizo kubwa kuliko
            # session moja kushuka.
            msg = (f"🔴 *Bridge haipatikani*\n\n{data.get('error', 'haijulikani')}\n\n"
                   f"Bot ZOTE haziwezi kupokea wala kutuma jumbe.")
            self.stderr.write(self.style.ERROR('Bridge haipatikani: ' + str(data.get('error'))))
            notify.notify(msg)
            return

        live = {s['session']: s for s in data.get('sessions', [])}
        now = timezone.now()
        down, recovered, ok = [], [], 0

        bots = (BotConfig.objects
                .filter(is_active=True, status='active', autostart=True)
                .exclude(session_name='')
                .select_related('client'))

        for bot in bots:
            s = live.get(bot.session_name)
            problem = self._diagnose(bot, s)

            if problem:
                if not bot.down_since:
                    bot.down_since = now
                self._apply(bot, s, problem)

                minutes = int((now - bot.down_since).total_seconds() // 60)
                due = minutes >= ALERT_AFTER_MINUTES
                fresh = not bot.alerted_at or bot.alerted_at < bot.down_since

                if (due and fresh) or opts['force_alert']:
                    down.append((bot, problem, minutes))
                    bot.alerted_at = now
                bot.save(update_fields=['down_since', 'alerted_at', 'connection_status',
                                        'connected_number', 'last_seen_at'])
            else:
                was_down = bool(bot.down_since)
                bot.down_since = None
                self._apply(bot, s, None)
                if was_down and bot.alerted_at:
                    recovered.append(bot)
                    bot.alerted_at = None
                bot.save(update_fields=['down_since', 'alerted_at', 'connection_status',
                                        'connected_number', 'last_seen_at'])
                ok += 1

        if down:
            notify.notify(self._down_message(down))
            for bot, problem, mins in down:      # mwenye bot ajue pia — awali taarifa ilikuja JamiiTek peke yake
                _email_client_down(bot)
        if recovered:
            notify.notify(self._recovered_message(recovered))

        if not quiet:
            self.stdout.write(self.style.SUCCESS(
                f"Sessions: {ok} sawa · {len(down)} taarifa zimetumwa · "
                f"{len(recovered)} zimerudi"))
            for bot, problem, mins in down:
                self.stdout.write(f"  🔴 {bot.bot_name}: {problem} (dakika {mins})")

    # ──────────────────────────────────────────────────────────

    def _diagnose(self, bot, s):
        """Inarudisha maelezo ya tatizo, au None ikiwa ni sawa."""
        if s is None:
            return 'haipo kwenye bridge — haijaanzishwa'

        status = s.get('status')
        if status != 'connected':
            names = {
                'waiting_qr':   'inasubiri QR — mteja ajaunganisha',
                'logged_out':   'imetolewa kwenye simu — QR mpya inahitajika',
                'disconnected': 'imekatika',
                'starting':     'inaanza',
            }
            base = names.get(status, status)
            err = s.get('last_error')
            return f"{base}{' — ' + err if err else ''}"

        # Imeunganishwa. Lakini je, WhatsApp inaongea nayo kweli?
        silent = s.get('silent_seconds')
        if silent is not None and silent > ZOMBIE_MINUTES * 60:
            return (f"MAITI — inaonekana imeunganishwa lakini WhatsApp haijatuma "
                    f"tukio kwa dakika {silent // 60}. Scan QR upya.")

        if s.get('event_total', 1) == 0:
            return 'MAITI — hakuna tukio hata moja kutoka WhatsApp. Scan QR upya.'

        return None

    def _apply(self, bot, s, problem):
        from django.utils import timezone as tz
        bot.connection_status = (s or {}).get('status') or 'disconnected'
        number = (s or {}).get('number') or ''
        if number:
            bot.connected_number = number
        if not problem:
            bot.last_seen_at = tz.now()

    def _down_message(self, down):
        L = [f"🔴 *Bot {len(down)} zina tatizo*", ""]
        for bot, problem, mins in down:
            dur = f"dakika {mins}" if mins < 60 else f"saa {mins // 60}"
            L.append(f"*{bot.bot_name}* — {bot.client.business_name}")
            L.append(f"  {problem}")
            L.append(f"  imekuwa hivi {dur}")
            L.append("")
        L.append(_sessions_url())
        return "\n".join(L)

    def _recovered_message(self, bots):
        L = [f"🟢 *Bot {len(bots)} zimerudi*", ""]
        for bot in bots:
            L.append(f"• {bot.bot_name} — {bot.connected_number or 'imeunganishwa'}")
        return "\n".join(L)


def _sessions_url():
    from django.conf import settings
    base = (getattr(settings, 'SITE_URL', '') or 'https://www.jamiitek.com').rstrip('/')
    return f"{base}/manage/chatbot/sessions/"


def _email_client_down(bot):
    """Email kwa mwenye bot (mteja) kwamba bot yake imekatika kutoka WhatsApp, na jinsi ya kuirudisha.
    Mara moja kwa kila tukio (alerted_at). Hakuna email ya mteja -> hakuna kinachotumwa (si kwa JamiiTek)."""
    client = getattr(bot, 'client', None)
    to = (getattr(client, 'email', '') or '').strip()
    if not to and getattr(client, 'user', None):
        to = (client.user.email or '').strip()
    if not to:
        return False
    from django.conf import settings
    from apps.utils.customer_email import send_customer_email
    base = (getattr(settings, 'SITE_URL', '') or 'https://www.jamiitek.com').rstrip('/')
    name = (getattr(client, 'full_name', '') or '').split(' ')[0]
    return send_customer_email(
        to, f'⚠️ {bot.bot_name} is not connected to WhatsApp',
        (f'Hi {name},' if name else 'Hello,')
        + f'\n\nYour JamiiBot "{bot.bot_name}" has lost its connection to WhatsApp, so it is not replying to '
        + 'your customers right now.\n\nTo reconnect, open the Connect page and scan the QR code with the '
        + 'WhatsApp of your business.',
        alert={'kind': 'warning', 'title': 'Action needed', 'text': 'Your customers are not getting replies.'},
        button=('Reconnect WhatsApp', f'{base}/chatbot/connect/'), category='bot_down', chip=('⚠ Not connected', 'warning'),
    )
