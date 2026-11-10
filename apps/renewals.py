# apps/renewals.py
"""
Ankara za renewal: hosting, domain na email hosting.

MZUNGUKO MZIMA
  1. Kila siku (`manage.py renewal_invoices`, kupitia daily_tasks) — huduma
     zinazokaribia kuisha zinapata ankara:
         hosting na email hosting  → siku HOSTING_DAYS (7) kabla
         domain                    → siku DOMAIN_DAYS (30) kabla
     Huduma za mteja mmoja zinazoisha karibu wakati mmoja zinaingia kwenye
     ankara MOJA. Ankara inatumwa kwa email NA WhatsApp (namba ya mteja).
  2. Vikumbusho (email + WhatsApp) — siku 3, 1 na siku ya mwisho (domain pia
     14 na 7). Onyo la zamani la "hosting inaisha" halitumwi tena kwa huduma
     yenye ankara iliyo wazi — mteja hapati barua mbili kwa jambo moja.
  3. Mteja analipa (M-Pesa / benki) kisha anatuma uthibitisho kutoka ukurasa
     wa ankara (PaymentProof). Wewe unahakiki.
  4. Ukiidhinisha uthibitisho, au ukibonyeza "Mark paid" kwenye ankara:
       • risiti (DevelopmentReceipt) inatengenezwa — inahitaji SAHIHI;
       • mteja anatumiwa link ya KUTHIBITISHA risiti (si link ya risiti yenyewe):
         anathibitisha kwanza, kisha ndipo anaiona/kuipakua;
       • ankara ikilipwa yote: tarehe za hosting/domain/email zinasogezwa mbele,
         rekodi za malipo zinaandikwa, na tovuti iliyosimamishwa inarudi.

Kila hatua ni best-effort na haitupi exception kwa anayeiita.
"""
import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

HOSTING_DAYS = 7
DOMAIN_DAYS = 30
# Huduma iliyokwisha bila ankara (mfano iliongezwa kwenye mfumo ikiwa imeshaisha)
# bado inapata ankara ikiwa ndani ya siku hizi.
LATE_DAYS = 30

# Siku zilizobaki ambazo ukumbusho unatumwa (baada ya ankara ya kwanza)
REMIND_STAGES = {
    'hosting': (3, 1, 0),
    'email': (3, 1, 0),
    'domain': (14, 7, 3, 1, 0),
}


# ══════════════════════════════════════════════════════════════
# Vipande vidogo
# ══════════════════════════════════════════════════════════════
def _add_months(d, months):
    try:
        from dateutil.relativedelta import relativedelta
        return d + relativedelta(months=int(months))
    except ImportError:
        return d + timedelta(days=30 * int(months))


def _site_url(path):
    base = (getattr(settings, 'SITE_URL', '') or 'https://www.jamiitek.com').rstrip('/')
    return base + path


def phone_digits(phone):
    d = re.sub(r'\D', '', phone or '')
    if d.startswith('0') and len(d) == 10:
        d = '255' + d[1:]
    elif len(d) == 9 and d[0] in '67':
        d = '255' + d
    return d


def _money(v, cur='TZS'):
    return f'{cur} {float(v or 0):,.0f}'


def _fmt(d):
    return d.strftime('%d %b %Y') if d else ''


def _new_start(period_end, today):
    """Kipindi kipya kinaanza pale cha zamani kinapoishia — au leo kama kimeshaisha."""
    return period_end if period_end and period_end > today else today


def _plural(n, word):
    return f'{n} {word}{"s" if n != 1 else ""}'


# Hosting na email hosting zinalipiwa KILA MWEZI: ankara ni ya mwezi mmoja tu.
# (Awali ilifuata malipo ya mwisho — na mteja asiye na rekodi ya malipo alipewa
# miezi 12 kwa chaguo-msingi. Ndiyo maana baadhi ya ankara zilitoka na kiasi
# kikubwa mno.) Domain ni mwaka mmoja, kama ilivyo kwa msajili.
HOSTING_MONTHS = 1
DOMAIN_MONTHS = 12


def _hosting_line(site, start, months=HOSTING_MONTHS):
    price = site.price_for(months)
    end = _add_months(start, months)
    desc = f'Website hosting – {site.name} · {_plural(months, "month")} ({_fmt(start)} – {_fmt(end)})'
    if price['discount_pct']:
        desc += f' · {price["discount_pct"]:g}% discount'
    return desc, Decimal(str(round(price['total'], 2)))


