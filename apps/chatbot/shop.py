"""
Duka ndani ya chat — katalogi, oda na malipo rahisi. HAKUNA AI.

MZUNGUKO (kila hatua ni namba, kama menyu ya USSD):

    "bidhaa" / "products" -> orodha ya bidhaa (au makundi, zikiwa nyingi)
    "2"                 -> picha + bei ya bidhaa ya 2, "unataka ngapi?"
    "3"                 -> imeongezwa; 1. ongeza nyingine 2. maliza 3. ghairi
    "2"                 -> "tupe mahali pa kukuletea" (maandishi au location)
    "Sinza, Dar"        -> muhtasari; 1. thibitisha 2. ghairi
    "1"                 -> Oda #K7Q2 imehifadhiwa, mmiliki ameambiwa,
                           mteja anapewa maelekezo ya malipo ya MMILIKI
    "QWE123RTY" / picha -> namba ya muamala imehifadhiwa, mmiliki ameambiwa

LUGHA

Kila ujumbe uko kwa Kiswahili na English (TEXT). Lugha inafuata
BotConfig.language: 'en' -> English, 'sw' -> Kiswahili, 'sw+en' -> lugha
aliyotumia mteja kufungua duka ("products" -> English, "bidhaa" -> Kiswahili).

KWA NINI BILA AI

Kila hatua ina majibu machache yanayojulikana (namba, idadi, mahali).
AI ingeongeza gharama ya Groq na nafasi ya kukosea bei. Hapa bei inatoka
kwenye database kila mara — mteja hawezi "kushawishi" bei mpya.

KUTOKA BILA KUKWAMA

Mteja akiandika kitu kisicho jibu la hatua (swali, salamu), hatumnasi:
hali inarudi 'chat', kikapu kinabaki, na injini inamjibu kwa AI kama
kawaida. Akiandika "bidhaa" tena, anaendelea pale alipoachia.

MALIPO

JamiiTek haishiki pesa. Mteja anaonyeshwa njia za malipo za mmiliki
(BotConfig.payment_methods — Lipa Namba, namba za simu, akaunti za benki —
na payment_instructions kama maelezo ya ziada), anatuma namba ya muamala,
na mmiliki MWENYEWE anathibitisha kwenye dashboard → Orders ("Mark paid").
"""
import logging
import re
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Message, Order

logger = logging.getLogger('chatbot.shop')

STATES = ('shop_browse', 'shop_qty', 'shop_cart', 'shop_address', 'shop_confirm', 'shop_payref')

TRIGGERS_SW = {
    'bidhaa', 'bidhaa zenu', 'bidhaa zako', 'duka', 'katalogi', 'nunua', 'kununua', 'agiza',
    'kuagiza', 'oda', 'menu ya bidhaa', 'orodha ya bidhaa', 'mna bidhaa gani', 'mnauza nini',
    'unauza nini',
}
TRIGGERS_EN = {
    'products', 'product', 'catalog', 'catalogue', 'shop', 'order', 'buy', 'store',
    'what do you sell', 'show products', 'price list',
}
_WANT_SW = re.compile(r'^(nataka|naomba|ningependa|nahitaji)\s+(ku)?(agiza|nunua|order)\b')
_WANT_EN = re.compile(r'^(i\s+want|i\s+would\s+like|i\s+d\s+like|can\s+i)\s+(to\s+)?(order|buy|shop)\b')
CANCEL = {'ghairi', 'acha', 'sitisha', 'futa oda', 'ghairi oda', 'cancel', 'stop', 'cancel order'}
PICKUP = {'nitachukua', 'nitakuja kuchukua', 'pickup', 'pick up', 'i will pick up', 'collect'}

