"""
Maarifa — bot inajifunza, lakini mmiliki ndiye anayeamua.

MZUNGUKO:

    mteja anauliza
        -> bot inashindwa
        -> swali linahifadhiwa (KnowledgeGap)
        -> AI inaandika RASIMU ya jibu
        -> mmiliki anasoma, anahariri, anakubali
        -> inakuwa BotFAQ
        -> BotFAQ inaingia kwenye build_system_prompt
        -> bot inajua wakati ujao

KWA NINI MMILIKI YUKO KATIKATI

Bot inayojiandikia maarifa yenyewe itajifunza jibu baya mapema au
baadaye. Mteja akiandika "saruji ni 15,000" na bot ikalichukua kama
ukweli, mteja wa kesho anaambiwa bei isiyo ya mmiliki. Biashara
haitajua imesema nini kwa niaba yake.

Hatua ya kukubali si urasimu — ndiyo inayofanya mmiliki aweze
kusimama nyuma ya kila neno bot inalosema.

KUTAMBUA KUSHINDWA

Njia tatu, zote za bure (hakuna wito wa ziada wa AI):
  1. AI imerudisha kosa -> fallback_msg imetumwa
  2. Jibu la bot lina maneno ya kutojua ("sijui", "wasiliana nasi")
  3. Mteja ameomba binadamu — hilo lenyewe ni kushindwa

Kuuliza AI "je, ulijibu vizuri?" kungegharimu wito mara mbili kwa
kila ujumbe. Kwa bot 30 zenye jumbe 1,000 kwa mwezi, hiyo ni
maradufu ya gharama kwa faida ndogo.
"""
import logging
import os
import re

import requests
from django.conf import settings

logger = logging.getLogger('chatbot.knowledge')

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

# Maneno yanayoonyesha bot haikujua — Kiswahili na Kiingereza
UNSURE = [
    'sijui', 'sina uhakika', 'sina taarifa', 'sijaelewa', 'sielewi',
    'siwezi kukusaidia', 'siwezi kujibu', 'wasiliana na', 'wasiliana nasi',
    'piga simu', 'nitakuunganisha',
    "i don't know", "i dont know", "i'm not sure", "im not sure",
    "i don't have", "i cannot help", "i can't help", "contact us",
    "reach out to", "please contact",
]

# Maswali mafupi sana si maswali
MIN_LENGTH = 8
MAX_LENGTH = 500


def normalize(text):
    """
    Funguo ya kuunganisha maswali yanayofanana.

    Ni ya wastani kwa makusudi: inaondoa alama, inasawazisha nafasi,
    na inaondoa maneno ya heshima yanayotangulia. Maswali
    yanayofanana KABISA yanaungana; yanayokaribiana yanaungwa
    baadaye na AI kwenye `analyze_gaps`.
    """
    t = (text or '').lower().strip()
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    for lead in ('tafadhali ', 'samahani ', 'habari ', 'hujambo ',
                 'please ', 'hi ', 'hello ', 'hey '):
        if t.startswith(lead):
            t = t[len(lead):]
    return t[:300]


def looks_unanswered(reply):
    low = (reply or '').lower()
    return any(kw in low for kw in UNSURE)


def watch(bot, conv, question, reply, result=None):
    """
    Inaitwa baada ya kila jibu la AI. Kimya kabisa isipokuwa
    kuna pengo halisi.
    """
    try:
        _watch(bot, conv, question, reply, result or {})
    except Exception:
        # Kamwe isivunje mazungumzo ya mteja kwa sababu ya kujifunza
        logger.exception('knowledge.watch imeshindwa')


def _watch(bot, conv, question, reply, result):
    q = (question or '').strip()
    if len(q) < MIN_LENGTH or len(q) > MAX_LENGTH:
        return
    if q.startswith('['):          # lebo za media, si maswali
        return

    if not result.get('success'):
        source = 'fallback'
    elif looks_unanswered(reply):
        source = 'unsure'
    else:
        return

    record(bot, conv, q, reply, source)


