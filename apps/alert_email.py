"""
Email za alerts za mfumo kwa mmiliki: muhtasari juu, kisha kadi moja kwa kila alert.

Template: emails/system_alerts.html. Telegram na WhatsApp zinaendelea kupokea maandishi
ya kawaida; hii ni kwa email tu.
"""
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

# rangi ya mstari, rangi ya kisanduku, alama, jina
LEVELS = {
    'critical': ('#dc2626', '#fef2f2', '🔴', 'Critical'),
    'warning': ('#d97706', '#fffbeb', '🟡', 'Warning'),
    'info': ('#0284c7', '#f0f9ff', '🔵', 'Info'),
    'ok': ('#16a34a', '#f0fdf4', '🟢', 'OK'),
}
ORDER = {'critical': 0, 'warning': 1, 'info': 2, 'ok': 3}

ALERTS_FOOTER = ('Checked every 30 minutes · a critical alert repeats at most every 6 hours, '
                 'a warning once a day, info once a week')


def admin_url(path='/manage/'):
    return getattr(settings, 'SITE_BASE_URL', 'https://www.jamiitek.com').rstrip('/') + path


def card(level, body='', *, tag='', title='', meta='', url='', action='', level_name=''):
    color, bg, icon, name = LEVELS.get(level, LEVELS['info'])
    return {'level': level, 'color': color, 'bg': bg, 'icon': icon, 'level_name': level_name or name,
            'tag': tag, 'title': title, 'meta': meta, 'body': body, 'url': url, 'action': action}


def _kicker(word):
    return f'{word} · {timezone.localtime():%d %b, %H:%M}'


def render(subject, cards, *, heading, kicker='System check', counts=False, footer_note=ALERTS_FOOTER,
           label='System alerts'):
    """(maandishi, html). `counts=True` inaonyesha visanduku vya idadi kwa kila kiwango."""
    cards = sorted(cards, key=lambda c: ORDER.get(c['level'], 9))
    boxes = []
    if counts:
        for level in ('critical', 'warning', 'info'):
            color, bg, _icon, name = LEVELS[level]
            boxes.append({'n': sum(c['level'] == level for c in cards), 'name': name, 'color': color, 'bg': bg})
    html = render_to_string('emails/system_alerts.html', {
        'subject': subject, 'label': label, 'kicker': _kicker(kicker), 'heading': heading, 'counts': boxes,
        'cards': cards, 'admin_url': admin_url(), 'footer_note': footer_note,
    })
    parts = [heading]
    for c in cards:
        head = f"{c['icon']} {c['level_name']}" + (f" · {c['tag']}" if c['tag'] else '')
        lines = [head] + [x for x in (c['title'], c['meta'], c['body']) if x]
        if c['url']:
            lines.append(f"{c['action'] or 'Open'}: {c['url']}")
        parts.append('\n'.join(lines))
    parts.append(f'Open JamiiTek admin: {admin_url()}')
    return '\n\n'.join(parts), html
