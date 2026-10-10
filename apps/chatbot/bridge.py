"""
Mteja wa Bridge — Django -> Baileys.

`BaileysHandler` ina INTERFACE ILE ILE ya `WhatsAppHandler` ya Meta:
`is_configured()`, `send_text()`, `send_interactive_list()`,
`mark_as_read()`. Hiyo ni kwa makusudi — `_process_message` yenye
state machine yake yote inabaki kama ilivyo. Kilichobadilika ni
njia ya kutuma, si mantiki ya kujibu.

Tofauti moja ya kweli: Baileys haina interactive list inayoaminika.
WhatsApp imepunguza msaada wake kwa clients zisizo rasmi na mara
nyingi orodha haionekani kabisa kwa mteja. Kwa hiyo
`send_interactive_list()` inaandika orodha kama maandishi yenye
namba. Mteja anaweza kujibu "2" na bot ikaelewa — jambo ambalo
interactive list ilikuwa inalifanya hata hivyo.
"""
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger('chatbot.bridge')

TIMEOUT = 15


def _base_url():
    return (getattr(settings, 'BRIDGE_URL', '') or '').rstrip('/')


def _key():
    return getattr(settings, 'BRIDGE_API_KEY', '') or ''


def is_configured():
    return bool(_base_url() and _key())


def _request(method, path, **kwargs):
    """Ombi moja kwenda bridge. Kamwe halitupi exception."""
    if not is_configured():
        return {'success': False, 'error': 'BRIDGE_URL au BRIDGE_API_KEY haijawekwa'}

    url = f"{_base_url()}{path}"
    headers = {'X-Bridge-Key': _key(), 'Content-Type': 'application/json'}
    try:
        resp = requests.request(method, url, headers=headers,
                                timeout=kwargs.pop('timeout', TIMEOUT), **kwargs)
        try:
            data = resp.json()
        except ValueError:
            return {'success': False, 'error': f'jibu si JSON ({resp.status_code})'}
        if resp.status_code >= 400 and 'error' not in data:
            data['error'] = f'HTTP {resp.status_code}'
        data.setdefault('success', resp.status_code < 400)
        return data
    except requests.Timeout:
        return {'success': False, 'error': 'bridge haijajibu kwa wakati'}
    except requests.RequestException as e:
        return {'success': False, 'error': str(e)}


# ══════════════════════════════════════════════════════════════
#  UDHIBITI WA SESSIONS
# ══════════════════════════════════════════════════════════════

def health(timeout=8):
    return _request('GET', '/health', timeout=timeout)


def list_sessions(timeout=TIMEOUT):
    return _request('GET', '/sessions', timeout=timeout)


def session_status(name, timeout=TIMEOUT):
    return _request('GET', f'/sessions/{name}', timeout=timeout)


def session_qr(name):
    """Inarudisha QR kama data URL. Ndiyo pekee inayobeba picha."""
    return _request('GET', f'/sessions/{name}/qr', timeout=20)


def start_session(name):
    return _request('POST', f'/sessions/{name}/start', timeout=40)


def restart_session(name):
    return _request('POST', f'/sessions/{name}/restart', timeout=40)


def stop_session(name):
    return _request('POST', f'/sessions/{name}/stop', timeout=20)


def logout_session(name):
    """Inafuta auth. Mteja atalazimika kuscan QR upya."""
    return _request('POST', f'/sessions/{name}/logout', timeout=40)


def resolve_phones(session, phones):
    """namba -> {exists, jid, lid}. Inahitaji session iwe hai."""
    return _request('POST', '/resolve',
                    json={'session': session, 'phones': list(phones)}, timeout=25)


def resolve_owner_lid(bot):
    """
    Jaza `owner_lid` mara moja. Inarudisha LID au tupu.

    Baileys 6.7.18 haina LID -> namba, lakini ina namba -> LID. Kwa
    hiyo tunatafsiri upande huu, kisha tunalinganisha LID na LID.
    """
    if bot.owner_lid:
        return bot.owner_lid
    phone = bot.owner_digits
    if not phone:
        return ''

    data = resolve_phones(bot.session_name, [phone])
    if not data.get('success'):
        logger.warning('[%s] kutafsiri LID ya mmiliki kumeshindwa: %s',
                       bot.session_name, data.get('error'))
        return ''

    lid = (data.get('resolved', {}).get(phone, {}) or {}).get('lid', '')
    if lid:
        bot.owner_lid = lid[:25]
        bot.save(update_fields=['owner_lid'])
        logger.info('[%s] LID ya mmiliki: %s -> %s', bot.session_name, phone, lid)
    return lid


