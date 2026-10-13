"""
Grace — Afisa masoko.

Kila siku (baada ya saa 1 asubuhi) anaandaa post MOJA ya mitandao ya kijamii
(Facebook, Instagram, LinkedIn, WhatsApp Status). Chanzo kinazunguka:

    makala mpya ya blog  →  template ya marketplace  →  huduma / JamiiBot

Hakuna API ya mitandao iliyounganishwa bado, kwa hiyo Grace anaandaa na wewe
unachapisha: post inaingia kwenye ripoti ya asubuhi ya William tayari
kunakiliwa, na kwenye panel kuna kitufe cha "Nimechapisha".

Mara moja kwa wiki pia anafanya ukaguzi wa SEO kutoka Google Search Console
(apps/wafanyakazi/seo.py) na kuandaa vichwa vipya vya kurasa zinazopoteza mibofyo.
"""
from datetime import timedelta

from . import ai
from .board import found, site
from .models import Kazi
from .team import member

SLUG = 'grace'
START_HOUR = 7
STALE_DAYS = 2


def _used(ref):
    return Kazi.objects.filter(worker=SLUG, ref=ref).exists()


def _blog(now):
    from apps.models import BlogPost

    for post in (BlogPost.objects.filter(status='published', published_at__gte=now - timedelta(days=4))
                 .order_by('-published_at')[:10]):
        ref = f'blog:{post.pk}'
        if not _used(ref):
            return ref, f'Makala: {post.title}', (
                f"Makala mpya ya blog ya JamiiTek: \"{post.title}\". Muhtasari: {post.excerpt}"
            ), site(f'/blog/{post.slug}/')
    return None


def _template(day):
    from apps.models import WebsiteTemplate

    items = list(WebsiteTemplate.objects.filter(is_active=True).order_by('order', 'pk'))
    if not items:
        return None
    t = items[day % len(items)]
    try:
        link = site(t.get_absolute_url())
    except Exception:
        link = site('/templates/')
    return f'template:{t.pk}:{day}', f'Template: {t.name}', (
        f"Template ya tovuti '{t.name}' ({t.get_category_display()}) kwenye marketplace ya "
        f"JamiiTek. {t.description} Bei: hosted TSh {t.price_hosted_monthly:,}/mwezi, au "
        f"source code TSh {t.price_source_code:,}."
    ), link


SERVICES = (
    ('jamiibot', 'JamiiBot',
     'JamiiBot — chatbot ya AI inayojibu wateja kwenye WhatsApp ya biashara yako saa 24, kwa '
     'Kiswahili na Kiingereza, inajua huduma na bei zako na inakuunganisha na mteja anapohitaji binadamu.',
     '/bot/'),
    ('builder', 'Web builder',
     'JamiiTek web builder — tengeneza tovuti ya biashara yako mwenyewe kwa dakika chache, kwa '
     'msaada wa AI, bila kujua code. Unaweza kuunganisha domain yako.',
     '/get-started/'),
    ('services', 'Huduma za JamiiTek',
     'JamiiTek inatengeneza tovuti za kitaalamu, mifumo, hosting, domain na email za biashara — '
     'Dar es Salaam, kwa wateja wa Tanzania nzima.',
     '/service/'),
)


def _service(day):
    slug, label, facts, path = SERVICES[day % len(SERVICES)]
    return f'service:{slug}:{day}', label, facts, site(path)


WHATSAPP = 'https://wa.me/255629712678'

# Pembe ya post inazunguka kila siku ili ujumbe usijirudie: kila pembe ni
# sababu tofauti ya mteja kuchukua hatua leo.
ANGLES = (
    ('tatizo', 'Anza na TATIZO halisi la mfanyabiashara wa Tanzania (mfano: wateja wanakutafuta '
               'Google hawakupati, unajibu WhatsApp usiku kucha), kisha onyesha jinsi hiki kinavyolitatua.'),
    ('faida', 'Anza na MATOKEO ambayo mteja atapata (wateja zaidi, muda unaookolewa, kuaminika zaidi) — '
              'si orodha ya vipengele.'),
    ('swali', 'Anza kwa SWALI fupi linalomgusa msomaji moja kwa moja, kisha jibu kwa sentensi 2–3.'),
    ('hatua', 'Onyesha jinsi ilivyo RAHISI kuanza: hatua 3 fupi zenye namba (1️⃣ 2️⃣ 3️⃣).'),
    ('dhana', 'Anza kwa kuvunja DHANA potofu inayozuia watu (mfano: "website ni ghali", '
              '"chatbot ni kwa makampuni makubwa tu") — bila kubuni bei.'),
)