# Namba kwa maneno — wateja wengi huandika "mbili" badala ya "2"
_WORDS = {'moja': 1, 'mbili': 2, 'tatu': 3, 'nne': 4, 'tano': 5, 'sita': 6, 'saba': 7,
          'nane': 8, 'tisa': 9, 'kumi': 10, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
          'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}

MAX_LIST = 20       # WhatsApp: orodha ndefu zaidi haisomeki kwenye simu
CATEGORY_AFTER = 8  # bidhaa zaidi ya hizi + makundi 2+ => onyesha makundi kwanza
MAX_QTY = 99

TEXT = {
    'catalog_title': {'sw': "🛍️ *Bidhaa za {shop}*", 'en': "🛍️ *{shop} — products*"},
    'pick_category': {'sw': "Chagua kundi:", 'en': "Choose a category:"},
    'sold_out_tag':  {'sw': " _(imeisha)_", 'en': " _(sold out)_"},
    'showing':       {'sw': "_Zinaonyeshwa {n} kati ya {total}. Uliza bidhaa nyingine kwa jina._",
                      'en': "_Showing {n} of {total}. Ask for other products by name._"},
    'pick_hint':     {'sw': "Andika *namba* unayotaka. Andika *ghairi* kuacha.",
                      'en': "Reply with a *number*. Type *cancel* to stop."},
    'pick_range':    {'sw': "Chagua namba kati ya 1 na {n}, au andika *ghairi*.",
                      'en': "Choose a number from 1 to {n}, or type *cancel*."},
    'sold_out':      {'sw': "Samahani, *{name}* imeisha kwa sasa. Chagua nyingine kwa namba.",
                      'en': "Sorry, *{name}* is sold out right now. Choose another by number."},
    'ask_qty':       {'sw': "Unataka ngapi? Andika idadi (mfano: *2*).",
                      'en': "How many would you like? Reply with a quantity (e.g. *2*)."},
    'qty_range':     {'sw': "Andika idadi kati ya 1 na {n}.", 'en': "Reply with a quantity from 1 to {n}."},
    'added':         {'sw': "✅ {qty} × {name} imeongezwa.", 'en': "✅ {qty} × {name} added."},
    'cart_title':    {'sw': "🧺 *Kikapu chako*", 'en': "🧺 *Your cart*"},
    'total':         {'sw': "*Jumla: {total}*", 'en': "*Total: {total}*"},
    'cart_options':  {'sw': "1. Ongeza bidhaa nyingine\n2. Maliza oda\n3. Ghairi",
                      'en': "1. Add another product\n2. Checkout\n3. Cancel"},
    'cart_kept':     {'sw': "Kikapu chako bado kipo.", 'en': "Your cart is still here."},
    'choose_123':    {'sw': "Chagua 1, 2 au 3.", 'en': "Choose 1, 2 or 3."},
    'ask_address':   {'sw': "📍 Tupe mahali pa kukuletea (mtaa / eneo), au tuma *location*.\n"
                            "Kama utakuja kuchukua mwenyewe, andika *nitachukua*.",
                      'en': "📍 Where should we deliver? Send your area / street, or share your *location*.\n"
                            "If you will collect it yourself, type *pickup*."},
    'address_again': {'sw': "Andika mahali kwa maandishi, tuma *location*, au andika *nitachukua*.",
                      'en': "Type the delivery place, share your *location*, or type *pickup*."},
    'pickup':        {'sw': "Atakuja kuchukua mwenyewe", 'en': "Customer will pick up"},
    'confirm_title': {'sw': "📝 *Thibitisha oda yako*", 'en': "📝 *Confirm your order*"},
    'place':         {'sw': "Mahali: {place}", 'en': "Delivery: {place}"},
    'confirm_opts':  {'sw': "1. Thibitisha oda\n2. Ghairi", 'en': "1. Confirm order\n2. Cancel"},
    'choose_12':     {'sw': "Chagua 1 kuthibitisha au 2 kughairi.", 'en': "Choose 1 to confirm or 2 to cancel."},
    'save_failed':   {'sw': "Samahani, oda haikuhifadhiwa. Tafadhali jaribu tena.",
                      'en': "Sorry, the order could not be saved. Please try again."},
    'received':      {'sw': "✅ *Oda #{code} imepokelewa!*\nJumla: *{total}*",
                      'en': "✅ *Order #{code} received!*\nTotal: *{total}*"},
    'send_ref':      {'sw': "Ukishalipa, tuma hapa *namba ya muamala* (au picha ya ujumbe wa malipo).",
                      'en': "After paying, send the *transaction number* here "
                            "(or a screenshot of the payment message)."},
    'will_contact':  {'sw': "Tutawasiliana nawe hivi punde kuthibitisha oda yako. Asante! 🙏",
                      'en': "We will contact you shortly to confirm your order. Thank you! 🙏"},
    'paid_thanks':   {'sw': "🙏 Asante! Tumepokea taarifa ya malipo ya oda *#{code}*. "
                            "Tutathibitisha na kukujulisha.",
                      'en': "🙏 Thank you! We received your payment details for order *#{code}*. "
                            "We will confirm and let you know."},
    'cancelled':     {'sw': "Sawa, oda imeghairiwa. Andika *bidhaa* wakati wowote kuona bidhaa zetu. 🙏",
                      'en': "OK, the order is cancelled. Type *products* any time to see what we sell. 🙏"},
    # Mmiliki akibadilisha hali ya oda kwenye dashboard -> mteja wa WhatsApp
    'upd_paid':      {'sw': "✅ Malipo ya oda *#{code}* ({total}) yamethibitishwa. Asante! Tunaandaa oda yako.",
                      'en': "✅ Payment for order *#{code}* ({total}) is confirmed. Thank you! "
                            "We are preparing your order."},
    'upd_delivered': {'sw': "📦 Oda *#{code}* imekamilika. Asante kwa kununua kwetu! 🙏",
                      'en': "📦 Order *#{code}* is complete. Thank you for shopping with us! 🙏"},
    'upd_cancelled': {'sw': "Oda *#{code}* imeghairiwa. Kwa maswali, tujibu hapa.",
                      'en': "Order *#{code}* has been cancelled. Reply here if you have any questions."},
    # Taarifa kwa MMILIKI — lugha ya bot ('en' -> English, vinginevyo Kiswahili)
    'owner_order':   {'sw': "🛒 *Oda mpya #{code}*\n\nMteja: *{who}* — {contact}\n{rows}\n"
                            "*Jumla: {total}*\nMahali: {place}\n\nAngalia JamiiBot dashboard → Orders.",
                      'en': "🛒 *New order #{code}*\n\nCustomer: *{who}* — {contact}\n{rows}\n"
                            "*Total: {total}*\nDelivery: {place}\n\nOpen JamiiBot dashboard → Orders."},
    'owner_paid':    {'sw': "💰 *Malipo — oda #{code}*\n\n{who} amesema amelipa {total}.\nMuamala: {ref}\n\n"
                            "Hakiki kwenye simu yako, kisha bonyeza *Mark paid* kwenye dashboard → Orders.",
                      'en': "💰 *Payment — order #{code}*\n\n{who} says they paid {total}.\nTransaction: {ref}\n\n"
                            "Check your phone, then press *Mark paid* on the dashboard → Orders."},
    'owner_cancelled': {'sw': "❌ *Oda #{code} imeghairiwa* na {who}.",
                        'en': "❌ *Order #{code} was cancelled* by {who}."},
    'customer':      {'sw': "Mteja", 'en': "Customer"},
    'open_chat':     {'sw': "fungua chat kwenye WhatsApp ya biashara", 'en': "open the chat on the business WhatsApp"},
    'screenshot':    {'sw': "[picha ya malipo — iangalie WhatsApp]", 'en': "[payment screenshot — check WhatsApp]"},
}


# ── Njia za malipo za mmiliki ─────────────────────────────────

NETWORKS = {
    'mpesa':    'M-Pesa',
    'mixx':     'Mixx by Yas',
    'airtel':   'Airtel Money',
    'halopesa': 'Halopesa',
}
KINDS = ('lipa', 'mobile', 'bank')
MAX_METHODS = 6

PAY_TEXT = {
    'title':  {'sw': "💳 *Jinsi ya kulipa — {total}*", 'en': "💳 *How to pay — {total}*"},
    'lipa':   {'sw': "Lipa Namba ({net})", 'en': "Lipa Namba ({net})"},
    'mobile': {'sw': "{net} — namba ya simu", 'en': "{net} — phone number"},
    'bank':   {'sw': "Benki — {bank}", 'en': "Bank — {bank}"},
    'name':   {'sw': "Jina: {name}", 'en': "Name: {name}"},
    'ref':    {'sw': "Kwenye maelezo ya malipo andika *{code}* ukiweza.",
               'en': "Use *{code}* as the payment reference if you can."},
}
_KEYCAPS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣']


def clean_method(kind, provider, number, name):
    """(method, None) au (None, kosa) — kutoka fomu ya dashboard."""
    kind = (kind or '').strip()
    provider = (provider or '').strip()[:60]
    name = re.sub(r'\s+', ' ', (name or '')).strip()[:80]
    raw = (number or '').strip()
    if kind not in KINDS:
        return None, "Choose a payment type."
    if kind in ('lipa', 'mobile') and provider not in NETWORKS:
        return None, "Choose the mobile network."
    if kind == 'bank' and not provider:
        return None, "Enter the bank name."
    if not name:
        return None, "Enter the name the customer will see when paying."
    if kind == 'mobile':
        digits = re.sub(r'\D', '', raw)
        if digits.startswith('255') and len(digits) == 12:
            digits = '0' + digits[3:]
        if not re.fullmatch(r'0[67]\d{8}', digits):
            return None, "Enter a valid phone number, e.g. 0754 123 456."
        number = f"{digits[:4]} {digits[4:7]} {digits[7:]}"
    elif kind == 'lipa':
        number = re.sub(r'\s', '', raw)
        if not re.fullmatch(r'\d{5,10}', number):
            return None, "Enter the Lipa Namba (numbers only, e.g. 555777)."
    else:
        number = re.sub(r'\s+', ' ', raw)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 -]{4,29}', number):
            return None, "Enter a valid account number."
    return {'kind': kind, 'provider': provider, 'number': number, 'name': name}, None


