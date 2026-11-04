"""
Diana — Fedha na ofisi.

  • Invoice zilizopita tarehe ya kulipwa → rasimu MOJA kwa kila mteja, ikiorodhesha
    invoice zake zote (mteja mwenye invoice 6 anapata email moja, si 6)
  • Invoice zinazoisha ndani ya siku 3 → rasimu ya ukumbusho wa upole
  • Malipo ya JamiiBot yanayosubiri kuthibitishwa → kazi ya ofisi
  • Hesabu za wiki (kwa ripoti ya William)
"""
import hashlib
import re
from datetime import timedelta

from django.db.models import Sum

from . import ai
from .board import found, money, settle, site
from .team import member, signature

SLUG = 'diana'
DUE_SOON_DAYS = 3


def _client(inv):
    name = inv.client_name or (inv.client.name if inv.client else '') or 'Mteja'
    email = inv.display_email or ''
    phone = inv.client_phone or (inv.client.phone if inv.client else '') or ''
    who = (email.lower() or re.sub(r'\D', '', phone) or name.lower().strip() or f'inv{inv.pk}')
    return who, name, email, phone


def _line(inv, today, lang='sw'):
    number = inv.invoice_number or f'#{inv.pk}'
    late = (today - inv.due_date).days
    if lang == 'en':
        when = (f'was due {inv.due_date:%d/%m/%Y} ({late} day{"" if late == 1 else "s"} late)' if late > 0
                else f'due {inv.due_date:%d/%m/%Y}')
    else:
        when = (f'ilitakiwa {inv.due_date:%d/%m/%Y} (siku {late} zimepita)' if late > 0
                else f'inatakiwa {inv.due_date:%d/%m/%Y}')
    return (f"• {number} — {inv.title}: {money(inv.balance_due, inv.currency)}, {when}\n"
            f"  {site(inv.public_url)}")


def _reminder(group, today, late):
    """Rasimu MOJA kwa mteja mmoja, ikiorodhesha invoice zake zote za hatua hii.
    Ikitumwa kwa email (mteja ana email) ni kwa Kiingereza; kwa WhatsApp inabaki Kiswahili."""
    if group.get('email'):
        return _reminder_en(group, today, late)
    who = member(SLUG)
    invs, name = group['invoices'], group['name']
    total = money(sum(i.balance_due for i in invs), invs[0].currency)
    many = len(invs) > 1
    numbers = ', '.join(i.invoice_number or f'#{i.pk}' for i in invs)

    if late:
        subject = (f'Ukumbusho: invoice {len(invs)} zinazodaiwa ({total})' if many
                   else f'Ukumbusho: invoice {numbers} ({total})')
        facts = (f"{name} ana invoice {len(invs)} ({numbers}) zilizopita tarehe ya kulipwa, "
                 f"jumla ya salio {total}." if many else
                 f"Invoice {numbers} ({invs[0].title}) ya {name} ina salio la {total} na "
                 f"imechelewa siku {(today - invs[0].due_date).days}.")
        fallback = (f"Habari {name},\n\nTunakukumbusha kwa heshima kuhusu "
                    + (f"invoice {len(invs)} ambazo bado hazijalipwa, jumla ya {total}."
                       if many else f"invoice {numbers} yenye salio la {total} ambayo muda wake wa kulipwa umepita.")
                    + " Kama umeshalipa, tafadhali tutumie uthibitisho ili tusasishe kumbukumbu zetu.")
    else:
        subject = f'Invoice {numbers} inakaribia tarehe ya kulipwa'
        facts = f"{name} ana invoice {numbers} yenye salio la {total} inayokaribia tarehe ya kulipwa."
        fallback = (f"Habari {name},\n\nHuu ni ukumbusho wa upole kuhusu "
                    + (f"invoice {len(invs)} zinazokaribia tarehe ya kulipwa, jumla ya {total}."
                       if many else f"invoice {numbers} yenye salio la {total} inayokaribia tarehe ya kulipwa."))

    body = ai.write(
        ai.persona(who['name'], who['role']),
        f"{facts}\nAndika aya 1-2 tu za utangulizi za kumkumbusha mteja kulipa, kwa adabu, ukianza "
        f"na 'Habari {name},'. Usiorodheshe invoice wala kuweka link — orodha itaongezwa chini.",
        max_tokens=260) or fallback
    lines = '\n'.join(_line(i, today) for i in invs)
    return subject[:200], (f"{body}\n\n{'Invoice' if not many else 'Invoice zako'} na njia za kulipa:\n"
                           f"{lines}\n\nAsante,\n{signature(SLUG)}")