def _email_line(plan, start, months=HOSTING_MONTHS):
    end = _add_months(start, months)
    desc = (f'Email hosting – {plan.email_domain} ({_plural(plan.accounts_count, "account")}) · '
            f'{_plural(months, "month")} ({_fmt(start)} – {_fmt(end)})')
    return desc, Decimal(str(plan.monthly_cost or 0)) * months


def _domain_line(dom, start, months=DOMAIN_MONTHS):
    end = _add_months(start, months)
    return (f'Domain renewal – {dom.domain_name} · 1 year ({_fmt(start)} – {_fmt(end)})',
            Decimal(str(dom.renewal_cost or 0)))


# ══════════════════════════════════════════════════════════════
# 1. Kinachokaribia kuisha
# ══════════════════════════════════════════════════════════════
def _hosting_items(today):
    from apps.models import ManagedWebsite
    qs = (ManagedWebsite.objects
          .filter(hosting_end_date__lte=today + timedelta(days=HOSTING_DAYS),
                  hosting_end_date__gte=today - timedelta(days=LATE_DAYS),
                  send_expiry_warnings=True)
          .exclude(status='terminated')
          .select_related('client'))
    for site in qs:
        desc, amount = _hosting_line(site, _new_start(site.hosting_end_date, today))
        if amount <= 0:
            continue
        yield {
            'kind': 'hosting', 'obj': site, 'client': site.client, 'period_end': site.hosting_end_date,
            'months': HOSTING_MONTHS, 'amount': amount, 'desc': desc, 'label': f'Hosting – {site.name}',
        }


def _email_items(today):
    from apps.models import EmailHostingPlan
    qs = (EmailHostingPlan.objects
          .filter(end_date__lte=today + timedelta(days=HOSTING_DAYS),
                  end_date__gte=today - timedelta(days=LATE_DAYS),
                  send_expiry_warnings=True)
          .exclude(status='cancelled')
          .select_related('client'))
    for plan in qs:
        desc, amount = _email_line(plan, _new_start(plan.end_date, today))
        if amount <= 0:
            continue
        yield {
            'kind': 'email', 'obj': plan, 'client': plan.client, 'period_end': plan.end_date,
            'months': HOSTING_MONTHS, 'amount': amount, 'desc': desc, 'label': f'Email – {plan.email_domain}',
        }


def _domain_items(today):
    from apps.models import DomainRecord
    qs = (DomainRecord.objects
          .filter(expiry_date__lte=today + timedelta(days=DOMAIN_DAYS),
                  expiry_date__gte=today - timedelta(days=LATE_DAYS),
                  send_renewal_warnings=True, renewal_cost__gt=0)
          .exclude(status='transferred')
          .select_related('website__client'))
    for dom in qs:
        start = _new_start(dom.expiry_date, today)
        end = _add_months(start, 12)
        yield {
            'kind': 'domain', 'obj': dom, 'client': dom.website.client, 'period_end': dom.expiry_date,
            'months': 12, 'amount': Decimal(str(dom.renewal_cost)),
            'desc': f'Domain renewal – {dom.domain_name} · 1 year ({_fmt(start)} – {_fmt(end)})',
            'label': f'Domain – {dom.domain_name}',
        }


def due_items(today=None):
    """Huduma zote zinazohitaji ankara sasa na bado hazina ankara ya kipindi hiki."""
    from apps.models import RenewalNotice
    today = today or timezone.localdate()
    out = []
    for gen in (_hosting_items, _email_items, _domain_items):
        for item in gen(today):
            exists = RenewalNotice.objects.filter(
                kind=item['kind'], object_id=item['obj'].pk, period_end=item['period_end']).exists()
            if not exists:
                out.append(item)
    return out


def has_open_invoice(kind, object_id):
    """Je huduma hii ina ankara ya renewal ambayo bado haijalipwa?"""
    from apps.models import RenewalNotice
    return (RenewalNotice.objects
            .filter(kind=kind, object_id=object_id, applied_at__isnull=True)
            .exclude(invoice__status__in=('paid', 'cancelled'))
            .exists())


