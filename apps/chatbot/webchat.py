"""
Chat ya website — JamiiBot kwenye tovuti ya mteja.

Mmiliki akishafungua bot na kuiunganisha WhatsApp, anaweza pia kuiweka
kwenye tovuti yake mwenyewe kwa mstari mmoja:

    <script src="https://www.jamiitek.com/chatbot/widget/<BOT_ID>.js" defer></script>

Script hiyo inatengeneza kitufe kinachoelea (floating button) chini
kulia. Mtembeleaji akibonyeza, dirisha la chat linafunguka lenye
mwonekano kama WhatsApp. Kila ujumbe unaenda:

    browser -> POST /chatbot/web/<BOT_ID>/ -> _process_message -> jibu

INJINI NI ILE ILE. `_process_message` haijui kama ujumbe umetoka
WhatsApp au tovuti — tunaipa `WebHandler` badala ya `BaileysHandler`.
Handler hiyo inanasa majibu ya bot (yanarudi kwenye browser) badala ya
kuyatuma WhatsApp. State machine, AI, rate limit, handoff — vyote
vinabaki kama vilivyo.

HANDOFF KWENYE TOVUTI
Mtembeleaji akihitaji binadamu:
  1. Taarifa inaenda kwa mmiliki — WhatsApp ya biashara NA email yake.
  2. Mtembeleaji anapewa namba ya mmiliki aipigie moja kwa moja
     (tovuti haina namba ya mtembeleaji, kwa hiyo yeye ndiye anayepiga).
"""
import json
import logging
import re
import secrets

from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import BotConfig, Conversation, Message

logger = logging.getLogger('chatbot.webchat')


# ══════════════════════════════════════════════════════════════
#  HANDLER YA TOVUTI
# ══════════════════════════════════════════════════════════════