def _reminder_en(group, today, late):
    who = member(SLUG)
    invs, name = group['invoices'], group['name']
    total = money(sum(i.balance_due for i in invs), invs[0].currency)
    many = len(invs) > 1
    numbers = ', '.join(i.invoice_number or f'#{i.pk}' for i in invs)
    if late:
        subject = (f'Reminder: {len(invs)} unpaid invoices ({total})' if many
                   else f'Reminder: invoice {numbers} ({total})')
        facts = (f"{name} ana invoice {len(invs)} ({numbers}) zilizopita tarehe ya kulipwa, "
                 f"jumla ya salio {total}." if many else
                 f"Invoice {numbers} ({invs[0].title}) ya {name} ina salio la {total} na "
                 f"imechelewa siku {(today - invs[0].due_date).days}.")
        fallback = (f"Hello {name},\n\nThis is a polite reminder about "
                    + (f"{len(invs)} invoices that are still unpaid, {total} in total."
                       if many else f"invoice {numbers}, with {total} still due, which is past its due date.")
                    + " If you have already paid, please send us the confirmation so we can update our records.")
    else:
        subject = f'Invoice {numbers} is due soon'
        facts = f"{name} ana invoice {numbers} yenye salio la {total} inayokaribia tarehe ya kulipwa."
        fallback = (f"Hello {name},\n\nThis is a friendly reminder about "
                    + (f"{len(invs)} invoices that are due soon, {total} in total."
                       if many else f"invoice {numbers}, with {total} due soon."))
    body = ai.write(
        ai.persona(who['name'], who['role'], lang='en'),
        f"{facts}\nAndika aya 1-2 tu za utangulizi za kumkumbusha mteja kulipa, kwa adabu, ukianza "
        f"na 'Hello {name},'. Usiorodheshe invoice wala kuweka link — orodha itaongezwa chini.",
        max_tokens=260) or fallback
    lines = '\n'.join(_line(i, today, 'en') for i in invs)
    return subject[:200], (f"{body}\n\n{'Your invoice' if not many else 'Your invoices'} and how to pay:\n"
                           f"{lines}\n\nThank you,\n{signature(SLUG, 'en')}")