def record(bot, conv, question, reply='', source='unsure'):
    """Hifadhi pengo, au ongeza hesabu kama linajulikana."""
    from .models import KnowledgeGap

    key = normalize(question)
    if not key:
        return None

    gap, created = KnowledgeGap.objects.get_or_create(
        bot=bot, normalized=key,
        defaults={
            'question': question[:MAX_LENGTH],
            'bot_reply': (reply or '')[:2000],
            'source': source,
            'example_conversation': conv,
        },
    )
    if not created:
        # Swali lililojibiwa likirudi, linafunguka tena — jibu
        # halikuwa la kutosha
        gap.times_asked += 1
        fields = ['times_asked', 'last_asked_at']
        if gap.status == 'dismissed':
            pass                      # mmiliki aliamua; heshimu uamuzi wake
        elif gap.status == 'answered':
            gap.status = 'open'
            fields.append('status')
        gap.save(update_fields=fields)
    else:
        logger.info('[%s] pengo jipya: %s', bot.session_name, question[:60])

    return gap


# ══════════════════════════════════════════════════════════════
#  RASIMU ZA AI
# ══════════════════════════════════════════════════════════════

DRAFT_PROMPT = """Wewe ni msaidizi wa mmiliki wa biashara "{business}".

Biashara: {description}

Huduma zinazotolewa:
{services}

Maswali yaliyopo tayari na majibu yake:
{faqs}

Wateja wameuliza swali hili na bot haikuweza kulijibu:
"{question}"
(limeulizwa mara {times})

Andika RASIMU ya jibu ambalo mmiliki anaweza kulihariri.

SHERIA MUHIMU:
- Tumia TU taarifa zilizo hapo juu. USIBUNI bei, namba, saa za kazi,
  mahali, wala ahadi yoyote.
- Kama huwezi kujibu bila taarifa ambayo huna, andika hasa taarifa
  gani mmiliki anapaswa kuijaza, kwa mabano. Mfano:
  "Tunafungua saa [ANDIKA SAA] hadi saa [ANDIKA SAA]."
- Jibu kwa lugha ile ile ya swali.
- Sentensi 1-3. Fupi, la moja kwa moja, la kirafiki.
- Rudisha JIBU PEKEE. Hakuna utangulizi, hakuna maelezo."""


def draft_answer(bot, gap):
    """AI inaandika rasimu. Inarudisha maandishi au tupu."""
    from apps import llm
    key = getattr(settings, 'GROQ_API_KEY', '')
    if not (key or llm.gemini_first()):
        return ''

    services = "\n".join(
        f"- {s.name}: {s.description}" + (f" (Bei: {s.price})" if s.price else "")
        for s in bot.services.filter(is_active=True)[:20]
    ) or "(hakuna zilizoorodheshwa)"

    faqs = "\n".join(
        f"S: {f.question}\nJ: {f.answer}"
        for f in bot.faqs.filter(is_active=True)[:15]
    ) or "(hakuna)"

    prompt = DRAFT_PROMPT.format(
        business=bot.business_name,
        description=bot.description or '(hakuna maelezo)',
        services=services,
        faqs=faqs,
        question=gap.question,
        times=gap.times_asked,
    )

    try:
        payload = {
            'model': MODEL,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.3,     # chini — hatutaki ubunifu hapa
            'max_tokens': 300,
        }
        r = llm.gemini_response(payload)   # Gemini kwanza — Kiswahili bora
        if r is None and not key:
            return ''
        r = r or requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=30,
        )
        if r.status_code != 200:
            logger.error('draft imeshindwa %s: %s', r.status_code, r.text[:200])
            return ''
        return (r.json()['choices'][0]['message']['content'] or '').strip()
    except Exception:
        logger.exception('draft imeshindwa')
        return ''


# ══════════════════════════════════════════════════════════════
#  KUKUBALI
# ══════════════════════════════════════════════════════════════