class WebHandler:
    """
    Interface ile ile ya `BaileysHandler` (`send_text`, `mark_as_read`,
    `send_interactive_list`) lakini:

      • jibu kwa MTEMBELEAJI linanaswa kwenye `self.replies` — linarudi
        kwenye browser kama JSON.
      • taarifa kwa MMILIKI (`owner_whatsapp`) inaendelea kwa WhatsApp
        halisi kupitia bridge, NA kwa email ya mmiliki.

    Tofauti kati ya hizo mbili ni `to`: ikiwa ni funguo ya mtembeleaji,
    ni jibu la chat; vinginevyo ni taarifa ya mmiliki.
    """

    def __init__(self, bot, customer_key):
        self.bot = bot
        self.customer_key = str(customer_key)
        self.jid = None
        self.replies = []
        self.owner_notified = False
        self.paused = False      # injini inaiweka True bot ikiwa imesimama

    # -- interface inayotarajiwa na injini --------------------------

    def is_configured(self):
        return True

    def mark_as_read(self, message_id):
        return {'success': True}

    def send_text(self, to, message, jid=None):
        if str(to) == self.customer_key:
            # Jibu la bot kwa mtembeleaji
            if message:
                self.replies.append(message)
            return {'success': True, 'message_id': f'web_{len(self.replies)}'}
        # `to` si mtembeleaji => ni taarifa ya mmiliki (handoff)
        return self._notify_owner(message)

    def send_image(self, to, url, caption='', jid=None):
        """Picha ya bidhaa: widget inaigeuza `[[img:URL]]` kuwa <img> (https pekee)."""
        if str(to) != self.customer_key:
            return self._notify_owner(caption)
        if url and str(url).startswith('https://'):
            self.replies.append(f"[[img:{url}]]\n{caption}".strip())
        elif caption:
            self.replies.append(caption)
        return {'success': True, 'message_id': f'web_{len(self.replies)}'}

    def send_interactive_list(self, to, header, body, button_text, sections):
        """Orodha ya huduma inakuwa maandishi — browser haina UI ya WhatsApp."""
        lines = [f'*{header}*', '', body, '']
        n = 0
        for section in sections or []:
            title = section.get('title')
            if title:
                lines.append(f'_{title}_')
            for row in section.get('rows', []):
                n += 1
                line = f"{n}. *{row.get('title', '')}*"
                desc = row.get('description')
                if desc:
                    line += f"\n   {desc}"
                lines.append(line)
            lines.append('')
        if not n:
            return {'success': False, 'error': 'Hakuna vipengele'}
        lines.append('Andika namba ya huduma unayotaka, au uliza swali lako moja kwa moja.')
        return self.send_text(to, '\n'.join(lines).strip())

    def send_interactive_buttons(self, to, body, buttons):
        lines = [body, '']
        for i, b in enumerate(buttons[:3], start=1):
            lines.append(f"{i}. {b.get('title', '')}")
        return self.send_text(to, '\n'.join(lines).strip())

    # -- taarifa ya mmiliki -----------------------------------------

    def _notify_owner(self, message):
        """Taarifa ya handoff -> WhatsApp ya biashara + email ya mmiliki."""
        ok = False

        # 1) WhatsApp ya biashara (kama bridge na session zipo)
        try:
            from .bridge import BaileysHandler, is_configured as _bridge_ok
            if _bridge_ok() and self.bot.owner_whatsapp:
                res = BaileysHandler(self.bot).send_text(self.bot.owner_whatsapp, message)
                ok = ok or bool(res.get('success'))
        except Exception:
            logger.exception('[%s] handoff ya tovuti -> WhatsApp imeshindwa', self.bot.session_name)

        # 2) Email ya mmiliki — njia ya uhakika (bridge inaweza kuwa chini)
        try:
            if self._email_owner(message):
                ok = True
        except Exception:
            logger.exception('[%s] handoff ya tovuti -> email imeshindwa', self.bot.session_name)

        self.owner_notified = self.owner_notified or ok
        return {'success': ok, 'message_id': 'owner_notify'}

    def _email_owner(self, message):
        to = ''
        try:
            to = (self.bot.client.email or '').strip()
        except Exception:
            to = ''
        if not to:
            to = (getattr(settings, 'EMAIL_HOST_USER', '') or '').strip()
        if not to:
            return False

        from django.core.mail import send_mail
        body = _strip_md(message)
        # Njia hii inatumiwa na taarifa mbili tofauti: mteja anahitaji
        # binadamu, na bot imeacha kujibu. Kichwa kilikuwa cha kwanza tu.
        if 'imeacha kujibu' in (message or ''):
            subject = f"[JamiiTek] {self.bot.bot_name} imeacha kujibu wateja — {self.bot.business_name}"
        else:
            subject = f"[JamiiTek] Mteja wa tovuti anahitaji binadamu — {self.bot.business_name}"
        send_mail(
            subject, body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', to), [to],
            fail_silently=True,
        )
        return True


def _strip_md(text):
    """Ondoa alama za WhatsApp (*bold*, _italic_) kwa email/plaintext."""
    text = re.sub(r'\*(.*?)\*', r'\1', text or '', flags=re.S)
    text = re.sub(r'_(.*?)_', r'\1', text, flags=re.S)
    return text


# ══════════════════════════════════════════════════════════════
#  MSAADA
# ══════════════════════════════════════════════════════════════

def _raw_visitor(visitor):
    """
    Kitambulisho ghafi cha browser (kutoka localStorage). Kikiwa tupu au
    kibovu, tunazalisha kipya. Hiki ndicho tunachomrudishia browser
    ahifadhi — SI funguo ya database, ili kisiongezeke kila zunguko.
    """
    clean = re.sub(r'[^a-zA-Z0-9]', '', str(visitor or ''))
    if len(clean) < 6:
        clean = secrets.token_hex(8)   # herufi 16
    return clean[:32]


def _customer_key(raw):
    """
    Funguo ya database kwa kila browser. `Conversation.customer_phone` ina
    kikomo cha herufi 20, kwa hiyo tunafupisha na kuweka 'w' mbele ili
    isichanganyike na namba halisi za simu.

    LAZIMA iwe idempotent: `_customer_key(x)` ni ile ile kila mara kwa `x`
    ile ile. Ndiyo maana tunaipa kitambulisho GHAFI (`_raw_visitor`), si
    funguo iliyokwisha tengenezwa — vinginevyo 'w' ingeongezeka kila
    zunguko na kila ujumbe ungetengeneza mazungumzo mapya.
    """
    clean = re.sub(r'[^a-zA-Z0-9]', '', str(raw or '')) or secrets.token_hex(8)
    return ('w' + clean)[:20]