def _invoices(today):
    from apps.models import Invoice

    groups = {}
    qs = (Invoice.objects.select_related('client')
          .exclude(status__in=['draft', 'paid', 'cancelled'])
          .filter(due_date__isnull=False, due_date__lte=today + timedelta(days=DUE_SOON_DAYS))
          .order_by('due_date', 'pk')[:300])
    for inv in qs:
        if inv.balance_due <= 0:
            continue
        late = (today - inv.due_date).days > 0
        who, name, email, phone = _client(inv)
        g = groups.setdefault((who, late, inv.currency), {
            'name': name, 'email': email, 'phone': phone, 'invoices': []})
        g['invoices'].append(inv)

    seen = []
    for (who, late, currency), g in groups.items():
        invs = g['invoices']
        # Invoice zikibadilika (mpya, au moja ikilipwa), kazi mpya inaundwa yenye
        # rasimu sahihi; ya zamani inafungwa na settle().
        ids = '-'.join(str(i.pk) for i in sorted(invs, key=lambda i: i.pk))
        key = f"diana:cli:{hashlib.sha1(f'{who}|{currency}|{ids}'.encode()).hexdigest()[:16]}:{'late' if late else 'soon'}"
        seen.append(key)
        total = money(sum(i.balance_due for i in invs), currency)
        oldest = max((today - i.due_date).days for i in invs)
        if late:
            what = f'invoice {len(invs)} zimechelewa' if len(invs) > 1 else \
                f'invoice {invs[0].invoice_number or invs[0].pk} imechelewa'
            title = f'{g["name"]}: {what} (siku {oldest}) — {total}'
            priority = 1 if oldest > 14 else 2
        else:
            what = (f'invoice {len(invs)} zinakaribia' if len(invs) > 1 else
                    f'invoice {invs[0].invoice_number or invs[0].pk} inakaribia')
            title = f'{g["name"]}: {what} tarehe ya kulipwa — {total}'
            priority = 3
        found(SLUG, key, title[:200],
              draft=(lambda g=g, late=late: _reminder(g, today, late)) if (g['email'] or g['phone']) else None,
              ref=f"invoices:{ids}"[:60], priority=priority,
              detail='\n'.join(f"{i.invoice_number or i.pk} · {i.title} · {money(i.balance_due, i.currency)} · "
                               f"{i.due_date:%d/%m/%Y}" for i in invs)[:2000],
              link=site(f'/manage/invoices/{invs[0].pk}/edit/' if len(invs) == 1 else '/manage/invoices/'),
              channel='email' if g['email'] else ('whatsapp' if g['phone'] else 'none'),
              recipient_name=g['name'], recipient_email=g['email'], recipient_phone=g['phone'])
    settle(SLUG, 'diana:cli:', seen, 'Invoice zimelipwa au zimebadilika.')
    # Kazi za mtindo wa zamani (invoice moja moja) zinafungwa
    settle(SLUG, 'diana:inv:', [], 'Imeunganishwa kwenye ukumbusho mmoja kwa kila mteja.')
    return sum(len(g['invoices']) for g in groups.values())


def _bot_payments():
    from apps.chatbot.models import SubscriptionPayment

    seen = []
    for p in (SubscriptionPayment.objects.filter(status='pending')
              .select_related('subscription__bot')[:50]):
        key = f'diana:botpay:{p.pk}'
        seen.append(key)
        bot = p.subscription.bot
        found(SLUG, key, f'Thibitisha malipo ya JamiiBot: {bot.business_name} — {money(p.amount)}',
              ref=f'botpay:{p.pk}', priority=1,
              detail=f'{p.payment_method} · ref {p.transaction_ref} · miezi {p.months_covered}',
              link=site('/manage/chatbot/payments/'))
    settle(SLUG, 'diana:botpay:', seen, 'Malipo yamethibitishwa au kukataliwa.')
    return len(seen)


def numbers(now):
    """Hesabu za fedha kwa ripoti ya William."""
    from apps.models import Invoice
    from apps.pesapal_models import PesapalTransaction

    week_ago = now - timedelta(days=7)
    online = (PesapalTransaction.objects.filter(status='completed', completed_at__gte=week_ago)
              .aggregate(t=Sum('amount'))['t'] or 0)
    paid = Invoice.objects.filter(paid_at__gte=week_ago)
    invoices_paid = sum(inv.grand_total for inv in paid)
    open_qs = Invoice.objects.exclude(status__in=['draft', 'paid', 'cancelled'])
    outstanding = sum(inv.balance_due for inv in open_qs[:500])
    overdue = sum(1 for inv in open_qs[:500] if inv.is_overdue)
    return {
        'online_week': float(online),
        'invoices_paid_week': float(invoices_paid),
        'outstanding': float(outstanding),
        'overdue_count': overdue,
    }


def run(now):
    today = now.date()
    return {'invoices': _invoices(today), 'bot_payments': _bot_payments()}