# ══════════════════════════════════════════════════════════════
# 2. Kutengeneza ankara
# ══════════════════════════════════════════════════════════════
def create_invoices(today=None, send=True, dry_run=False):
    """Tengeneza ankara za renewal (moja kwa kila mteja). Rudisha orodha ya ankara."""
    from apps.models import Invoice, RenewalNotice

    today = today or timezone.localdate()
    groups = {}
    for item in due_items(today):
        groups.setdefault(item['client'].pk, []).append(item)

    created = []
    for _cid, items in groups.items():
        client = items[0]['client']
        if dry_run:
            created.append((client, items))
            continue
        due = min(i['period_end'] for i in items)
        due = max(due, today)
        try:
            with transaction.atomic():
                inv = Invoice.objects.create(
                    invoice_type='standard',
                    client=client, client_name=client.name, client_email=client.email,
                    client_company=client.company or '', client_phone=client.phone or '',
                    title='Service Renewal',
                    project_name=', '.join(i['label'] for i in items)[:200],
                    issue_date=today, due_date=due,
                    line_items=[{'desc': i['desc'], 'qty': 1, 'unit_price': float(i['amount']),
                                 'amount': float(i['amount'])} for i in items],
                    currency='TZS', payment_mode='manual',
                    payment_methods=[dict(m) for m in Invoice.DEFAULT_PAYMENT_METHODS],
                    payment_terms='Pay before the due date to keep your services running without a break.',
                    notes_en=('After paying, press "I have paid" on this page and send the transaction ID, '
                              'a screenshot or a PDF. We check it and send your receipt.'),
                    status='sent', sent_at=timezone.now(),
                )
                for i in items:
                    RenewalNotice.objects.create(
                        kind=i['kind'], object_id=i['obj'].pk, period_end=i['period_end'],
                        months=i['months'], label=i['label'][:200], amount=i['amount'], invoice=inv,
                        last_stage=(due - today).days, last_stage_at=timezone.now())
                    # Onyo la "siku 7" la zamani lisitumwe juu ya ankara hii
                    if i['kind'] == 'hosting':
                        site = i['obj']
                        site.last_warning_stage = 7
                        site.last_warning_at = timezone.now()
                        site.save(update_fields=['last_warning_stage', 'last_warning_at'])
        except Exception:
            logger.exception('[renewals] ankara ya %s haikutengenezwa', client)
            continue

        created.append(inv)
        _activity('renewal_invoice', f'Renewal invoice {inv.invoice_number} — {client.name}',
                  rows=[(i['label'], _money(i['amount'])) for i in items] + [('Due', _fmt(inv.due_date))],
                  link=f'/manage/invoices/{inv.pk}/edit/', amount=inv.grand_total)
        if send:
            send_invoice(inv, first=True)
    return created


# ══════════════════════════════════════════════════════════════
# 3. Kutuma: email + WhatsApp
# ══════════════════════════════════════════════════════════════
def _invoice_phone(inv):
    return inv.client_phone or (inv.client.phone if inv.client else '')


def send_whatsapp(phone, text):
    """Kupitia JamiiBot ya JamiiTek (bridge). Rudisha True ikifika."""
    digits = phone_digits(phone)
    if not digits or len(digits) < 11 or len(digits) > 13:
        return False
    try:
        from apps.chatbot import bridge
        from apps.wafanyakazi.ibrahimu import bots
        bot = bots().first()
        if not bot or not bridge.is_configured():
            return False
        res = bridge.BaileysHandler(bot).send_text(digits, text)
        if not res.get('success'):
            logger.warning('[renewals] WhatsApp kwa %s haikufika: %s', digits, res.get('error'))
        return bool(res.get('success'))
    except Exception:
        logger.exception('[renewals] WhatsApp imeshindikana')
        return False


def _days_left(inv, today=None):
    if not inv.due_date:
        return None
    return (inv.due_date - (today or timezone.localdate())).days


def _when(days):
    if days is None:
        return ''
    if days < 0:
        return f'{-days} day{"s" if days != -1 else ""} ago'
    if days == 0:
        return 'today'
    if days == 1:
        return 'tomorrow'
    return f'in {days} days'


