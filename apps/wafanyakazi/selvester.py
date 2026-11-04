"""
Selvester — Afisa mauzo.

  • Leads za fomu ya /proposals/ ambazo bado hazijageuzwa proposal
  • Ujumbe mpya wa fomu ya mawasiliano (Contact)
  • Malipo ya Pesapal yaliyoanzishwa lakini hayakukamilika
  • Tovuti za builder zilizoundwa lakini hazijachapishwa
  • Wateja wa JamiiBot wenye nia ya kununua (anapewa na Ibrahimu)
"""
import json
from datetime import timedelta

from . import ai
from .board import found, settle, site
from .models import Alama
from .team import member, signature

SLUG = 'selvester'
LEAD_DAYS = 21
PER_RUN = 15


def _write(facts, ask, fallback, max_tokens=320, lang='sw'):
    who = member(SLUG)
    return ai.write(ai.persona(who['name'], who['role'], lang=lang), f'{facts}\n{ask}',
                    max_tokens=max_tokens) or fallback


def _sign(body, link='', lang='sw'):
    """Email za wateja (lang='en') zinaishia kwa Kiingereza; WhatsApp inabaki Kiswahili."""
    tail = f'\n\n{link}' if link else ''
    thanks = 'Thank you,' if lang == 'en' else 'Asante,'
    return f'{body}{tail}\n\n{thanks}\n{signature(SLUG, lang)}'


# ── Leads za /proposals/ ─────────────────────────────────────────

def _req(lead):
    req = lead.requirements
    if isinstance(req, str):
        try:
            req = json.loads(req)
        except (ValueError, TypeError):
            req = {}
    return req if isinstance(req, dict) else {}


def _leads(now):
    from apps.models import ProjectProposal, Proposal

    converted = set(Proposal.objects.exclude(client_email='').values_list('client_email', flat=True))
    seen, made = [], 0
    for lead in (ProjectProposal.objects.select_related('client', 'website_type')
                 .filter(created_at__gte=now - timedelta(days=LEAD_DAYS)).order_by('-created_at')):
        req = _req(lead)
        email = req.get('client_email') or getattr(lead.client, 'email', '') or ''
        if email and email in converted:
            continue
        key = f'selv:lead:{lead.pk}'
        seen.append(key)
        name = req.get('client_name') or getattr(lead.client, 'name', '') or 'Mteja'
        phone = req.get('client_phone') or getattr(lead.client, 'phone', '') or ''
        kind = getattr(lead.website_type, 'name', 'tovuti')
        age = (now - lead.created_at).days
        wishes = ', '.join(f'{k}: {v}' for k, v in list(req.items())[:8]
                           if k not in ('client_email', 'client_phone', 'client_name')
                           and isinstance(v, (str, int)) and str(v).strip())[:600]

        def draft(name=name, kind=kind, wishes=wishes, lang='en' if email else 'sw'):
            if lang == 'en':                  # email kwa mteja: Kiingereza
                body = _write(
                    f"{name} alijaza fomu ya JamiiTek akiomba {kind}. Maelezo: {wishes or 'hakuna'}.",
                    f"Andika ujumbe wa kumfuatilia (aya 2): mshukuru, onyesha umeelewa anachotaka, "
                    f"na umwombe muda mfupi wa simu au mkutano ili kumpa proposal. Anza na 'Hello {name},'.",
                    f"Hello {name},\n\nThank you for contacting JamiiTek about {kind}. We have read your "
                    "details and would like to prepare a full proposal for you. Do you have time for a short "
                    "call this week so we understand exactly what you need?", lang=lang)
                return f'{kind} for {name} — JamiiTek', _sign(body, lang=lang)
            body = _write(
                f"{name} alijaza fomu ya JamiiTek akiomba {kind}. Maelezo: {wishes or 'hakuna'}.",
                f"Andika ujumbe wa kumfuatilia (aya 2): mshukuru, onyesha umeelewa anachotaka, "
                f"na umwombe muda mfupi wa simu au mkutano ili kumpa proposal. Anza na 'Habari {name},'.",
                f"Habari {name},\n\nAsante kwa kuwasiliana na JamiiTek kuhusu {kind}. Tumepitia "
                "maelezo yako na tungependa kukuandalia proposal kamili. Je, una muda wa simu "
                "fupi wiki hii ili tuelewe vizuri unachohitaji?")
            return f'{kind} kwa {name} — JamiiTek', _sign(body)

        if made >= PER_RUN and not _exists(key):
            continue
        _, created = found(SLUG, key, f'Lead: {name} anataka {kind} (siku {age})',
                           draft=draft if (email or phone) else None,
                           ref=f'lead:{lead.pk}', priority=1 if age <= 2 else 2,
                           detail=wishes, link=site('/manage/leads/'),
                           channel='email' if email else ('whatsapp' if phone else 'none'),
                           recipient_name=name, recipient_email=email, recipient_phone=phone)
        made += created
    settle(SLUG, 'selv:lead:', seen, 'Lead imegeuzwa proposal au imepitwa na muda.')
    return len(seen)


