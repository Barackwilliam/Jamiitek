"""
Duka ndani ya chat — katalogi, oda na malipo rahisi. HAKUNA AI.

MZUNGUKO (kila hatua ni namba, kama menyu ya USSD):

    "bidhaa"            -> orodha ya bidhaa (au makundi, zikiwa nyingi)
    "2"                 -> picha + bei ya bidhaa ya 2, "unataka ngapi?"
    "3"                 -> imeongezwa; 1. ongeza nyingine 2. maliza 3. ghairi
    "2"                 -> "tupe mahali pa kukuletea" (maandishi au location)
    "Sinza, Dar"        -> muhtasari; 1. thibitisha 2. ghairi
    "1"                 -> Oda #K7Q2 imehifadhiwa, mmiliki ameambiwa,
                           mteja anapewa maelekezo ya malipo ya MMILIKI
    "QWE123RTY" / picha -> namba ya muamala imehifadhiwa, mmiliki ameambiwa

KWA NINI BILA AI

Kila hatua ina majibu machache yanayojulikana (namba, idadi, mahali).
AI ingeongeza gharama ya Groq na nafasi ya kukosea bei. Hapa bei inatoka
kwenye database kila mara — mteja hawezi "kushawishi" bei mpya.

KUTOKA BILA KUKWAMA

Mteja akiandika kitu kisicho jibu la hatua (swali, salamu), hatumnasi:
hali inarudi 'chat', kikapu kinabaki, na injini inamjibu kwa AI kama
kawaida. Akiandika "bidhaa" tena, anaendelea pale alipoachia.

MALIPO

JamiiTek haishiki pesa. Mteja anaonyeshwa maelekezo ya malipo ya mmiliki
(BotConfig.payment_instructions — Lipa Namba / M-Pesa yake), anatuma
namba ya muamala, na mmiliki anathibitisha kwenye dashboard → Oda.
"""
import logging
import re
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Message, Order, Product

logger = logging.getLogger('chatbot.shop')

STATES = ('shop_browse', 'shop_qty', 'shop_cart', 'shop_address', 'shop_confirm', 'shop_payref')

TRIGGERS = {
    'bidhaa', 'bidhaa zenu', 'bidhaa zako', 'duka', 'katalogi', 'catalog', 'catalogue',
    'products', 'product', 'nunua', 'kununua', 'agiza', 'kuagiza', 'oda', 'order', 'shop',
    'menu ya bidhaa', 'orodha ya bidhaa', 'mna bidhaa gani', 'mnauza nini', 'unauza nini',
}
_WANT = re.compile(r'^(nataka|naomba|ningependa|nahitaji)\s+(ku)?(agiza|nunua|order)\b')
CANCEL = {'ghairi', 'cancel', 'acha', 'sitisha', 'futa oda', 'ghairi oda'}

# Namba kwa maneno — wateja wengi huandika "mbili" badala ya "2"
_WORDS = {'moja': 1, 'mbili': 2, 'tatu': 3, 'nne': 4, 'tano': 5, 'sita': 6, 'saba': 7,
          'nane': 8, 'tisa': 9, 'kumi': 10, 'one': 1, 'two': 2, 'three': 3}

MAX_LIST = 20       # WhatsApp: orodha ndefu zaidi haisomeki kwenye simu
CATEGORY_AFTER = 8  # bidhaa zaidi ya hizi + makundi 2+ => onyesha makundi kwanza
MAX_QTY = 99


# ── Msaada ────────────────────────────────────────────────────

def tzs(n):
    return f"TZS {int(n):,}"


def _norm(text):
    return re.sub(r'[^\w\s]', ' ', (text or '').lower()).strip()


def _number(text):
    """'2', 'namba 2', '2.', 'mbili' -> 2. Kitu kingine -> None."""
    t = _norm(text)
    if t in _WORDS:
        return _WORDS[t]
    m = re.fullmatch(r'(?:namba\s+|no\s+|#\s*)?(\d{1,3})', t)
    return int(m.group(1)) if m else None


def is_trigger(text):
    t = re.sub(r'\s+', ' ', _norm(text))
    return t in TRIGGERS or bool(_WANT.match(t))


def is_active(bot):
    return bool(bot.shop_enabled) and bot.products.filter(is_active=True).exists()