def send_invoice(inv, first=False, stage=None, corrected=False, today=None):
    """Tuma ankara (au ukumbusho wake) kwa email na WhatsApp. Rudisha (email_ok, wa_ok)."""
    from apps.utils.customer_email import send_customer_email

    link = _site_url(inv.public_url) + '?lang=en'
    days = _days_left(inv, today)
    services = ', '.join(r.label for r in inv.renewals.all()) or inv.project_name or inv.title
    amount = _money(inv.balance_due, inv.currency)

    if corrected:
        subject = f'Corrected invoice {inv.invoice_number} — the right amount is {amount}'
        lead = (f'Dear {inv.display_client},\n\nSorry — our earlier email for invoice {inv.invoice_number} '
                f'showed the wrong amount. Hosting is billed for one month at a time.\n\n'
                f'The correct amount to pay is {amount}. Please ignore the earlier amount. '
                f'If you already paid more, reply to this email and we will sort it out.')
        chip = ('✓ Corrected', 'info')
    elif first:
        subject = f'Invoice {inv.invoice_number} — renew {services} ({amount})'
        lead = (f'Dear {inv.display_client},\n\nYour services below end {_when(days)} '
                f'({_fmt(inv.due_date)}). We have prepared your renewal invoice so they keep running '
                f'without a break.\n\nPay by M-Pesa or bank, then press "I have paid" on the invoice page '
                f'and send the transaction ID or a screenshot. We will check it and send your receipt.')
        chip = (f'⏳ {days} day{"s" if days != 1 else ""} left' if days and days > 0 else '⏳ Due today', 'warning')
    elif days is not None and days < 0:
        subject = f'Overdue — invoice {inv.invoice_number} ({amount})'
        lead = (f'Dear {inv.display_client},\n\nYour renewal invoice was due {_when(days)}. '
                f'Please pay now so your services are not stopped.')
        chip = ('⛔ Overdue', 'danger')
    else:
        urgent = 'Final reminder' if days is not None and days <= 1 else 'Reminder'
        subject = f'{urgent}: {services} ends {_when(days)} — invoice {inv.invoice_number}'
        lead = (f'Dear {inv.display_client},\n\nThis is a reminder that {services} ends {_when(days)} '
                f'({_fmt(inv.due_date)}). Your invoice is still waiting for payment.')
        chip = ('🔴 Ends today' if days == 0 else f'⏳ {days} day{"s" if days != 1 else ""} left',
                'danger' if days is not None and days <= 1 else 'warning')

    # Ushauri wa kulipa mapema — si deni: ankara yenyewe inabaki ya mwezi mmoja
    tips = pay_ahead_text(inv)
    if tips:
        lead += ('\n\nTip (optional): pay for more months at once and save. Your invoice is for '
                 'one month — these are only options:\n' + '\n'.join(tips)
                 + '\nTo pay ahead, send that amount and choose the months when you send your proof.')

    rows = [(it['desc'], _money(it['amount'], inv.currency)) for it in inv.items]
    rows += [('Amount to pay', amount), ('Due date', _fmt(inv.due_date))]
    email_ok = False
    if inv.display_email:
        email_ok = send_customer_email(
            inv.display_email, subject, lead, rows=rows,
            button=('View & pay invoice', link, 'orange'),
            category='renewal_invoice', chip=chip, reply_to=['info@jamiitek.com'])

    if corrected:
        intro = (f'Sorry — the amount in our earlier message for invoice *{inv.invoice_number}* was wrong. '
                 f'Hosting is billed for one month. The correct amount is *{amount}*.\n')
    elif first:
        intro = f'Your renewal invoice *{inv.invoice_number}* is ready: *{amount}*.\n'
    else:
        intro = f'Reminder: invoice *{inv.invoice_number}* ({amount}) is not paid yet.\n'
    wa_text = (f'Hello {inv.display_client},\n\n' + intro
               + f'Services: {services}\n'
               + f'Pay by: *{_fmt(inv.due_date)}*' + (f' ({_when(days)})' if days is not None else '') + '\n\n'
               + f'View and pay here:\n{_site_url(inv.public_url)}\n\n'
               + f'After paying, send your proof here:\n{_site_url(inv.public_url)}paid/'
               + (('\n\n_Optional — pay ahead and save:_\n' + '\n'.join(tips)) if tips else '')
               + '\n\nThank you!')
    wa_ok = send_whatsapp(_invoice_phone(inv), wa_text)

    if not inv.sent_at:
        inv.sent_at = timezone.now()
        inv.save(update_fields=['sent_at'])
    return email_ok, wa_ok


# ══════════════════════════════════════════════════════════════
# Kulipa mapema (miezi 2, 3, 4, 6, 12) — ushauri tu, si deni
# ══════════════════════════════════════════════════════════════
PAY_AHEAD_MONTHS = (2, 3, 4, 6, 12)


def _renewal_objects(inv):
    """[(notice, obj)] kwa ankara hii, obj ikiwa website / email plan / domain (au None)."""
    from apps.models import EmailHostingPlan, ManagedWebsite, DomainRecord
    model = {'hosting': ManagedWebsite, 'email': EmailHostingPlan, 'domain': DomainRecord}
    return [(r, model[r.kind].objects.filter(pk=r.object_id).first())
            for r in inv.renewals.all().order_by('pk')]


def _line_for(r, obj, start, hosting_months=None):
    """(desc, amount, months) ya notice moja. hosting_months=None = baki na miezi ya notice."""
    if obj is None:
        return r.label, Decimal(str(r.amount)), r.months
    if r.kind == 'hosting':
        m = hosting_months or r.months
        return (*_hosting_line(obj, start, m), m)
    if r.kind == 'email':
        m = hosting_months or r.months
        return (*_email_line(obj, start, m), m)
    return (*_domain_line(obj, start, r.months), r.months)