def _exists(key):
    from .models import Kazi
    return Kazi.objects.filter(key=key).exists()


# ── Fomu ya mawasiliano ──────────────────────────────────────────

def _contacts():
    """Contact haina tarehe, kwa hiyo tunakumbuka id ya mwisho tuliyoiona."""
    from apps.models import Contact

    last = Contact.objects.order_by('-pk').values_list('pk', flat=True).first() or 0
    mark = Alama.get('selvester:contact_pk')
    if mark == '':
        # Mara ya kwanza: usifanyie kazi ujumbe wa zamani wote
        Alama.put('selvester:contact_pk', last)
        return 0
    new = list(Contact.objects.filter(pk__gt=int(mark)).order_by('pk')[:PER_RUN])
    for c in new:
        def draft(c=c):
            body = _write(
                f"{c.full_name} ameandika kupitia fomu ya mawasiliano. Mada: {c.subject}. "
                f"Ujumbe: {c.message[:800]}",
                f"Andika jibu fupi la kwanza (aya 1-2): mshukuru, jibu kwa ufupi kama unaweza "
                f"bila kubuni, na umwombe maelezo/muda wa kuzungumza. Anza na 'Hello {c.full_name},'.",
                f"Hello {c.full_name},\n\nThank you for contacting JamiiTek about \"{c.subject}\". "
                "We have received your message and we will help you. Could you share a phone number or a "
                "good time to talk?", lang='en')
            return f'Re: {c.subject}'[:200], _sign(body, lang='en')

        found(SLUG, f'selv:contact:{c.pk}', f'Ujumbe mpya: {c.full_name} — {c.subject}'[:200],
              draft=draft, ref=f'contact:{c.pk}', priority=1, detail=c.message[:1500],
              link=site(f'/admin/apps/contact/{c.pk}/change/'), channel='email',
              recipient_name=c.full_name, recipient_email=c.email)
    if new:
        Alama.put('selvester:contact_pk', new[-1].pk)
    return len(new)


# ── Malipo yaliyoachwa njiani ────────────────────────────────────