def method_label(m, lang='en'):
    net = NETWORKS.get(m.get('provider'), m.get('provider', ''))
    return PAY_TEXT[m['kind']][lang].format(net=net, bank=m.get('provider', ''))


def payment_text(bot, lang, code, total):
    """Maelekezo ya malipo kwa mteja, au '' kama mmiliki hajaweka njia yoyote."""
    methods = [m for m in (bot.payment_methods or []) if m.get('kind') in KINDS][:MAX_METHODS]
    note = (bot.payment_instructions or '').strip()
    if not methods and not note:
        return ''
    out = [PAY_TEXT['title'][lang].format(total=tzs(total))]
    for i, m in enumerate(methods):
        mark = _KEYCAPS[i] if len(methods) > 1 else '▪️'
        out += ["", f"{mark} *{method_label(m, lang)}*", f"*{m['number']}*",
                PAY_TEXT['name'][lang].format(name=m['name'])]
    if note:
        out += ["", note]
    if methods:
        out += ["", PAY_TEXT['ref'][lang].format(code=code)]
    return "\n".join(out)


# ── Msaada ────────────────────────────────────────────────────

def tzs(n):
    return f"TZS {int(n):,}"


def _norm(text):
    return re.sub(r'[^\w\s]', ' ', (text or '').lower()).strip()


