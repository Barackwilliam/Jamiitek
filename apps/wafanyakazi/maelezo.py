"""
Grace — maelezo ya kipekee ya kila template (SEO).

Kurasa za templates (/templates/<slug>/) zinashiriki maandishi mengi ya jumla
(vipengele, FAQ, "Customize in the Builder…"). Google inaziona kama nakala na
haiziorodheshi (Search Console: "Crawled – currently not indexed").

Dawa ni aya 2–3 za KIPEKEE kwa kila template (WebsiteTemplate.long_description),
zinazoonyeshwa juu ya maandishi ya jumla. Grace anaziandika kutoka kwa template
YENYEWE — HTML ya demo (vichwa, sehemu, huduma inazoonyesha), jina, jamii na
maelezo mafupi — bila kubuni bei, maoni ya wateja wala vipengele visivyokuwepo.

Rasimu inakuja "Mezani kwako"; ukikubali, inaingia kwenye ukurasa papo hapo
(apps/wafanyakazi/seo.py → apply) na Bing/ChatGPT search zinajulishwa.
"""
import re

from . import ai
from .board import found
from .models import Kazi
from .team import member

SLUG = 'grace'
START_HOUR = 7
PER_DAY = 2            # rasimu ngapi kwa siku — usimfurike mmiliki
MIN_LENGTH = 300       # maelezo mafupi kuliko haya yanahesabika kama hayapo
SOURCE_CHARS = 2500    # herufi za maandishi ya demo ambazo AI inasoma


def _demo_text(html):
    """Vichwa na maandishi yanayoonekana kwenye demo ya template."""
    html = re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>', ' ', html or '')
    heads = [re.sub(r'<[^>]+>', ' ', h) for h in re.findall(r'(?is)<h[1-3][^>]*>(.*?)</h[1-3]>', html)]
    heads = [re.sub(r'\s+', ' ', h).strip() for h in heads if h.strip()]
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()
    return heads[:20], text[:SOURCE_CHARS]


def _ref(tpl):
    return f'tpldesc:{tpl.pk}'


def candidates():
    """Templates hai zisizo na maelezo ya kipekee wala rasimu (iliyo hai au iliyokataliwa)."""
    from apps.models import WebsiteTemplate

    handled = set(Kazi.objects.filter(worker=SLUG, ref__startswith='tpldesc:')
                  .values_list('ref', flat=True))
    out = []
    for tpl in WebsiteTemplate.objects.filter(is_active=True).order_by('order', 'pk'):
        if len((tpl.long_description or '').strip()) >= MIN_LENGTH or _ref(tpl) in handled:
            continue
        out.append(tpl)
    return out


def draft_for(tpl):
    """Rudisha (maandishi, maneno_yasiyo_kwenye_template) — '' kama AI haipatikani."""
    from apps import template_seo as ts

    from .seo import unsupported

    info = ts.cat_info(tpl)
    heads, text = _demo_text(tpl.preview_html)
    who = member(SLUG)
    body = ai.write(
        ai.persona(who['name'], who['role']) + ' Wewe pia ni mwandishi wa SEO wa kurasa za bidhaa.',
        f"Template ya website: \"{tpl.name}\" — jamii: {tpl.category_plain()} ({info['noun']}).\n"
        f"Maelezo mafupi: {ts.plain(tpl.description)}\n"
        f"Vichwa vya sehemu kwenye demo: {'; '.join(heads) or '—'}\n"
        f"Maandishi ya demo (mwanzo wake):\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Andika maelezo ya KIPEKEE ya template hii kwa ukurasa wake wa marketplace: aya 2–3, "
        "maneno 120–220 kwa jumla, kwa KIINGEREZA, aya zikitenganishwa na mstari mtupu.\n"
        "SHERIA:\n"
        "1. Eleza kile kilichopo kwenye demo hii hasa — mtindo, sehemu zake, na aina ya biashara "
        "inayofaa — ili maelezo yasifanane na ya template nyingine.\n"
        "2. Usibuni bei, maoni ya wateja, takwimu, tuzo wala vipengele visivyoonekana kwenye demo.\n"
        "3. Taja kwa kawaida neno la utafutaji kama "
        f"\"{info['noun']} website template\" mara moja au mbili — si kulazimisha.\n"
        "4. Usiweke vichwa, orodha wala markdown — aya tu.",
        max_tokens=520, temperature=0.5)
    body = (body or '').strip()
    body = re.sub(r'(?m)^\s*(#+|\*\*|[-*•]\s)', '', body).strip()
    if len(body) < 200:
        return '', []
    snap = {'title': tpl.name, 'description': tpl.description or '', 'text': ' '.join(heads) + ' ' + text}
    return body, unsupported(body, snap, [{'query': f"{info['noun']} website template {tpl.category_plain()}"}])


def run(now):
    if now.hour < START_HOUR:
        return {'maelezo': 'bado mapema'}
    today = Kazi.objects.filter(worker=SLUG, ref__startswith='tpldesc:',
                                created_at__date=now.date()).count()
    made = 0
    for tpl in candidates():
        if today + made >= PER_DAY:
            break
        body, risky = draft_for(tpl)
        if not body:
            break          # AI haipatikani — maandishi ya jumla hayasaidii, subiri
        detail = (f"Template: {tpl.name} ({tpl.category_plain()}). Ukurasa wake unashiriki maandishi "
                  "mengi ya jumla na templates nyingine, kwa hiyo Google inauona kama nakala. "
                  "Maelezo haya ya kipekee yataonyeshwa juu ya ukurasa.")
        if risky:
            detail = ('⚠️ Maneno yasiyo kwenye demo ya template: ' + ', '.join(risky[:8])
                      + '. Hakikisha ni sahihi kabla ya kukubali.\n\n' + detail)
        try:
            link = tpl.get_absolute_url()
        except Exception:
            link = '/templates/'
        from .board import site
        found(SLUG, f'grace:maelezo:{tpl.pk}', f'Maelezo ya kipekee: {tpl.name}', draft=body,
              ref=_ref(tpl), priority=2, detail=detail, link=site(link), channel='seo')
        made += 1
    return {'maelezo': f'rasimu mpya {made}'}