def _recent_openers(limit=6):
    """Mistari ya kwanza ya post za karibuni — Grace asirudie mwanzo uleule."""
    drafts = (Kazi.objects.filter(worker=SLUG, channel='social').exclude(draft='')
              .order_by('-created_at').values_list('draft', flat=True)[:limit])
    return [d.strip().splitlines()[0][:90] for d in drafts if d.strip()]


def _caption(facts, link, day=0):
    who = member(SLUG)
    angle, how = ANGLES[day % len(ANGLES)]
    recent = _recent_openers()
    avoid = ('\nPost za karibuni zilianza hivi — USIRUDIE mwanzo wala muundo huu:\n'
             + '\n'.join(f'- {r}' for r in recent)) if recent else ''
    text = ai.write(
        ai.persona(who['name'], who['role']),
        f"UKWELI (tumia huu tu — usibuni bei, takwimu wala ahadi):\n{facts}\n\n"
        f"Andika post ya leo kwa Kiswahili. Pembe: {how}{avoid}\n\n"
        "Muundo:\n"
        "• Facebook/Instagram/WhatsApp Status: mstari wa kwanza wenye nguvu; sentensi 2–4 fupi; "
        "ikiwezekana orodha fupi ya ✅ ya mambo 2–3; wito wa kuchukua hatua unaotaja WhatsApp "
        f"({WHATSAPP}); hashtags 4–6 (mfano #JamiiTek #Tanzania #Biashara). Emoji chache.\n"
        "• Kisha mstari wenye '———' peke yake, halafu 'LinkedIn:' na toleo fupi la kitaalamu "
        "(sentensi 2–3, bila emoji nyingi, hashtags 2–3).\n"
        "Usiweke link ya ukurasa — itaongezwa.",
        max_tokens=480, temperature=0.8)
    if not text:
        text = (f"{facts}\n\n💬 Tuandikie WhatsApp leo: {WHATSAPP}\n\n"
                "#JamiiTek #Tanzania #Biashara #Teknolojia")
    return f"{text}\n\n🔗 {link}"


def run(now):
    from . import seo
    result = _post(now)
    result.update(seo.run(now))      # ukaguzi wa SEO wa kila wiki (Search Console)
    return result


def _post(now):
    # Post za zamani ambazo hazikuchapishwa zinaondoka zenyewe (si rasimu za SEO —
    # hizo zinasubiri uamuzi wako hata wiki nzima)
    old = Kazi.objects.filter(worker=SLUG, status__in=Kazi.LIVE, channel='social',
                              created_at__lt=now - timedelta(days=STALE_DAYS))
    expired = 0
    for kazi in old:
        kazi.close(Kazi.DISMISSED, 'Muda wa post hii umepita.')
        expired += 1

    if now.hour < START_HOUR:
        return {'post': 'bado mapema', 'expired': expired}
    key = f'grace:post:{now.date().isoformat()}'
    if Kazi.objects.filter(key=key).exists():
        return {'post': 'tayari ipo', 'expired': expired}

    day = now.date().toordinal()
    order = {0: (_blog, _template, _service), 1: (_template, _blog, _service),
             2: (_service, _blog, _template)}[day % 3]
    pick = None
    for source in order:
        pick = source(now) if source is _blog else source(day)
        if pick:
            break
    if not pick:
        return {'post': 'hakuna chanzo', 'expired': expired}

    ref, label, facts, link = pick
    found(SLUG, key, f'Post ya leo: {label}', draft=lambda: _caption(facts, link, day),
          ref=ref, priority=2, detail=facts[:600], link=link, channel='social')
    return {'post': label, 'expired': expired}