def approve(gap, answer, sort_order=0):
    """
    Mmiliki amekubali. Sasa bot inajua.

    Jibu linakuwa BotFAQ, na FAQ tayari zinaingia kwenye
    `build_system_prompt`. Hakuna sehemu nyingine inayohitaji
    kubadilishwa — hapo ndipo mzunguko unapofungwa.
    """
    from .models import BotFAQ
    from django.utils import timezone

    answer = (answer or '').strip()
    if not answer:
        return None

    if gap.created_faq:
        faq = gap.created_faq
        faq.question = gap.question[:500]
        faq.answer = answer
        faq.is_active = True
        faq.save(update_fields=['question', 'answer', 'is_active'])
    else:
        faq = BotFAQ.objects.create(
            bot=gap.bot, question=gap.question[:500],
            answer=answer, sort_order=sort_order,
        )
        gap.created_faq = faq

    gap.status = 'answered'
    gap.suggested_answer = answer
    gap.save(update_fields=['status', 'suggested_answer', 'created_faq'])
    logger.info('[%s] pengo limejibiwa: %s', gap.bot.session_name, gap.question[:60])
    return faq


# ══════════════════════════════════════════════════════════════
#  KUMBUKUMBU YA MTEJA
# ══════════════════════════════════════════════════════════════
# `build_messages` inachukua jumbe 10 za mwisho. Mteja akirudi baada
# ya mwezi, bot haikumbuki alichonunua. Hii inahifadhi mambo
# YANAYODUMU tu.
#
# Inasasishwa kila baada ya jumbe MEMORY_EVERY, si kila ujumbe —
# kusasisha kila ujumbe kungefanya wito wa AI kuwa maradufu.

MEMORY_EVERY = 8
MEMORY_MAX_CHARS = 700

MEMORY_PROMPT = """Soma mazungumzo haya kati ya biashara "{business}" na mteja wake.

{history}

{existing}

Andika muhtasari wa mambo YANAYODUMU kuhusu mteja huyu ambayo
yatasaidia mazungumzo ya baadaye.

JUMUISHA: jina, mahali anapoishi/anapofanya kazi, alichonunua au
kuuliza, mapendeleo yake, ahadi aliyopewa, matatizo ambayo hayajatatuliwa.

USIJUMUISHE: salamu, maswali ya kawaida yaliyojibiwa na kuisha,
maelezo ya bot, mambo ya siku moja tu.

SHERIA:
- Sentensi fupi, kila moja ni ukweli mmoja.
- Usibuni. Kama hujui, usiandike.
- Kama hakuna la kudumu, andika neno moja: HAKUNA
- Chini ya maneno 100.
- Lugha ya mteja."""


def maybe_update_memory(bot, conv):
    """
    Inaitwa baada ya kila jibu. Inafanya kazi mara chache tu.
    Kamwe haivunji mazungumzo.
    """
    try:
        if conv.message_count - (conv.memory_at_count or 0) < MEMORY_EVERY:
            return
        _update_memory(bot, conv)
    except Exception:
        logger.exception('kusasisha kumbukumbu kumeshindwa')


def _update_memory(bot, conv):
    from django.utils import timezone

    key = getattr(settings, 'GROQ_API_KEY', '')
    if not key:
        return

    msgs = list(conv.messages.order_by('-created_at')[:30])[::-1]
    if len(msgs) < 4:
        return

    history = "\n".join(
        f"{'Mteja' if m.role == 'user' else 'Bot'}: {(m.content or '')[:200]}"
        for m in msgs
    )
    existing = (f"Kumbukumbu uliyonayo tayari:\n{conv.memory}\n\n"
                "Isasishe — ongeza mapya, ondoa yaliyopitwa na wakati."
                if conv.memory else "")

    prompt = MEMORY_PROMPT.format(
        business=bot.business_name, history=history, existing=existing)

    try:
        r = requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'model': MODEL,
                  'messages': [{'role': 'user', 'content': prompt}],
                  'temperature': 0.2, 'max_tokens': 250},
            timeout=30,
        )
        if r.status_code != 200:
            return
        text = (r.json()['choices'][0]['message']['content'] or '').strip()
    except Exception:
        logger.exception('memory API imeshindwa')
        return

    if not text or text.strip().upper().startswith('HAKUNA'):
        conv.memory_at_count = conv.message_count
        conv.save(update_fields=['memory_at_count'])
        return

    conv.memory = text[:MEMORY_MAX_CHARS]
    conv.memory_updated_at = timezone.now()
    conv.memory_at_count = conv.message_count
    conv.save(update_fields=['memory', 'memory_updated_at', 'memory_at_count'])
    logger.info('[%s] kumbukumbu imesasishwa: %s', bot.session_name, conv.customer_phone)