def _clean_greeting(text, name=''):
    """Weka jina; ondoa nafasi zilizobaki ('Karibu !' -> 'Karibu!')."""
    g = (text or '').replace('{name}', name or '')
    if not name:
        g = re.sub(r'\s+([!?.,])', r'\1', g)
        g = re.sub(r'\s{2,}', ' ', g)
    return g.strip()


def _owner_call_number(bot):
    """Namba ya mmiliki mtembeleaji anayoweza kuipigia. Tupu ikiwa haipo."""
    num = (bot.owner_whatsapp or '').strip()
    if not num:
        try:
            num = (bot.client.phone or '').strip()
        except Exception:
            num = ''
    return num


def _cors(response, request):
    origin = request.headers.get('Origin', '*')
    response['Access-Control-Allow-Origin'] = origin or '*'
    response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response['Access-Control-Allow-Headers'] = 'Content-Type'
    response['Access-Control-Max-Age'] = '86400'
    response['Vary'] = 'Origin'
    return response


# ══════════════════════════════════════════════════════════════
#  VIEW: POST ujumbe wa chat
# ══════════════════════════════════════════════════════════════

@csrf_exempt
def web_chat(request, bot_id):
    """
    Browser -> Django. Inakimbiza injini PAPO HAPO (si nyuma kama
    WhatsApp) kwa sababu browser inasubiri jibu kwenye response ile ile.
    """
    if request.method == 'OPTIONS':
        return _cors(HttpResponse(status=204), request)

    if request.method != 'POST':
        return _cors(JsonResponse({'error': 'POST pekee'}, status=405), request)

    try:
        bot = BotConfig.objects.select_related('client').get(id=bot_id)
    except (BotConfig.DoesNotExist, ValueError, Exception):
        return _cors(JsonResponse({'error': 'Bot haipo'}, status=404), request)

    if not bot.is_active or bot.status != 'active':
        return _cors(JsonResponse({
            'replies': ['Samahani, huduma hii haipatikani kwa sasa.'],
            'handoff': False,
        }), request)

    try:
        data = json.loads(request.body or '{}')
    except (json.JSONDecodeError, ValueError):
        return _cors(JsonResponse({'error': 'JSON si sahihi'}, status=400), request)

    text = (data.get('message') or '').strip()[:2000]
    raw = _raw_visitor(data.get('visitor') or '')

    # Kikomo kwa IP: mgeni anaweza kubadilisha `visitor` kila ombi, kwa hiyo
    # kikomo cha kila mteja peke yake hakitoshi kuzuia mafuriko ya AI.
    from apps.turnstile import get_client_ip
    from .ratelimit import _hit
    ip = get_client_ip(request) or 'unknown'
    ok_m, _ = _hit(f'chat:web:ip:m:{bot.id}:{ip}', 20, 60)
    ok_h, _ = _hit(f'chat:web:ip:h:{ip}', 300, 3600)
    if not (ok_m and ok_h):
        return _cors(JsonResponse({
            'replies': ['Umetuma jumbe nyingi kwa muda mfupi. Tafadhali subiri kidogo.'],
            'handoff': False,
        }, status=429), request)
    contact_name = (data.get('name') or '').strip()[:60]

    customer_key = _customer_key(raw)

    if not text:
        # Kufungua dirisha. Salamu inatoka HAPA (server) mara MOJA tu, si
        # kwenye browser — vinginevyo ingeonekana mara mbili: browser
        # ingeionyesha, kisha injini ingeirudia kwenye ujumbe wa kwanza.
        conv, is_new = Conversation.objects.get_or_create(
            bot=bot, customer_phone=customer_key,
            defaults={'wa_contact_name': contact_name,
                      'customer_name':   contact_name,
                      'metadata':        {'state': 'greeting'}},
        )
        greeting = _clean_greeting(bot.greeting_msg or 'Karibu! Nitakusaidiaje leo?', contact_name)
        replies = [greeting]

        if is_new:
            Message.objects.create(conversation=conv, role='assistant', content=greeting)
            meta = conv.metadata or {}
            if bot.collect_name and not conv.customer_name:
                ask = "Kwa njia, nikuite nani? 😊"
                replies.append(ask)
                Message.objects.create(conversation=conv, role='assistant', content=ask)
                meta['state'] = 'collect_name'
            elif bot.collect_phone and not meta.get('phone_collected'):
                ask = "Tafadhali nipe namba yako ya simu ili tuweze kuwasiliana nawe. 📱"
                replies.append(ask)
                Message.objects.create(conversation=conv, role='assistant', content=ask)
                meta['state'] = 'collect_phone'
            else:
                meta['state'] = 'chat'
            conv.metadata = meta
            conv.save(update_fields=['metadata'])
        else:
            # Mgeni anarudi. Anaona salamu tu — swali la jina au namba
            # halionyeshwi tena. Kama tungeacha hali ya 'collect_name',
            # ujumbe wake wa kwanza ungechukuliwa kama jina (ndivyo
            # "Unafanyaje kazi" ilivyokuwa jina). Tunarudi kwenye mazungumzo.
            meta = conv.metadata or {}
            if meta.get('state') in ('collect_name', 'collect_phone', 'greeting'):
                meta['state'] = 'chat'
                conv.metadata = meta
                conv.save(update_fields=['metadata'])

        return _cors(JsonResponse({
            'replies': replies,
            'visitor': raw,
            'bot_name': bot.bot_name,
            'business_name': bot.business_name,
            'handoff': False,
        }), request)

    handler = WebHandler(bot, customer_key)

    msg_data = {
        'from':          customer_key,
        'text':          text,
        'message_id':    f'web_{timezone.now().timestamp()}_{secrets.token_hex(3)}',
        'contact_name':  contact_name,
        'msg_type':      'text',
        'jid':           '',
        'is_lid':        False,
        'channel':       'web',
    }

    from .views import _process_message

    try:
        _process_message(bot, msg_data, handler=handler)
    except Exception:
        logger.exception('[%s] web_chat: kushughulikia ujumbe kumeshindwa', bot.session_name)
        return _cors(JsonResponse({
            'replies': ['Samahani, kumetokea hitilafu. Tafadhali jaribu tena.'],
            'visitor': customer_key,
            'handoff': False,
        }), request)

    conv = Conversation.objects.filter(bot=bot, customer_phone=customer_key).first()
    in_handoff = bool(conv and conv.is_human_handoff)

    replies = list(handler.replies)
    call_number = ''

    # Bot imesimama (trial imeisha, haijalipiwa). Kwenye WhatsApp tunanyamaza
    # kwa sababu mmiliki anaona ujumbe kwenye simu yake. Kwenye tovuti
    # hakuna anayeuona — ukimya ungeonekana kama site imeharibika.
    if getattr(handler, 'paused', False) and not replies:
        call_number = _owner_call_number(bot)
        if call_number:
            replies.append(f"Asante kwa ujumbe wako! Kwa msaada wa haraka, wasiliana nasi moja kwa moja: 📞 {call_number}")
        else:
            replies.append("Asante kwa ujumbe wako! Tafadhali jaribu tena baadaye kidogo.")

    if in_handoff:
        call_number = _owner_call_number(bot)
        # Kwenye tovuti, ukimya (kama WhatsApp) unaonekana kama bot
        # imeharibika. Kwa hiyo tunampa mtembeleaji jibu la wazi kila
        # wakati akiwa kwenye hali ya handoff.
        if not replies:
            replies.append(
                "Uko kwenye foleni ya kuhudumiwa na mtu wa timu yetu. "
                "Tafadhali subiri kidogo."
            )
        if call_number:
            replies.append(f"📞 Unaweza pia kumpigia mmiliki moja kwa moja: {call_number}")

    return _cors(JsonResponse({
        'replies':  replies,
        'visitor':  raw,
        'handoff':  in_handoff,
        'call_number': call_number,
        'bot_name': bot.bot_name,
        'business_name': bot.business_name,
    }), request)