def _number(text):
    """'2', 'namba 2', '2.', 'mbili', 'two' -> 2. Kitu kingine -> None."""
    t = _norm(text)
    if t in _WORDS:
        return _WORDS[t]
    m = re.fullmatch(r'(?:namba\s+|no\s+|number\s+|#\s*)?(\d{1,3})', t)
    return int(m.group(1)) if m else None


def trigger_lang(text):
    """'sw' / 'en' kama ujumbe unafungua duka, vinginevyo None."""
    t = re.sub(r'\s+', ' ', _norm(text))
    if t in TRIGGERS_SW or _WANT_SW.match(t):
        return 'sw'
    if t in TRIGGERS_EN or _WANT_EN.match(t):
        return 'en'
    return None


def is_trigger(text):
    return trigger_lang(text) is not None


def is_active(bot):
    return bool(bot.shop_enabled) and bot.products.filter(is_active=True).exists()


def _meta(conv):
    return conv.metadata.setdefault('shop', {})


def lang_for(bot, chosen=None):
    """Lugha ya majibu: ya bot ('sw' / 'en'), au kwa 'sw+en' aliyotumia mteja."""
    if bot.language in ('sw', 'en'):
        return bot.language
    return chosen if chosen in ('sw', 'en') else 'sw'


def _t(bot, conv, key, **kw):
    return TEXT[key][lang_for(bot, _meta(conv).get('lang'))].format(**kw)