def _meta(conv):
    return conv.metadata.setdefault('shop', {})


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

    if not category and len(categories) >= 2 and total > CATEGORY_AFTER:
        shop['listing'] = {'kind': 'cat', 'items': categories[:MAX_LIST]}
        lines = [f"🛍️ *Bidhaa za {bot.business_name or bot.bot_name}*", "", "Chagua kundi:"]
        lines += [f"{i}. {c}" for i, c in enumerate(categories[:MAX_LIST], 1)]
    else:
        shop['listing'] = {'kind': 'prod', 'items': [p.id for p in products]}
        head = f"🛍️ *{category}*" if category else f"🛍️ *Bidhaa za {bot.business_name or bot.bot_name}*"
        lines = [head, ""]
        for i, p in enumerate(products, 1):
            lines.append(f"{i}. *{p.name}* — {tzs(p.price)}" + ("" if p.in_stock else " _(imeisha)_"))
        if total > len(products) and not category:
            lines += ["", f"_Zinaonyeshwa {len(products)} kati ya {total}. Uliza bidhaa nyingine kwa jina._"]
    lines += ["", "Andika *namba* unayotaka. Andika *ghairi* kuacha."]
    conv.metadata['shop'] = shop
    _set(conv, 'shop_browse')
    _say(wa, conv, phone, "\n".join(lines), jid)
    return True


def _pick(bot, wa, conv, phone, jid, n):
    listing = _meta(conv).get('listing') or {}
    items = listing.get('items') or []
    if not 1 <= n <= len(items):
        _say(wa, conv, phone, f"Chagua namba kati ya 1 na {len(items)}, au andika *ghairi*.", jid)
        return True
    if listing.get('kind') == 'cat':
        return _show_catalog(bot, wa, conv, phone, jid, category=items[n - 1])

    product = bot.products.filter(id=items[n - 1], is_active=True).first()
    if not product:
        return _show_catalog(bot, wa, conv, phone, jid)
    if not product.in_stock:
        _say(wa, conv, phone, f"Samahani, *{product.name}* imeisha kwa sasa. Chagua nyingine kwa namba.", jid)
        return True

    caption = f"*{product.name}*\n{tzs(product.price)}"
    if product.description:
        caption += f"\n{product.description}"
    _show_image(wa, conv, phone, product.image_url, caption, jid)
    _meta(conv)['pending'] = product.id
    _set(conv, 'shop_qty')
    _say(wa, conv, phone, "Unataka ngapi? Andika idadi (mfano: *2*).", jid)
    return True


def _cart_menu(bot, wa, conv, phone, jid, note=''):
    lines = _cart_lines(bot, _meta(conv).get('cart', []))
    rows, total = _cart_text(lines)
    _set(conv, 'shop_cart')
    _say(wa, conv, phone, "\n".join(filter(None, [
        note, "🧺 *Kikapu chako*", rows, f"*Jumla: {tzs(total)}*", "",
        "1. Ongeza bidhaa nyingine", "2. Maliza oda", "3. Ghairi",
    ])), jid)
    return True


def _qty(bot, wa, conv, phone, jid, n):
    if not 1 <= n <= MAX_QTY:
        _say(wa, conv, phone, f"Andika idadi kati ya 1 na {MAX_QTY}.", jid)
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
    return _cart_menu(bot, wa, conv, phone, jid, note=f"✅ {n} × {product.name} imeongezwa.")


def _ask_address(bot, wa, conv, phone, jid):
    if not _cart_lines(bot, _meta(conv).get('cart', [])):
        return _show_catalog(bot, wa, conv, phone, jid)
    _set(conv, 'shop_address')
    _say(wa, conv, phone, "📍 Tupe mahali pa kukuletea (mtaa / eneo), au tuma *location*.\n"
                          "Kama utakuja kuchukua mwenyewe, andika *nitachukua*.", jid)
    return True