def prune_keys(days=30):
    return _request('POST', '/prune', json={'days': days}, timeout=60)


# ══════════════════════════════════════════════════════════════
#  HANDLER — inachukua nafasi ya WhatsAppHandler
# ══════════════════════════════════════════════════════════════

class BaileysHandler:
    """
    Inatuma jumbe kupitia bridge kwa niaba ya bot moja.

    `jid` inahitajika kwa `mark_as_read` pekee — Baileys inahitaji
    kujua mazungumzo, si message id peke yake (Meta ilihitaji id tu).
    """

    def __init__(self, bot_config, jid=None):
        self.bot = bot_config
        self.session = bot_config.session_name
        self.jid = jid

    def is_configured(self):
        return bool(is_configured() and self.session)

    def send_text(self, to, message, jid=None):
        """
        `jid` inatangulia `to` inapopatikana.

        WhatsApp sasa inatumia LID (tarakimu 15) badala ya namba kwa
        wateja wengi. LID inaishia `@lid`, si `@s.whatsapp.net`. Bridge
        ilikuwa inaijenga JID kutoka tarakimu, ikizalisha
        `158351803576497@s.whatsapp.net` — isiyo halali. Jibu halikwenda
        popote, na Django ilidhani imetuma.

        JID halisi tuliyoipokea ndiyo sahihi daima.
        """
        if not self.is_configured():
            logger.warning('Bot %s: bridge haijasanidiwa (BRIDGE_URL/BRIDGE_API_KEY)',
                           self.bot.bot_name)
            return {'success': False, 'error': 'Not configured'}

        # `jid` ni ya KILA WITO, si ya handler.
        #
        # `self.jid` ni ya mazungumzo yaliyoanzisha wito huu. Kuitumia
        # kwa kila `send_text` kulipeleka taarifa ya handoff kwa MTEJA
        # badala ya mmiliki — jid ilishinda `to`.
        #
        # Sasa: `_process_message` inapitisha jid inapojibu mteja;
        # `notify_owner` haipitishi, kwa hiyo `to` inatumika.
        payload = {'session': self.session, 'to': to, 'text': message}
        if jid:
            payload['jid'] = jid

        data = _request('POST', '/send', json=payload)
        if not data.get('success'):
            logger.error('Bot %s: kutuma kwa %s kumeshindwa — %s',
                         self.bot.bot_name, jid or to, data.get('error'))
        return data

    def send_interactive_list(self, to, header, body, button_text, sections):
        """
        Baileys: orodha inaandikwa kama maandishi yenye namba.

        Angalia docstring ya module kwa sababu. Namba zinabaki muhimu —
        mteja anaweza kujibu "2" badala ya kuandika jina la huduma.
        """
        lines = [f'*{header}*', '', body, '']
        n = 0
        for section in sections or []:
            title = section.get('title')
            if title:
                lines.append(f'_{title}_')
            for row in section.get('rows', []):
                n += 1
                line = f"{n}. *{row.get('title', '')}*"
                desc = row.get('description')
                if desc:
                    line += f"\n   {desc}"
                lines.append(line)
            lines.append('')

        if not n:
            return {'success': False, 'error': 'Hakuna vipengele'}

        lines.append('Andika namba ya huduma unayotaka, au uliza swali lako moja kwa moja.')
        return self.send_text(to, '\n'.join(lines).strip())

    def send_interactive_buttons(self, to, body, buttons):
        """Vitufe navyo vinakuwa maandishi — sababu ile ile."""
        lines = [body, '']
        for i, b in enumerate(buttons[:3], start=1):
            lines.append(f"{i}. {b.get('title', '')}")
        return self.send_text(to, '\n'.join(lines).strip())

    def mark_as_read(self, message_id):
        if not self.is_configured() or not self.jid or not message_id:
            return {'success': False}
        return _request('POST', '/read', json={
            'session': self.session,
            'jid': self.jid,
            'message_id': message_id,
        }, timeout=8)

    def get_media_url(self, media_id):
        """
        Baileys hupakua media yenyewe kupitia socket, si kwa URL.
        Bado haijatekelezwa — inarudisha tupu ili code inayoiita
        isivunjike.
        """
        return ''