def rebuild_lines(inv, hosting_months=None, pairs=None):
    """Andika upya mistari ya ankara kutoka kwenye notices zake (zote, au `pairs` zilizotolewa):
    hosting/email kwa `hosting_months` (None = kama zilivyo), domain kama ilivyo."""
    start_from = inv.issue_date or timezone.localdate()
    lines = []
    with transaction.atomic():
        for r, obj in (pairs if pairs is not None else _renewal_objects(inv)):
            desc, amount, months = _line_for(r, obj, _new_start(r.period_end, start_from), hosting_months)
            if (r.months, r.amount) != (months, amount):
                r.months, r.amount = months, amount
                r.save(update_fields=['months', 'amount'])
            lines.append({'desc': desc, 'qty': 1, 'unit_price': float(amount), 'amount': float(amount)})
        inv.line_items = lines
        inv.save(update_fields=['line_items'])
    return inv


def pay_ahead_options(inv):
    """
    Chaguo za kulipa hosting kwa miezi zaidi — kwa KUONYESHA tu (ankara yenyewe
    inabaki ya mwezi mmoja). Kila chaguo: miezi, jumla ya kulipa (pamoja na domain
    iliyo kwenye ankara), punguzo %, unachookoa, na hosting itafika lini.
    """
    if inv.is_paid or inv.paid_total > 0:
        return []
    pairs = [(r, o) for r, o in _renewal_objects(inv) if r.applied_at is None]
    hosting = [(r, o) for r, o in pairs if r.kind in ('hosting', 'email') and o is not None]
    if not hosting:
        return []
    fixed_extra = sum((Decimal(str(r.amount)) for r, _o in pairs if r.kind == 'domain'), Decimal('0'))
    start_from = inv.issue_date or timezone.localdate()
    first_end = min(_new_start(r.period_end, start_from) for r, _o in hosting)
    monthly = sum((Decimal(str(o.monthly_cost or 0)) for _r, o in hosting), Decimal('0'))
    out = []
    for m in PAY_AHEAD_MONTHS:
        total, pct = Decimal('0'), 0
        for r, o in hosting:
            if r.kind == 'hosting':
                p = o.price_for(m)
                total += Decimal(str(round(p['total'], 2)))
                pct = max(pct, float(p['discount_pct'] or 0))
            else:
                total += Decimal(str(o.monthly_cost or 0)) * m
        out.append({
            'months': m, 'label': '1 year' if m == 12 else f'{m} months',
            'hosting': total, 'total': total + fixed_extra, 'discount_pct': pct,
            'saving': monthly * m - total, 'per_month': total / m,
            'until': _add_months(first_end, m),
        })
    return out


def pay_ahead_text(inv, bullet='•'):
    """Mistari mifupi ya ushauri wa kulipa mapema (email / WhatsApp)."""
    rows = []
    for o in pay_ahead_options(inv):
        if o['months'] not in (3, 6, 12):
            continue
        save = f' — save {_money(o["saving"], inv.currency)} ({o["discount_pct"]:g}% off)' if o['saving'] > 0 else ''
        rows.append(f'{bullet} {o["label"]}: {_money(o["total"], inv.currency)}{save}')
    return rows


def fix_overbilled(send=True):
    """
    Rekebisha ankara za renewal zilizotengenezwa kwa miezi mingi (kosa la zamani:
    mteja asiye na rekodi ya malipo alipewa miezi 12). Hosting/email zinarudi kuwa
    mwezi MMOJA, mistari ya ankara inaandikwa upya, na mteja anatumiwa ankara
    iliyosahihishwa. Ankara zilizolipwa (au zenye malipo ya sehemu) haziguswi —
    hizo unaarifiwa uzishughulikie mwenyewe. Rudisha orodha ya ankara zilizorekebishwa.
    """
    from apps.models import EmailHostingPlan, Invoice, ManagedWebsite, DomainRecord

    fixed, skipped = [], []
    invoices = (Invoice.objects
                .filter(renewals__kind__in=('hosting', 'email'), renewals__months__gt=HOSTING_MONTHS,
                        renewals__applied_at__isnull=True)
                .exclude(status__in=('paid', 'cancelled')).distinct())
    for inv in invoices:
        if inv.proofs.filter(months__gt=1).exists():
            continue                     # mteja mwenyewe alichagua kulipa miezi zaidi — si kosa
        if inv.paid_total > 0:
            skipped.append(inv)
            continue
        old_total = inv.grand_total
        rebuild_lines(inv, HOSTING_MONTHS)
        fixed.append(inv)
        _activity('renewal_invoice', f'Corrected renewal invoice {inv.invoice_number} — {inv.display_client}',
                  rows=[('Was', _money(old_total, inv.currency)), ('Now', _money(inv.grand_total, inv.currency)),
                        ('Why', 'Hosting is billed one month at a time (old invoice used 12 months)')],
                  link=f'/manage/invoices/{inv.pk}/edit/', amount=inv.grand_total)
        if send:
            send_invoice(inv, corrected=True)
    for inv in skipped:
        _activity('renewal_invoice', f'Check renewal invoice {inv.invoice_number} — billed for many months',
                  rows=[('Client', inv.display_client), ('Total', _money(inv.grand_total, inv.currency)),
                        ('Paid', _money(inv.paid_total, inv.currency)),
                        ('Why', 'It already has a payment, so it was not changed automatically')],
                  link=f'/manage/invoices/{inv.pk}/edit/', amount=inv.grand_total)
    return fixed