# ══════════════════════════════════════════════════════════════
#  KUUNGANISHA MASWALI YANAYOFANANA
# ══════════════════════════════════════════════════════════════
# `normalize()` inaunganisha maswali YANAYOFANANA KABISA. Lakini
# "mnafungua saa ngapi" na "mnafanya kazi mpaka saa ngapi" ni swali
# moja kwa mteja, na mawili kwenye database. AI inaweza kuyaona.

CLUSTER_PROMPT = """Hii ni orodha ya maswali ambayo bot ya biashara "{business}" ilishindwa kuyajibu.

{items}

Yapange kwa makundi. Maswali yanayotaka JIBU LILE LILE ni kundi moja,
hata kama yameandikwa tofauti au kwa lugha tofauti.

Rudisha JSON PEKEE, bila maelezo yoyote, kwa muundo huu:
[{{"kuu": 3, "wengine": [7, 12]}}, {{"kuu": 5, "wengine": []}}]

"kuu" ni namba ya swali lililo wazi zaidi kwenye kundi.
"wengine" ni namba za maswali mengine ya kundi hilo.
Kila namba itokee MARA MOJA tu kwenye jibu lote."""


def cluster_gaps(bot, limit=40):
    """
    Inaunganisha mapungufu yanayofanana. Inarudisha idadi
    iliyounganishwa.

    Yaliyounganishwa yanapewa status 'dismissed' na hesabu zao
    zinahamia kwenye swali kuu — hivyo mmiliki anaona kwamba swali
    limeulizwa mara 9, si mara 3 mahali tatu.
    """
    from .models import KnowledgeGap

    key = getattr(settings, 'GROQ_API_KEY', '')
    if not key:
        return 0

    gaps = list(KnowledgeGap.objects
                .filter(bot=bot, status__in=['open', 'drafted'])
                .order_by('-times_asked')[:limit])
    if len(gaps) < 3:
        return 0

    items = "\n".join(f"{i}. {g.question}" for i, g in enumerate(gaps))
    prompt = CLUSTER_PROMPT.format(business=bot.business_name, items=items)

    try:
        r = requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'model': MODEL,
                  'messages': [{'role': 'user', 'content': prompt}],
                  'temperature': 0.1, 'max_tokens': 800},
            timeout=45,
        )
        if r.status_code != 200:
            logger.error('cluster imeshindwa: %s', r.status_code)
            return 0
        raw = (r.json()['choices'][0]['message']['content'] or '').strip()
    except Exception:
        logger.exception('cluster API imeshindwa')
        return 0

    groups = _parse_json_array(raw)
    if not groups:
        return 0

    merged = 0
    seen = set()
    for grp in groups:
        try:
            main_i = int(grp.get('kuu'))
            others = [int(x) for x in (grp.get('wengine') or [])]
        except (TypeError, ValueError):
            continue
        if main_i in seen or not (0 <= main_i < len(gaps)):
            continue
        seen.add(main_i)
        main = gaps[main_i]

        for oi in others:
            if oi in seen or not (0 <= oi < len(gaps)) or oi == main_i:
                continue
            seen.add(oi)
            other = gaps[oi]
            main.times_asked += other.times_asked
            other.status = 'dismissed'
            other.save(update_fields=['status'])
            merged += 1

        if merged:
            main.save(update_fields=['times_asked'])

    if merged:
        logger.info('[%s] maswali %d yameunganishwa', bot.session_name, merged)
    return merged


def _parse_json_array(raw):
    """AI mara nyingine inazungushia JSON kwa ```json — tunaisafisha."""
    import json
    txt = raw.strip()
    txt = re.sub(r'^```(?:json)?\s*', '', txt)
    txt = re.sub(r'\s*```$', '', txt)
    start, end = txt.find('['), txt.rfind(']')
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(txt[start:end + 1])
        return data if isinstance(data, list) else []
    except Exception:
        logger.warning('cluster JSON haikusomeka: %s', raw[:150])
        return []