def _confirm_menu(bot, wa, conv, phone, jid):
    shop = _meta(conv)
    rows, total = _cart_text(_cart_lines(bot, shop.get('cart', [])))
    _set(conv, 'shop_confirm')
    _say(wa, conv, phone, "\n".join([
        "📝 *Thibitisha oda yako*", rows, f"*Jumla: {tzs(total)}*",
        f"Mahali: {shop.get('address', '')}", "", "1. Thibitisha oda", "2. Ghairi",
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
    for _ in range(3):
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    bot=bot, conversation=conv, code=_new_code(bot), customer_name=name,
                    customer_phone=conv.customer_phone, items=items, total=total,
                    delivery=shop.get('address', '')[:300])
            break
        except IntegrityError:
            continue
    else:
        _say(wa, conv, phone, "Samahani, oda haikuhifadhiwa. Tafadhali jaribu tena.", jid)
        return True

    _notify_owner(bot, wa, conv, "\n".join([
        f"🛒 *Oda mpya #{order.code}*", "",
        f"Mteja: *{name or 'Mteja'}* — {_contact(conv)}", rows,
        f"*Jumla: {tzs(total)}*", f"Mahali: {order.delivery}", "",
        "Angalia JamiiBot dashboard → Oda.",
    ]))

    conv.metadata['shop'] = {'order': order.id}
    msg = [f"✅ *Oda #{order.code} imepokelewa!*", f"Jumla: *{tzs(total)}*"]
    if (bot.payment_instructions or '').strip():
        msg += ["", "*Jinsi ya kulipa:*", bot.payment_instructions.strip(), "",
                "Ukishalipa, tuma hapa *namba ya muamala* (au picha ya ujumbe wa malipo)."]
        _set(conv, 'shop_payref')
    else:
        msg += ["", "Tutawasiliana nawe hivi punde kuthibitisha oda yako. Asante! 🙏"]
        _set(conv, 'chat')
    _say(wa, conv, phone, "\n".join(msg), jid)
    return True


_REF = re.compile(r'\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,20}\b|\b\d{8,20}\b')


def _payment_ref(bot, wa, conv, phone, jid, text, msg_type):
    order = bot.orders.filter(id=_meta(conv).get('order')).first()
    if not order or order.status not in ('new', 'payment_sent'):
        _set(conv, 'chat')
        return False
    if msg_type == 'image':
        ref = '[picha ya malipo — iangalie WhatsApp]'
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
    _notify_owner(bot, wa, conv, "\n".join([
        f"💰 *Malipo — oda #{order.code}*", "",
        f"{order.customer_name or 'Mteja'} amesema amelipa {tzs(order.total)}.",
        f"Muamala: {order.payment_ref}", "",
        "Hakiki kwenye simu yako, kisha bonyeza *Imelipwa* kwenye dashboard → Oda.",
    ]))
    conv.metadata['shop'] = {}
    _set(conv, 'chat')
    _say(wa, conv, phone, f"🙏 Asante! Tumepokea taarifa ya malipo ya oda *#{order.code}*. "
                          "Tutathibitisha na kukujulisha.", jid)
    return True


def _contact(conv):
    ident = conv.customer_phone or ''
    return 'fungua chat kwenye WhatsApp ya biashara' if len(ident) >= 15 else ident


def _notify_owner(bot, wa, conv, text):
    """Mmiliki anajua kuhusu oda/malipo papo hapo — WhatsApp yake (na email kwa chat ya tovuti)."""
    if not bot.owner_digits or bot.is_owner(conv.customer_phone):
        return
    res = wa.send_text(bot.owner_whatsapp, text)
    if not res.get('success'):
        logger.warning('[%s] duka: taarifa kwa mmiliki haikufika: %s', bot.session_name, res.get('error'))


def _cancel(bot, wa, conv, phone, jid):
    conv.metadata['shop'] = {}
    _set(conv, 'chat')
    _say(wa, conv, phone, "Sawa, oda imeghairiwa. Andika *bidhaa* wakati wowote kuona bidhaa zetu. 🙏", jid)
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

    if is_trigger(text):
        # Kikapu kilichoachwa (aliuliza swali katikati) kinaendelea pale pale
        if _cart_lines(bot, _meta(conv).get('cart', [])):
            return _cart_menu(bot, wa, conv, phone, jid, note="Kikapu chako bado kipo.")
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
            _say(wa, conv, phone, "Andika mahali kwa maandishi, tuma *location*, au andika *nitachukua*.", jid)
            return True
        if t in ('nitachukua', 'nitakuja kuchukua', 'pickup'):
            address = 'Atakuja kuchukua mwenyewe'
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
        _say(wa, conv, phone, "Chagua 1, 2 au 3.", jid)
        return True
    if state == 'shop_confirm':
        if n == 1:
            return _place_order(bot, wa, conv, phone, jid)
        if n == 2:
            return _cancel(bot, wa, conv, phone, jid)
        _say(wa, conv, phone, "Chagua 1 kuthibitisha au 2 kughairi.", jid)
        return True
    return False


CUSTOMER_UPDATES = {
    'paid':      "✅ Malipo ya oda *#{code}* ({total}) yamethibitishwa. Asante! Tunaandaa oda yako.",
    'delivered': "📦 Oda *#{code}* imekamilika. Asante kwa kununua kwetu! 🙏",
    'cancelled': "Oda *#{code}* imeghairiwa. Kwa maswali, tujibu hapa.",
}


def mark(order, status):
    """
    Dashboard: mmiliki anabadilisha hali ya oda. Mteja wa WhatsApp anaarifiwa
    (paid / delivered / cancelled) — jibu kwa mazungumzo aliyoanzisha yeye.
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
    template = CUSTOMER_UPDATES.get(status)
    if not (template and jid):
        return                       # chat ya tovuti haina njia ya kumfikia mteja baadaye
    from .bridge import BaileysHandler
    text = template.format(code=order.code, total=tzs(order.total))
    try:
        res = BaileysHandler(order.bot).send_text(conv.customer_phone, text, jid=jid)
        if res.get('success'):
            Message.objects.create(conversation=conv, role='assistant', content=text)
    except Exception:
        logger.exception('[%s] duka: taarifa ya oda #%s kwa mteja imeshindwa',
                         order.bot.session_name, order.code)