def _current_end(kind, obj):
    return {'hosting': getattr(obj, 'hosting_end_date', None), 'email': getattr(obj, 'end_date', None),
            'domain': getattr(obj, 'expiry_date', None)}.get(kind)


def cancel_stale(today=None):
    """
    Huduma iliyolipiwa kwa njia nyingine (malipo ya mkono kwenye /manage, Pesapal ya portal,
    au tarehe kuhaririwa) wakati ankara yake ya renewal bado iko wazi: mstari huo unaondolewa
    kwenye ankara; ankara ikibaki tupu inafutwa (cancelled). Bila hii, vikumbusho vingeendelea
    na onyo la kipindi kipya lingezuiwa. Ankara yenye malipo haiguswi. Rudisha idadi ya ankara
    zilizobadilishwa.
    """
    from apps.models import Invoice

    today = today or timezone.localdate()
    changed = 0
    invoices = (Invoice.objects.filter(renewals__applied_at__isnull=True)
                .exclude(status__in=('paid', 'cancelled')).distinct())
    for inv in invoices:
        if inv.paid_total > 0:
            continue
        pairs = _renewal_objects(inv)
        stale = [r for r, o in pairs
                 if r.applied_at is None and (o is None or (_current_end(r.kind, o) or r.period_end) > r.period_end)]
        if not stale:
            continue
        with transaction.atomic():
            for r in stale:
                r.applied_at = timezone.now()           # imeshughulikiwa nje ya ankara hii
                r.save(update_fields=['applied_at'])
            left = [(r, o) for r, o in pairs if r not in stale and r.applied_at is None]
            if left:
                rebuild_lines(inv, pairs=left)
            else:
                inv.status = 'cancelled'
                inv.save(update_fields=['status'])
        changed += 1
        _activity('renewal_invoice',
                  f'Renewal invoice {inv.invoice_number} {"cancelled" if not left else "trimmed"} — '
                  f'{inv.display_client} renewed another way',
                  rows=[(r.label, 'already renewed') for r in stale],
                  link=f'/manage/invoices/{inv.pk}/edit/')
    return changed


def send_reminders(today=None):
    """Ukumbusho kwa ankara za renewal ambazo bado hazijalipwa. Rudisha idadi iliyotumwa."""
    from apps.models import RenewalNotice

    today = today or timezone.localdate()
    open_rows = (RenewalNotice.objects
                 .filter(applied_at__isnull=True)
                 .exclude(invoice__status__in=('paid', 'cancelled', 'draft'))
                 .select_related('invoice', 'invoice__client'))
    by_invoice = {}
    for r in open_rows:
        by_invoice.setdefault(r.invoice_id, []).append(r)

    sent = 0
    for rows in by_invoice.values():
        inv = rows[0].invoice
        if inv.is_paid:
            continue
        days = (inv.due_date - today).days if inv.due_date else None
        if days is None:
            continue
        # Hatua inayostahili: ndogo kabisa kati ya hatua ambazo siku hizi zimezifikia
        stages = sorted({s for r in rows for s in REMIND_STAGES.get(r.kind, ())})
        stage = next((s for s in stages if days <= s), None)
        if days < 0:
            stage = -1                      # imechelewa — ukumbusho mmoja wa mwisho
        if stage is None:
            continue
        last = min((r.last_stage for r in rows if r.last_stage is not None), default=None)
        if last is not None and stage >= last:
            continue
        email_ok, wa_ok = send_invoice(inv, stage=stage, today=today)
        if email_ok or wa_ok:
            RenewalNotice.objects.filter(pk__in=[r.pk for r in rows]).update(
                last_stage=stage, last_stage_at=timezone.now())
            sent += 1
    return sent