def _owner(bot, key, **kw):
    return TEXT[key]['en' if bot.language == 'en' else 'sw'].format(**kw)


def _set(conv, state):
    conv.metadata['state'] = state
    conv.save(update_fields=['metadata'])


def _say(wa, conv, phone, text, jid=None):
    res = wa.send_text(phone, text, jid=jid)
    if not res.get('success'):
        logger.error('[%s] duka: ujumbe haukufika kwa %s: %s',
                     conv.bot.session_name, phone, res.get('error'))
    Message.objects.create(conversation=conv, role='assistant', content=text)


def _show_image(wa, conv, phone, url, caption, jid=None):
    """Picha + maelezo. Handler isiyo na send_image (au ikishindwa) -> maandishi tu."""
    send_image = getattr(wa, 'send_image', None)
    res = send_image(phone, url, caption, jid=jid) if (send_image and url) else None
    if not res or not res.get('success'):
        res = wa.send_text(phone, caption, jid=jid)
    Message.objects.create(conversation=conv, role='assistant',
                           content=f"[Picha: {url}]\n{caption}" if url else caption)


def _products(bot, category=None):
    qs = bot.products.filter(is_active=True)
    if category:
        qs = qs.filter(category=category)
    return list(qs[:MAX_LIST])


def _cart_lines(bot, cart):
    """[(product, qty)] kwa bidhaa zilizopo bado. Bei ni ya SASA kutoka database."""
    ids = [c['id'] for c in cart]
    found = {p.id: p for p in bot.products.filter(id__in=ids, is_active=True)}
    return [(found[c['id']], c['qty']) for c in cart if c['id'] in found]


def _cart_text(lines):
    rows = [f"• {q} × {p.name} — {tzs(p.price * q)}" for p, q in lines]
    total = sum(p.price * q for p, q in lines)
    return "\n".join(rows), total


def _new_code(bot):
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # bila O/0, I/1 — rahisi kusoma kwa simu
    for _ in range(8):
        code = ''.join(secrets.choice(alphabet) for _ in range(4))
        if not bot.orders.filter(code=code).exists():
            return code
    return ''.join(secrets.choice(alphabet) for _ in range(6))


# ── Hatua ─────────────────────────────────────────────────────

def _show_catalog(bot, wa, conv, phone, jid, category=None):
    shop = _meta(conv)
    products = _products(bot, category)
    categories = sorted({c for c in bot.products.filter(is_active=True)
                         .exclude(category='').values_list('category', flat=True)})
    total = bot.products.filter(is_active=True).count()
    title = _t(bot, conv, 'catalog_title', shop=bot.business_name or bot.bot_name)

    if not category and len(categories) >= 2 and total > CATEGORY_AFTER:
        shop['listing'] = {'kind': 'cat', 'items': categories[:MAX_LIST]}
        lines = [title, "", _t(bot, conv, 'pick_category')]
        lines += [f"{i}. {c}" for i, c in enumerate(categories[:MAX_LIST], 1)]
    else:
        shop['listing'] = {'kind': 'prod', 'items': [p.id for p in products]}
        lines = [f"🛍️ *{category}*" if category else title, ""]
        for i, p in enumerate(products, 1):
            lines.append(f"{i}. *{p.name}* — {tzs(p.price)}"
                         + ("" if p.in_stock else _t(bot, conv, 'sold_out_tag')))
        if total > len(products) and not category:
            lines += ["", _t(bot, conv, 'showing', n=len(products), total=total)]
    lines += ["", _t(bot, conv, 'pick_hint')]
    _set(conv, 'shop_browse')
    _say(wa, conv, phone, "\n".join(lines), jid)
    return True