# ══════════════════════════════════════════════════════════════
#  VIEW: script ya widget (JS)
# ══════════════════════════════════════════════════════════════

def web_widget_js(request, bot_id):
    """
    Inarudisha JavaScript inayotengeneza kitufe kinachoelea + dirisha la
    chat kwenye tovuti ya mteja. `bot_id` na `origin` zimewekwa ndani
    wakati wa kutuma, na UI yote iko ndani ya Shadow DOM ili CSS ya
    tovuti ya mteja isiharibu mwonekano (na kinyume chake).
    """
    try:
        bot = BotConfig.objects.get(id=bot_id)
    except (BotConfig.DoesNotExist, ValueError, Exception):
        return HttpResponse('/* JamiiBot: bot haipo */',
                            content_type='application/javascript', status=404)

    origin = request.build_absolute_uri('/').rstrip('/')
    cfg = {
        'botId':        str(bot.id),
        'origin':       origin,
        'endpoint':     f'{origin}/chatbot/web/{bot.id}/',
        'botName':      bot.bot_name or 'JamiiBot',
        'businessName': bot.business_name or '',
        'greeting':     _clean_greeting(bot.greeting_msg or 'Karibu! Nitakusaidiaje leo?'),
        'logo':         f'{origin}/static/img/jamiibot-icon.png',
        'brandUrl':     f'{origin}/bot/',
    }

    js = _WIDGET_JS.replace('__CONFIG__', json.dumps(cfg))
    resp = HttpResponse(js, content_type='application/javascript; charset=utf-8')
    resp['Cache-Control'] = 'public, max-age=300'
    resp['Access-Control-Allow-Origin'] = '*'
    return resp