# ══════════════════════════════════════════════════════════════
# 4. Malipo: kuongeza muda + risiti
# ══════════════════════════════════════════════════════════════
def apply_renewals(inv, by=None):
    """Ankara imelipwa yote: sogeza tarehe mbele (mara moja tu). Rudisha orodha ya maelezo."""
    from apps.models import (RenewalNotice, ManagedWebsite, HostingPayment, DomainRecord,
                             DomainRenewalPayment, EmailHostingPlan, EmailHostingPayment)

    if not inv.is_paid:
        return []
    done = []
    today = timezone.localdate()
    ref = inv.paid_reference or inv.invoice_number
    user = by if getattr(by, 'pk', None) else None
    with transaction.atomic():
        for r in RenewalNotice.objects.select_for_update().filter(invoice=inv, applied_at__isnull=True):
            try:
                if r.kind == 'hosting':
                    site = ManagedWebsite.objects.select_for_update().filter(pk=r.object_id).first()
                    if site:
                        HostingPayment.objects.create(
                            website=site, amount=r.amount, payment_date=today, months_covered=r.months,
                            payment_method='Invoice', transaction_ref=ref[:100], recorded_by=user,
                            notes=f'Renewal invoice {inv.invoice_number}')
                        site.hosting_end_date = _add_months(_new_start(site.hosting_end_date, today), r.months)
                        fields = ['hosting_end_date', 'last_warning_stage', 'last_warning_at']
                        site.last_warning_stage = site.last_warning_at = None
                        if site.status in ('suspended', 'maintenance'):
                            site.status = 'active'
                            site.suspension_reason = ''
                            fields += ['status', 'suspension_reason']
                        site.save(update_fields=fields)
                        done.append(f'{r.label}: until {_fmt(site.hosting_end_date)}')
                elif r.kind == 'domain':
                    dom = DomainRecord.objects.select_for_update().filter(pk=r.object_id).first()
                    if dom:
                        new_end = _add_months(_new_start(dom.expiry_date, today), r.months)
                        DomainRenewalPayment.objects.create(
                            domain=dom, amount=r.amount, paid_date=today, renewed_until=new_end,
                            payment_method='Invoice', transaction_ref=ref[:100], recorded_by=user,
                            notes=f'Renewal invoice {inv.invoice_number}')
                        dom.expiry_date = new_end
                        dom.status = 'active'
                        dom.save(update_fields=['expiry_date', 'status'])
                        done.append(f'{r.label}: until {_fmt(new_end)}')
                elif r.kind == 'email':
                    plan = EmailHostingPlan.objects.select_for_update().filter(pk=r.object_id).first()
                    if plan:
                        EmailHostingPayment.objects.create(
                            plan=plan, amount=r.amount, payment_date=today, months_covered=r.months,
                            payment_method='Invoice', transaction_ref=ref[:100], recorded_by=user,
                            notes=f'Renewal invoice {inv.invoice_number}')
                        plan.end_date = _add_months(_new_start(plan.end_date, today), r.months)
                        plan.status = 'active'
                        plan.save(update_fields=['end_date', 'status'])
                        done.append(f'{r.label}: until {_fmt(plan.end_date)}')
                r.applied_at = timezone.now()
                r.save(update_fields=['applied_at'])
            except Exception:
                logger.exception('[renewals] kuongeza muda kumeshindikana: %s', r)
    return done


METHOD_MAP = (('mpesa', 'mpesa'), ('m-pesa', 'mpesa'), ('airtel', 'airtel'), ('tigo', 'tigopesa'),
              ('mixx', 'tigopesa'), ('halo', 'halopesa'), ('bank', 'bank'), ('cash', 'cash'))


def _receipt_method(raw):
    r = (raw or '').lower()
    return next((v for k, v in METHOD_MAP if k in r), 'other')