def _pick(bot, wa, conv, phone, jid, n):
    listing = _meta(conv).get('listing') or {}
    items = listing.get('items') or []
    if not 1 <= n <= len(items):
        _say(wa, conv, phone, _t(bot, conv, 'pick_range', n=len(items)), jid)
        return True
    if listing.get('kind') == 'cat':
        return _show_catalog(bot, wa, conv, phone, jid, category=items[n - 1])

    product = bot.products.filter(id=items[n - 1], is_active=True).first()
    if not product:
        return _show_catalog(bot, wa, conv, phone, jid)
    if not product.in_stock:
        _say(wa, conv, phone, _t(bot, conv, 'sold_out', name=product.name), jid)
        return True

    caption = f"*{product.name}*\n{tzs(product.price)}"
    if product.description:
        caption += f"\n{product.description}"
    _show_image(wa, conv, phone, product.image_url, caption, jid)
    _meta(conv)['pending'] = product.id
    _set(conv, 'shop_qty')
    _say(wa, conv, phone, _t(bot, conv, 'ask_qty'), jid)
    return True


def _cart_menu(bot, wa, conv, phone, jid, note=''):
    rows, total = _cart_text(_cart_lines(bot, _meta(conv).get('cart', [])))
    _set(conv, 'shop_cart')
    _say(wa, conv, phone, "\n".join(filter(None, [
        note, _t(bot, conv, 'cart_title'), rows, _t(bot, conv, 'total', total=tzs(total)), "",
        _t(bot, conv, 'cart_options'),
    ])), jid)
    return True


def _qty(bot, wa, conv, phone, jid, n):
    if not 1 <= n <= MAX_QTY:
        _say(wa, conv, phone, _t(bot, conv, 'qty_range', n=MAX_QTY), jid)
        return True
    shop = _meta(conv)
    pid = shop.pop('pending', None)
    product = bot.products.filter(id=pid, is_active=True).first() if pid else None
    if not product:
        return _show_catalog(bot, wa, conv, phone, jid)
    cart = shop.setdefault('cart', [])
    for item in cart:
        if item['id'] == product.id:
            item['qty'] = min(MAX_QTY, item['qty'] + n)
            break
    else:
        cart.append({'id': product.id, 'qty': n})
    return _cart_menu(bot, wa, conv, phone, jid, note=_t(bot, conv, 'added', qty=n, name=product.name))


def _ask_address(bot, wa, conv, phone, jid):
    if not _cart_lines(bot, _meta(conv).get('cart', [])):
        return _show_catalog(bot, wa, conv, phone, jid)
    _set(conv, 'shop_address')
    _say(wa, conv, phone, _t(bot, conv, 'ask_address'), jid)
    return True


def _confirm_menu(bot, wa, conv, phone, jid):
    shop = _meta(conv)
    rows, total = _cart_text(_cart_lines(bot, shop.get('cart', [])))
    _set(conv, 'shop_confirm')
    _say(wa, conv, phone, "\n".join([
        _t(bot, conv, 'confirm_title'), rows, _t(bot, conv, 'total', total=tzs(total)),
        _t(bot, conv, 'place', place=shop.get('address', '')), "", _t(bot, conv, 'confirm_opts'),
    ]), jid)
    return True