def _abandoned(now):
    from apps.pesapal_models import PesapalTransaction

    seen = []
    qs = (PesapalTransaction.objects
          .filter(status__in=['pending', 'failed'],
                  created_at__lte=now - timedelta(hours=2),
                  created_at__gte=now - timedelta(days=7))
          .order_by('-created_at')[:30])
    for tx in qs:
        if not (tx.email or tx.phone):
            continue
        finished = PesapalTransaction.objects.filter(
            purpose=tx.purpose, target_id=tx.target_id, status='completed',
            created_at__gte=tx.created_at).exists()
        if finished:
            continue
        key = f'selv:pay:{tx.pk}'
        seen.append(key)
        name = ' '.join(p for p in (tx.first_name, tx.last_name) if p) or 'Mteja'
        what = tx.description or tx.get_purpose_display()
        amount = f'{tx.currency} {float(tx.amount):,.0f}'

        def draft(name=name, what=what, amount=amount, lang='en' if tx.email else 'sw'):
            if lang == 'en':
                body = _write(
                    f"{name} alianza kulipa {amount} kwa ajili ya '{what}' kupitia Pesapal lakini "
                    "malipo hayakukamilika.",
                    f"Andika ujumbe mfupi wa kirafiki (aya 1-2) wa kuuliza kama alipata changamoto "
                    f"na kumpa msaada wa kukamilisha. Anza na 'Hello {name},'.",
                    f"Hello {name},\n\nWe noticed you started paying for {what} ({amount}) but the payment "
                    "did not finish. If something went wrong, let us know and we will help — we can also give "
                    "you another way to pay.", lang=lang)
                return f'Your payment for {what} — can we help?'[:200], _sign(body, lang=lang)
            body = _write(
                f"{name} alianza kulipa {amount} kwa ajili ya '{what}' kupitia Pesapal lakini "
                "malipo hayakukamilika.",
                f"Andika ujumbe mfupi wa kirafiki (aya 1-2) wa kuuliza kama alipata changamoto "
                f"na kumpa msaada wa kukamilisha. Anza na 'Habari {name},'.",
                f"Habari {name},\n\nTumeona ulianza kulipia {what} ({amount}) lakini malipo "
                "hayakukamilika. Kama ulipata changamoto yoyote, tujulishe tukusaidie — "
                "tunaweza pia kukupa njia nyingine ya kulipa.")
            return f'Malipo ya {what} — tunaweza kusaidia?'[:200], _sign(body)

        found(SLUG, key, f'Malipo hayakukamilika: {name} — {what} ({amount})'[:200],
              draft=draft, ref=f'pesapal:{tx.pk}', priority=2,
              detail=f'{tx.get_purpose_display()} · {tx.get_status_display()} · {tx.created_at:%d/%m %H:%M}',
              link=site(f'/admin/apps/pesapaltransaction/{tx.pk}/change/'),
              channel='email' if tx.email else 'whatsapp',
              recipient_name=name, recipient_email=tx.email, recipient_phone=tx.phone)
    settle(SLUG, 'selv:pay:', seen, 'Malipo yamekamilika au muda umepita.')
    return len(seen)


# ── Tovuti za builder ambazo hazijachapishwa ─────────────────────

def _drafts(now):
    from builder.models import ClientWebsite

    seen = []
    qs = (ClientWebsite.objects.select_related('owner')
          .filter(is_published=False, is_suspended=False,
                  created_at__lte=now - timedelta(days=2),
                  created_at__gte=now - timedelta(days=30))
          .order_by('-created_at')[:PER_RUN])
    for w in qs:
        email = w.contact_email or getattr(w.owner, 'email', '')
        if not email:
            continue
        key = f'selv:site:{w.pk}'
        seen.append(key)
        name = (w.owner.get_full_name() or w.owner.username) if w.owner else 'Mteja'

        def draft(w=w, name=name):
            body = _write(
                f"{name} alianza kutengeneza tovuti '{w.site_name}' kwenye JamiiTek web builder "
                "siku kadhaa zilizopita lakini bado hajaichapisha.",
                f"Andika ujumbe mfupi (aya 1-2) wa kumtia moyo na kumpa msaada wa kuimaliza "
                f"na kuichapisha. Anza na 'Hello {name},'.",
                f"Hello {name},\n\nWe saw that you started building your website \"{w.site_name}\" — well "
                "done! It is not published yet. If anything is holding you back, reply to this email and we "
                "will help you finish it today.", lang='en')
            return f'Your website "{w.site_name}" — can we help you finish it?'[:200], _sign(
                body, site('/builder/login/'), lang='en')

        found(SLUG, key, f'Tovuti haijachapishwa: {w.site_name} ({name})'[:200],
              draft=draft, ref=f'site:{w.pk}', priority=3,
              detail=f'{w.subdomain} · imeundwa {w.created_at:%d/%m}',
              link=site('/manage/builder/'), channel='email',
              recipient_name=name, recipient_email=email)
    settle(SLUG, 'selv:site:', seen, 'Tovuti imechapishwa au muda umepita.')
    return len(seen)


def run(now):
    return {
        'leads': _leads(now),
        'contacts': _contacts(),
        'abandoned_payments': _abandoned(now),
        'unpublished_sites': _drafts(now),
    }