# JavaScript ya widget. `__CONFIG__` inabadilishwa na JSON halisi.
# Kila kitu kiko ndani ya IIFE + Shadow DOM — hakuna kinachovuja kwenda
# tovuti ya mteja.
_WIDGET_JS = r"""
(function () {
  if (window.__jamiiBotLoaded) return;
  window.__jamiiBotLoaded = true;

  var CFG = __CONFIG__;
  var LS_KEY = 'jt_wc_' + CFG.botId;

  function getVisitor() {
    try { return localStorage.getItem(LS_KEY) || ''; } catch (e) { return ''; }
  }
  function setVisitor(v) {
    try { if (v) localStorage.setItem(LS_KEY, v); } catch (e) {}
  }

  // ── Shadow host ────────────────────────────────────────────
  var host = document.createElement('div');
  host.id = 'jamiibot-widget';
  host.style.all = 'initial';
  document.body.appendChild(host);
  var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;

  var style = document.createElement('style');
  style.textContent = CSS();
  root.appendChild(style);

  var wrap = document.createElement('div');
  wrap.className = 'jt-wrap';
  wrap.innerHTML = HTML();
  root.appendChild(wrap);

  // ── Vipengele ──────────────────────────────────────────────
  var launcher = root.querySelector('.jt-launcher');
  var panel    = root.querySelector('.jt-panel');
  var closeBtn = root.querySelector('.jt-close');
  var body     = root.querySelector('.jt-body');
  var form     = root.querySelector('.jt-form');
  var input    = root.querySelector('.jt-input');
  var sendBtn  = root.querySelector('.jt-send');
  var badge    = root.querySelector('.jt-badge');

  var opened = false, inited = false, busy = false, unread = 0;
  var vv = window.visualViewport;

  launcher.addEventListener('click', function () { toggle(true); });
  closeBtn.addEventListener('click', function () { toggle(false); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var t = (input.value || '').trim();
    if (!t || busy) return;
    input.value = '';
    autoGrow();
    addBubble(t, 'out');
    send(t);
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  });
  input.addEventListener('input', autoGrow);
  input.addEventListener('focus', function(){ setTimeout(scroll, 300); });

  // ── Keyboard-aware sizing ──────────────────────────────────
  // Simu ikifungua keyboard, `visualViewport` inapungua. Tunaweka
  // urefu wa dirisha uwe sawa na sehemu inayoonekana, ili input
  // ibaki juu ya keyboard na maandishi yasijifiche.
  function isMobile(){ return window.innerWidth <= 480; }
  function fit(){
    if (!panel.classList.contains('open')) return;
    if (isMobile() && vv){
      panel.style.height = Math.round(vv.height) + 'px';
      panel.style.top    = Math.round(vv.offsetTop) + 'px';
      panel.style.bottom = 'auto';
      scroll();
    } else {
      panel.style.height = ''; panel.style.top = ''; panel.style.bottom = '';
    }
  }
  if (vv){ vv.addEventListener('resize', fit); vv.addEventListener('scroll', fit); }
  window.addEventListener('resize', fit);
  window.addEventListener('orientationchange', function(){ setTimeout(fit, 250); });

  function toggle(show) {
    opened = show;
    panel.classList.toggle('open', show);
    launcher.classList.toggle('hidden', show);
    if (isMobile()) document.documentElement.style.overflow = show ? 'hidden' : '';
    fit();
    if (show) {
      unread = 0; badge.style.display = 'none';
      if (!inited) { inited = true; initChat(); }
      setTimeout(function () { input.focus(); }, 300);
    }
  }

  // ── Kufungua: salamu inatoka server MARA MOJA ──────────────
  function initChat() {
    var typing = showTyping();
    fetch(CFG.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visitor: getVisitor() })
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      typing.remove();
      if (d.visitor) setVisitor(d.visitor);
      renderSequential(d.replies || [CFG.greeting], 0);
    })
    .catch(function () {
      typing.remove();
      if (CFG.greeting) addBubble(CFG.greeting, 'in');
    });
  }

  // ── Mawasiliano na server ──────────────────────────────────
  function send(text) {
    busy = true; sendBtn.disabled = true;
    var typing = showTyping();
    fetch(CFG.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, visitor: getVisitor() })
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      typing.remove();
      if (d.visitor) setVisitor(d.visitor);
      var reps = d.replies || [];
      renderSequential(reps, 0, function () {
        if (d.handoff && d.call_number) addCall(d.call_number);
      });
    })
    .catch(function () {
      typing.remove();
      addBubble('Samahani, mtandao umekwama. Tafadhali jaribu tena.', 'in');
    })
    .finally(function () {
      busy = false; sendBtn.disabled = false;
      if (opened) input.focus();
    });
  }

  // Tuma majibu moja baada ya jingine, kila moja na "typing" fupi —
  // inaonekana kama binadamu anaandika, kama WhatsApp.
  function renderSequential(list, i, done) {
    if (i >= list.length) { if (done) done(); return; }
    var t = showTyping();
    var delay = Math.min(900, 300 + list[i].length * 12);
    setTimeout(function () {
      t.remove();
      addBubble(list[i], 'in');
      renderSequential(list, i + 1, done);
    }, delay);
  }

  // ── UI helpers ─────────────────────────────────────────────
  function addBubble(text, dir) {
    var b = document.createElement('div');
    b.className = 'jt-msg ' + dir;
    // Picha ya bidhaa: "[[img:https://...]]\nmaelezo" (WebHandler.send_image)
    var img = '', m = /^\[\[img:(https:\/\/[^\]\s"'<>]+)\]\]\n?/.exec(text);
    if (m) { img = '<img class="jt-pic" src="' + esc(m[1]) + '" alt="" loading="lazy">'; text = text.slice(m[0].length); }
    b.innerHTML = '<div class="jt-bubble">' + img + fmt(text) + '<span class="jt-time">' + now() + '</span></div>';
    body.appendChild(b);
    scroll();
    if (dir === 'in' && !opened) {
      unread++; badge.textContent = unread; badge.style.display = 'flex';
    }
  }

  function addCall(number) {
    var tel = number.replace(/[^\d+]/g, '');
    var b = document.createElement('div');
    b.className = 'jt-msg in';
    b.innerHTML = '<a class="jt-callbtn" href="tel:' + tel + '">📞 Piga simu ' + esc(number) + '</a>';
    body.appendChild(b);
    scroll();
  }

  function showTyping() {
    var t = document.createElement('div');
    t.className = 'jt-msg in';
    t.innerHTML = '<div class="jt-bubble jt-typing"><span></span><span></span><span></span></div>';
    body.appendChild(t); scroll();
    return t;
  }

  function fmt(text) {
    // *bold* na _italic_ za WhatsApp + linebreaks + links salama
    var s = esc(text);
    s = s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');   // **x** (kinga)
    s = s.replace(/\*(.+?)\*/g, '<b>$1</b>');
    s = s.replace(/_(.+?)_/g, '<i>$1</i>');
    s = s.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/\n/g, '<br>');
    return s;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function now() {
    var d = new Date();
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  function scroll() { body.scrollTop = body.scrollHeight; }
  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(96, input.scrollHeight) + 'px';
  }

  // ── HTML + CSS ─────────────────────────────────────────────
  function HTML() {
    var sub = CFG.businessName ? CFG.businessName : 'Mtandaoni';
    return ''
      + '<button class="jt-launcher" aria-label="Fungua chat">'
      +   '<img class="jt-logo" src="' + esc(CFG.logo) + '" alt="' + esc(CFG.botName) + '">'
      +   '<span class="jt-badge"></span>'
      + '</button>'
      + '<div class="jt-panel" role="dialog" aria-label="Chat">'
      +   '<div class="jt-head">'
      +     '<div class="jt-avatar"><img class="jt-logo" src="' + esc(CFG.logo) + '" alt=""></div>'
      +     '<div class="jt-head-txt">'
      +       '<div class="jt-title">' + esc(CFG.botName) + '</div>'
      +       '<div class="jt-status"><span class="jt-dot"></span>' + esc(sub) + '</div>'
      +     '</div>'
      +     '<button class="jt-close" aria-label="Funga">&#10005;</button>'
      +   '</div>'
      +   '<div class="jt-body"></div>'
      +   '<form class="jt-form">'
      +     '<textarea class="jt-input" rows="1" placeholder="Andika ujumbe..."></textarea>'
      +     '<button type="submit" class="jt-send" aria-label="Tuma">' + ICON_SEND() + '</button>'
      +   '</form>'
      +   '<a class="jt-brand" href="' + esc(CFG.brandUrl) + '" target="_blank" rel="noopener">Inaendeshwa na <b>JamiiBot</b></a>'
      + '</div>';
  }

  function ICON_SEND() {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg>';
  }

  function CSS() {
    return ''
    + '*{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}'
    + '.jt-wrap{position:fixed;bottom:20px;right:20px;z-index:2147483000}'
    // launcher
    + '.jt-launcher{position:fixed;bottom:20px;right:20px;width:62px;height:62px;border:none;border-radius:50%;'
    +   'background:#fff;color:#fff;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.4);padding:0;overflow:hidden;'
    +   'display:flex;align-items:center;justify-content:center;transition:transform .18s,box-shadow .18s;animation:jt-pop .4s ease}'
    + '.jt-launcher:hover{transform:scale(1.08);box-shadow:0 8px 26px rgba(0,0,0,.5)}'
    + '.jt-launcher:active{transform:scale(.94)}'
    + '.jt-launcher.hidden{display:none}'
    + '.jt-logo{width:100%;height:100%;object-fit:cover;display:block}'
    + '.jt-badge{position:absolute;top:-2px;right:-2px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;'
    +   'background:#ff3b30;color:#fff;font-size:12px;font-weight:700;display:none;align-items:center;justify-content:center}'
    // panel — WhatsApp DARK, flexible column
    + '.jt-panel{position:fixed;bottom:20px;right:20px;width:380px;max-width:calc(100vw - 32px);'
    +   'height:620px;max-height:calc(100vh - 40px);max-height:calc(100dvh - 40px);'
    +   'background:#0B141A;border-radius:16px;overflow:hidden;display:flex;flex-direction:column;'
    +   'box-shadow:0 12px 44px rgba(0,0,0,.55);opacity:0;transform:translateY(24px) scale(.96);pointer-events:none;'
    +   'transition:opacity .22s,transform .22s;transform-origin:bottom right}'
    + '.jt-panel.open{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}'
    // header
    + '.jt-head{background:#202C33;color:#E9EDEF;padding:11px 14px;display:flex;align-items:center;gap:10px;flex:0 0 auto}'
    + '.jt-avatar{width:40px;height:40px;border-radius:50%;background:#fff;overflow:hidden;flex:0 0 auto}'
    + '.jt-head-txt{flex:1;min-width:0}'
    + '.jt-title{font-weight:600;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
    + '.jt-status{font-size:12px;color:#8696A0;display:flex;align-items:center;gap:5px}'
    + '.jt-dot{width:8px;height:8px;border-radius:50%;background:#00A884;display:inline-block}'
    + '.jt-close{background:none;border:none;color:#AEBAC1;font-size:17px;cursor:pointer;padding:6px;border-radius:8px}'
    + '.jt-close:hover{color:#E9EDEF;background:rgba(255,255,255,.08)}'
    // body — dark
    + '.jt-body{flex:1 1 auto;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:14px 12px;'
    +   'display:flex;flex-direction:column;gap:7px;background:#0B141A;'
    +   'background-image:radial-gradient(rgba(255,255,255,.02) 1px,transparent 1px);background-size:26px 26px}'
    + '.jt-msg{display:flex;max-width:82%}'
    + '.jt-msg.in{align-self:flex-start}'
    + '.jt-msg.out{align-self:flex-end}'
    + '.jt-pic{display:block;width:100%;max-width:240px;border-radius:6px;margin:-2px 0 6px;background:#111B21}'
    + '.jt-bubble{position:relative;padding:7px 10px 18px;border-radius:9px;font-size:14.5px;line-height:1.42;color:#E9EDEF;'
    +   'box-shadow:0 1px 1px rgba(0,0,0,.25);word-wrap:break-word;overflow-wrap:anywhere;white-space:pre-wrap;animation:jt-in .18s ease}'
    + '.jt-msg.in .jt-bubble{background:#202C33;border-top-left-radius:2px}'
    + '.jt-msg.out .jt-bubble{background:#005C4B;border-top-right-radius:2px}'
    + '.jt-bubble a{color:#53BDEB}'
    + '.jt-time{position:absolute;right:8px;bottom:4px;font-size:10.5px;color:#8696A0}'
    // typing
    + '.jt-typing{padding:12px 14px;display:flex;gap:4px;align-items:center}'
    + '.jt-typing span{width:7px;height:7px;border-radius:50%;background:#8696A0;display:inline-block;animation:jt-blink 1.2s infinite}'
    + '.jt-typing span:nth-child(2){animation-delay:.2s}.jt-typing span:nth-child(3){animation-delay:.4s}'
    // call button
    + '.jt-callbtn{display:inline-flex;align-items:center;gap:8px;background:#00A884;color:#04120E;text-decoration:none;'
    +   'padding:11px 16px;border-radius:24px;font-weight:700;font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,.35)}'
    + '.jt-callbtn:active{transform:scale(.96)}'
    // form
    + '.jt-form{display:flex;align-items:flex-end;gap:8px;padding:9px 10px;background:#1F2C34;flex:0 0 auto}'
    + '.jt-input{flex:1;resize:none;border:none;outline:none;background:#2A3942;color:#E9EDEF;border-radius:22px;'
    +   'padding:11px 16px;font-size:14.5px;max-height:96px;line-height:1.4}'
    + '.jt-input::placeholder{color:#8696A0}'
    + '.jt-send{width:46px;height:46px;flex:0 0 auto;border:none;border-radius:50%;background:#00A884;color:#04120E;'
    +   'cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform .15s,background .15s}'
    + '.jt-send:hover{background:#06cf9c}.jt-send:active{transform:scale(.9)}'
    + '.jt-send:disabled{opacity:.5;cursor:default}'
    + '.jt-brand{display:block;text-align:center;font-size:11px;color:#667781;padding:6px;background:#111B21;'
    +   'text-decoration:none;cursor:pointer;transition:color .15s;flex:0 0 auto}'
    + '.jt-brand:hover{color:#E9EDEF}'
    + '.jt-brand b{color:#00A884}'
    // animations
    + '@keyframes jt-pop{from{transform:scale(0)}to{transform:scale(1)}}'
    + '@keyframes jt-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}'
    + '@keyframes jt-blink{0%,60%,100%{opacity:.3}30%{opacity:1}}'
    // mobile: full screen, keyboard-flexible (JS sets exact height via visualViewport)
    + '@media(max-width:480px){.jt-panel{width:100vw;max-width:100vw;left:0;right:0;top:0;bottom:0;'
    +   'height:100vh;height:100dvh;max-height:none;border-radius:0}'
    +   '.jt-launcher{bottom:16px;right:16px}}';
  }
})();
"""