def _place_order(bot, wa, conv, phone, jid):
    shop = _meta(conv)
    lines = _cart_lines(bot, shop.get('cart', []))
    if not lines:
        return _show_catalog(bot, wa, conv, phone, jid)
    rows, total = _cart_text(lines)
    items = [{'product_id': p.id, 'name': p.name, 'price': p.price, 'qty': q} for p, q in lines]
    name = conv.customer_name or conv.wa_contact_name or ''
    lang = lang_for(bot, shop.get('lang'))
    for _ in range(3):
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    bot=bot, conversation=conv, code=_new_code(bot), customer_name=name,
                    customer_phone=conv.customer_phone, items=items, total=total,
                    delivery=shop.get('address', '')[:300], lang=lang)
            break
        except IntegrityError:
            continue
    else:
        _say(wa, conv, phone, _t(bot, conv, 'save_failed'), jid)
        return True

    _notify_owner(bot, wa, conv, _owner(
        bot, 'owner_order', code=order.code, who=name or _owner(bot, 'customer'),
        contact=_contact(bot, conv), rows=rows, total=tzs(total), place=order.delivery))

    msg = [_t(bot, conv, 'received', code=order.code, total=tzs(total))]
    pay = payment_text(bot, lang, order.code, total)
    if pay:
        msg += ["", pay, "", _t(bot, conv, 'send_ref')]
        next_state = 'shop_payref'
    else:
        msg += ["", _t(bot, conv, 'will_contact')]
        next_state = 'chat'
    conv.metadata['shop'] = {'order': order.id, 'lang': shop.get('lang')}
    _set(conv, next_state)
    _say(wa, conv, phone, "\n".join(msg), jid)
    return True


_REF = re.compile(r'\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,20}\b|\b\d{8,20}\b')


def _payment_ref(bot, wa, conv, phone, jid, text, msg_type):
    order = bot.orders.filter(id=_meta(conv).get('order')).first()
    if not order or order.status not in ('new', 'payment_sent'):
        _set(conv, 'chat')
        return False
    if msg_type == 'image':
        ref = _owner(bot, 'screenshot')
    else:
        m = _REF.search((text or '').upper())
        if not m:
            # Si namba ya muamala — huenda ni swali. Tusimnase: AI imjibu.
            _set(conv, 'chat')
            return False
        ref = m.group(0)
    order.payment_ref = ref[:60]
    order.status = 'payment_sent'
    order.save(update_fields=['payment_ref', 'status', 'updated_at'])
    _notify_owner(bot, wa, conv, _owner(
        bot, 'owner_paid', code=order.code, who=order.customer_name or _owner(bot, 'customer'),
        total=tzs(order.total), ref=order.payment_ref))
    reply = _t(bot, conv, 'paid_thanks', code=order.code)
    conv.metadata['shop'] = {}
    _set(conv, 'chat')
    _say(wa, conv, phone, reply, jid)
    return True


def _contact(bot, conv):
    ident = conv.customer_phone or ''
    return _owner(bot, 'open_chat') if len(ident) >= 15 else ident


def _notify_owner(bot, wa, conv, text):
    """Mmiliki anajua kuhusu oda/malipo papo hapo — WhatsApp yake (na email kwa chat ya tovuti)."""
    if not bot.owner_digits or bot.is_owner(conv.customer_phone):
        return
    res = wa.send_text(bot.owner_whatsapp, text)
    if not res.get('success'):
        logger.warning('[%s] duka: taarifa kwa mmiliki haikufika: %s', bot.session_name, res.get('error'))


def _cancel(bot, wa, conv, phone, jid):
    # Baada ya kuthibitisha (inasubiri malipo) oda ipo tayari: ighairi kweli, mmiliki ajue
    order = bot.orders.filter(id=_meta(conv).get('order'), status='new').first()
    if order:
        order.status = 'cancelled'
        order.save(update_fields=['status', 'updated_at'])
        _notify_owner(bot, wa, conv, _owner(bot, 'owner_cancelled', code=order.code,
                                            who=order.customer_name or _owner(bot, 'customer')))
    reply = _t(bot, conv, 'cancelled')
    conv.metadata['shop'] = {}
    _set(conv, 'chat')
    _say(wa, conv, phone, reply, jid)
    return True


# ── Mlango mkuu ──────────────────────────────────────────────

