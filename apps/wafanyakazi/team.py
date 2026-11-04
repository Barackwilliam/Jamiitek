"""
Timu ya wafanyakazi wa AI wa JamiiTek.

Kila mfanyakazi ni moduli moja yenye `run(now)`. Wanafanya kazi kwa mpangilio
huu kila mzunguko — William wa mwisho, kwa sababu anasoma kazi za wenzake.
"""

TEAM = {
    'william': {
        'title': 'Mkurugenzi wa Uendeshaji', 'photo': 'wafanyakazi/team/william.webp',
        'motto': 'Hakuna kazi inayolala mezani — kila jambo lina mwenyewe na muda wake.',
        'name': 'William', 'role': 'Kiongozi mkuu', 'role_en': 'Team lead', 'icon': '👔', 'fa': 'fa-user-tie',
        'color': '#2563eb',
        'duty': 'Anasimamia timu, anawakumbusha kazi zilizokwama na kukuletea ripoti '
                'ya asubuhi na jioni.',
    },
    'ibrahimu': {
        'title': 'Kiongozi wa Huduma kwa Wateja', 'photo': 'wafanyakazi/team/ibrahimu.webp',
        'motto': 'Kila mteja anastahili jibu la haraka na la heshima.',
        'name': 'Ibrahimu', 'role': 'Mhudumu wa wateja', 'role_en': 'Customer care', 'icon': '💬', 'fa': 'fa-headset',
        'color': '#0e9f6e',
        'duty': 'Anafuatilia mazungumzo ya JamiiBot: wateja wanaosubiri binadamu, maswali '
                'ambayo bot haikuyajua, na wateja wenye nia ya kununua.',
    },
    'selvester': {
        'title': 'Meneja wa Mauzo', 'photo': 'wafanyakazi/team/selvester.webp',
        'motto': 'Lead isiyofuatiliwa ni pesa iliyoachwa mezani.',
        'name': 'Selvester', 'role': 'Afisa mauzo', 'role_en': 'Sales', 'icon': '🎯', 'fa': 'fa-bullseye',
        'color': '#7c3aed',
        'duty': 'Anafuatilia leads, ujumbe wa fomu ya mawasiliano, malipo yaliyoachwa '
                'njiani na tovuti za builder ambazo hazijachapishwa.',
    },
    'grace': {
        'title': 'Meneja wa Masoko na Mitandao', 'photo': 'wafanyakazi/team/grace.webp',
        'motto': 'Kila siku JamiiTek ionekane, isikike na ikumbukwe.',
        'name': 'Grace', 'role': 'Afisa masoko', 'role_en': 'Marketing', 'icon': '📣', 'fa': 'fa-bullhorn',
        'color': '#db2777',
        'duty': 'Anaandaa post ya kila siku ya mitandao ya kijamii kutoka kwenye blog, '
                'templates na huduma za JamiiTek, na kila Jumatatu anakagua SEO ya Google '
                '(Search Console) na kuandaa vichwa vipya vya kurasa zinazopoteza mibofyo, '
                'pamoja na maelezo ya kipekee ya kila template.',
    },
    'diana': {
        'title': 'Meneja wa Fedha na Ofisi', 'photo': 'wafanyakazi/team/diana.webp',
        'motto': 'Hesabu safi, malipo kwa wakati, ofisi iliyopangika.',
        'name': 'Diana', 'role': 'Fedha na ofisi', 'role_en': 'Finance and office', 'icon': '💰', 'fa': 'fa-coins',
        'color': '#d97706',
        'duty': 'Anafuatilia invoice zinazodaiwa, malipo ya JamiiBot yanayosubiri '
                'kuthibitishwa na mapato ya wiki.',
    },
}

# Mpangilio wa kazi kila mzunguko.
ORDER = ('diana', 'selvester', 'ibrahimu', 'grace', 'william')

CHOICES = [(slug, f"{w['name']} — {w['role']}") for slug, w in TEAM.items()]


def member(slug):
    return TEAM.get(slug, {'name': slug.title(), 'role': '', 'icon': '•', 'fa': 'fa-user',
                           'color': '#64748b', 'duty': '', 'title': '', 'photo': '', 'motto': ''})


def signature(slug, lang='sw'):
    """Sahihi ya mfanyakazi. Email za wateja ni kwa Kiingereza (lang='en')."""
    w = member(slug)
    role = (w.get('role_en') or w['role']) if lang == 'en' else w['role']
    return f"{w['name']}\n{role} — JamiiTek"
