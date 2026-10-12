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


def _caption(facts, link):
    who = member(SLUG)
    text = ai.write(
        ai.persona(who['name'], who['role']),
        f"{facts}\n\nAndika post moja ya mitandao ya kijamii (Facebook/Instagram/WhatsApp Status) "
        "kwa Kiswahili: mstari wa kwanza wa kuvutia, sentensi 2-3 za faida kwa msomaji, wito wa "
        "kuchukua hatua, kisha hashtags 4-6 (mfano #JamiiTek #Tanzania). Emoji chache. "
        "Usiweke link — itaongezwa.",
        max_tokens=320, temperature=0.8)
    if not text:
        text = f"{facts}\n\n👉 Jifunze zaidi na uanze leo.\n\n#JamiiTek #Tanzania #Biashara #Teknolojia"
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
    found(SLUG, key, f'Post ya leo: {label}', draft=lambda: _caption(facts, link),
          ref=ref, priority=2, detail=facts[:600], link=link, channel='social')
    return {'post': label, 'expired': expired}