def handle(bot, wa, conv, phone, text, msg_data):
    """
    True = duka limejibu (injini isimame hapa). False = endelea na mtiririko wa kawaida.
    Inaitwa na `_process_message` kwa hali ya 'chat' na hali zote za duka.
    """
    state = conv.metadata.get('state', 'chat')
    in_shop = state in STATES
    jid = msg_data.get('jid')
    msg_type = msg_data.get('msg_type', 'text')

    if not is_active(bot):
        if in_shop:
            _set(conv, 'chat')
        return False

    t = _norm(text)
    if in_shop and t in CANCEL:
        return _cancel(bot, wa, conv, phone, jid)

    if state == 'shop_payref':
        return _payment_ref(bot, wa, conv, phone, jid, text, msg_type)

    lang = trigger_lang(text)
    if lang:
        _meta(conv)['lang'] = lang          # 'sw+en': jibu kwa lugha aliyotumia mteja
        # Kikapu kilichoachwa (aliuliza swali katikati) kinaendelea pale pale
        if _cart_lines(bot, _meta(conv).get('cart', [])):
            return _cart_menu(bot, wa, conv, phone, jid, note=_t(bot, conv, 'cart_kept'))
        return _show_catalog(bot, wa, conv, phone, jid)

    if not in_shop:
        return False

    if state == 'shop_address':
        if msg_type == 'location':
            loc = msg_data.get('location') or {}
            address = loc.get('name') or loc.get('address') or \
                f"Location: https://maps.google.com/?q={loc.get('latitude')},{loc.get('longitude')}"
        elif msg_type == 'text' and 2 <= len(text.strip()) <= 300:
            address = text.strip()
        else:
            _say(wa, conv, phone, _t(bot, conv, 'address_again'), jid)
            return True
        if t in PICKUP:
            address = _owner(bot, 'pickup')
        _meta(conv)['address'] = address
        return _confirm_menu(bot, wa, conv, phone, jid)

    n = _number(text)
    if n is None:
        # Si jibu la hatua hii — mteja anauliza kitu kingine. Kikapu kinabaki.
        _set(conv, 'chat')
        return False

    if state == 'shop_browse':
        return _pick(bot, wa, conv, phone, jid, n)
    if state == 'shop_qty':
        return _qty(bot, wa, conv, phone, jid, n)
    if state == 'shop_cart':
        if n == 1:
            return _show_catalog(bot, wa, conv, phone, jid)
        if n == 2:
            return _ask_address(bot, wa, conv, phone, jid)
        if n == 3:
            return _cancel(bot, wa, conv, phone, jid)
        _say(wa, conv, phone, _t(bot, conv, 'choose_123'), jid)
        return True
    if state == 'shop_confirm':
        if n == 1:
            return _place_order(bot, wa, conv, phone, jid)
        if n == 2:
            return _cancel(bot, wa, conv, phone, jid)
        _say(wa, conv, phone, _t(bot, conv, 'choose_12'), jid)
        return True
    return False


CUSTOMER_UPDATES = {'paid': 'upd_paid', 'delivered': 'upd_delivered', 'cancelled': 'upd_cancelled'}


def mark(order, status):
    """
    Dashboard: mmiliki anabadilisha hali ya oda. Mteja wa WhatsApp anaarifiwa
    (paid / delivered / cancelled) kwa lugha ya oda — jibu kwa mazungumzo aliyoanzisha yeye.
    """
    if order.status == status:
        return
    order.status = status
    fields = ['status', 'updated_at']
    if status == 'paid' and not order.paid_at:
        order.paid_at = timezone.now()
        fields.append('paid_at')
    order.save(update_fields=fields)

    conv = order.conversation
    jid = (conv.metadata or {}).get('jid') if conv else None
    key = CUSTOMER_UPDATES.get(status)
    if not (key and jid):
        return                       # chat ya tovuti haina njia ya kumfikia mteja baadaye
    from .bridge import BaileysHandler
    text = TEXT[key][lang_for(order.bot, order.lang)].format(code=order.code, total=tzs(order.total))
    try:
        res = BaileysHandler(order.bot).send_text(conv.customer_phone, text, jid=jid)
        if res.get('success'):
            Message.objects.create(conversation=conv, role='assistant', content=text)
    except Exception:
        logger.exception('[%s] duka: taarifa ya oda #%s kwa mteja imeshindwa',
                         order.bot.session_name, order.code)