def create_receipt(inv, amount, method='', reference='', by=''):
    """Risiti ya malipo moja ya ankara — inahitaji mteja aithibitishe (sahihi) kwanza."""
    from apps.models import DevelopmentReceipt

    amount = Decimal(str(amount))
    site = None
    first = inv.renewals.filter(kind='hosting').first()
    if first:
        from apps.models import ManagedWebsite
        site = ManagedWebsite.objects.filter(pk=first.object_id).first()
    paid_all = inv.is_paid
    items = inv.items
    if not paid_all or abs(sum(Decimal(str(i['amount'])) for i in items) - amount) > Decimal('1'):
        # Malipo ya sehemu: risiti inaonyesha kiasi kilicholipwa sasa tu
        items = [{'desc': f'Payment for invoice {inv.invoice_number}', 'qty': 1,
                  'unit_price': float(amount), 'amount': float(amount)}]
    return DevelopmentReceipt.objects.create(
        website=site, client=inv.client,
        client_name_manual=inv.display_client, client_company_manual=inv.display_company or '',
        client_email_manual=inv.display_email or '', client_phone_manual=_invoice_phone(inv) or '',
        project_label=inv.project_name or inv.title,
        kind='full' if paid_all else 'partial',
        title=f'{inv.title} — {inv.invoice_number}'[:200],
        description=f'Payment for invoice {inv.invoice_number}',
        line_items=[{'desc': i['desc'], 'qty': i['qty'], 'unit_price': i['unit_price'],
                     'amount': i['amount']} for i in items],
        currency=inv.currency, amount_paid=amount,
        payment_method=_receipt_method(method), payment_reference=(reference or inv.invoice_number)[:120],
        payment_date=timezone.localdate(), received_by=(by or 'JamiiTek')[:120],
        is_published=True, require_signature=True,
    )


def receipt_sign_link(receipt):
    """Link ya KUTHIBITISHA risiti (sahihi kwanza) — si link ya risiti yenyewe."""
    return f'{receipt.verify_url}#confirm'


def send_receipt_confirm(inv, receipt):
    """Mtumie mteja link ya kuthibitisha kupokea risiti (email + WhatsApp)."""
    from apps.utils.customer_email import send_customer_email

    link = receipt_sign_link(receipt)
    amount = _money(receipt.amount_paid, receipt.currency)
    email_ok = False
    if inv.display_email:
        email_ok = send_customer_email(
            inv.display_email,
            f'Payment received — confirm your receipt {receipt.receipt_number}',
            (f'Dear {inv.display_client},\n\nThank you! We have received your payment of {amount} '
             f'for invoice {inv.invoice_number}.\n\nYour receipt {receipt.receipt_number} is ready. '
             'Please open the link below and confirm that you received it — it takes a few seconds '
             '(fingerprint, Face ID, or your signature). After that you can view and download your receipt.'),
            rows=[('Receipt', receipt.receipt_number), ('Invoice', inv.invoice_number), ('Amount paid', amount)],
            button=('Confirm & get your receipt', link, 'green'),
            category='receipt', chip=('✅ Paid', 'success'), reply_to=['info@jamiitek.com'])
    wa_ok = send_whatsapp(_invoice_phone(inv), (
        f'Hello {inv.display_client},\n\nThank you! We received your payment of *{amount}* '
        f'for invoice {inv.invoice_number}.\n\nYour receipt *{receipt.receipt_number}* is ready. '
        f'Confirm you received it here (a few seconds), then you can view and download it:\n{link}'))
    return email_ok, wa_ok


def after_payment(inv, amount, method='', reference='', by=None, user=None):
    """
    Inaitwa BAADA ya malipo kurekodiwa na ankara kuhifadhiwa (Mark paid au
    kuidhinisha uthibitisho). Risiti + link ya kuthibitisha + kuongeza muda.
    Rudisha dict ya kilichofanyika.
    """
    out = {'receipt': None, 'renewed': [], 'email': False, 'whatsapp': False}
    try:
        receipt = create_receipt(inv, amount, method=method, reference=reference, by=by or '')
        out['receipt'] = receipt
        # Kumbukumbu ya risiti kwenye historia ya malipo ya ankara
        payments = list(inv.payments or [])
        if payments:
            payments[-1]['receipt'] = receipt.receipt_number
            inv.payments = payments
            inv.save(update_fields=['payments'])
    except Exception:
        logger.exception('[renewals] risiti ya %s haikutengenezwa', inv.invoice_number)
        receipt = None
    if inv.is_paid:
        out['renewed'] = apply_renewals(inv, by=user)
    if receipt is not None:
        out['email'], out['whatsapp'] = send_receipt_confirm(inv, receipt)
    _activity('invoice_paid', f'Invoice {inv.invoice_number} payment recorded — {inv.display_client}',
              rows=[('Amount', _money(amount, inv.currency)), ('Reference', reference or '-'),
                    ('Receipt', receipt.receipt_number if receipt else 'not created')]
                   + [('Renewed', x) for x in out['renewed']],
              link=f'/manage/invoices/{inv.pk}/edit/', amount=amount)
    return out


def _activity(action, title, rows=None, link='', amount=None):
    try:
        from apps import activity
        activity.record(action, title, rows=rows, link=link, amount=amount)
    except Exception:
        logger.exception('[renewals] activity haikurekodiwa')
