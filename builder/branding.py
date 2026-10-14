"""
Alama ya "Developed by JamiiTek" chini ya kila website ya mteja.

TATIZO

Credit ilikuwa ndani ya footer. Mteja aliyeandika footer yake (Code/AI),
aliyepakia ZIP yenye HTML yake, au aliyeongeza CSS kama
`.badge{display:none}` aliiondoa kwa urahisi.

SULUHISHO

Alama haihifadhiwi popote kwenye data ya mteja. Server inaiongeza kwenye
kila jibu la HTML la website ya mteja, mwishoni kabisa (kabla ya </body>):
kurasa za builder, kurasa za ZIP (raw_document), collections n.k.
(SubdomainMiddleware inaita inject_badge), na preview ya Studio.

Kuizuia isifichwe:
  - style ya inline yenye !important kwenye kishikio — CSS ya mteja
    (hata yenye !important) haiwezi kuishinda
  - JavaScript inaichora ndani ya "closed shadow root": CSS ya ukurasa
    haiwezi kufikia link wala maandishi yake
  - MutationObserver: ikifutwa, ikifichwa kwa `hidden` au style yake
    ikibadilishwa, inarudishwa papo hapo
  - bila JavaScript, link ya kawaida (yenye inline styles) bado inaonekana

Link inafungua https://www.jamiitek.com kwenye tab mpya.
"""
import re

BADGE_URL = 'https://www.jamiitek.com'

# Mitindo ya kishikio: inline + !important = CSS ya ukurasa haiwezi kuificha
_HOST_STYLE = ';'.join(f'{k}:{v}!important' for k, v in (
    ('display', 'block'), ('visibility', 'visible'), ('opacity', '1'), ('position', 'relative'),
    ('z-index', '2147483000'), ('width', 'auto'), ('height', 'auto'), ('max-height', 'none'),
    ('min-height', '0'), ('margin', '0'), ('padding', '0'), ('border', '0'), ('overflow', 'visible'),
    ('clip', 'auto'), ('clip-path', 'none'), ('transform', 'none'), ('filter', 'none'),
    ('pointer-events', 'auto'), ('float', 'none'), ('left', 'auto'), ('top', 'auto'),
    ('background', '#07090d'), ('content-visibility', 'visible'),
    # Ukurasa ukiwa flex/grid (body{display:flex}), alama isiwe safu ya pembeni
    ('grid-column', '1 / -1'), ('order', '2147483647'),
    ('align-self', 'stretch'), ('clear', 'both'), ('box-sizing', 'border-box'),
))

# Link ya akiba kwa browser bila JavaScript
_LINK_STYLE = ';'.join(f'{k}:{v}!important' for k, v in (
    ('display', 'block'), ('visibility', 'visible'), ('opacity', '1'), ('padding', '14px 16px'),
    ('background', '#07090d'), ('color', '#c9d1dd'), ('font', "600 13px/1.4 -apple-system,'Segoe UI',Roboto,Arial,sans-serif"),
    ('text-align', 'center'), ('text-decoration', 'none'), ('letter-spacing', '.01em'),
))

# Muonekano ndani ya shadow root — ukurasa hauwezi kuugusa
_SHADOW_HTML = (
    '<style>'
    ':host{all:initial}'
    'a{display:flex;align-items:center;justify-content:center;gap:9px;padding:14px 16px;background:#07090d;'
    'border-top:1px solid rgba(255,255,255,.06);color:#8b95a7;font:500 13px/1.4 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;'
    'text-decoration:none;letter-spacing:.01em;transition:color .2s}'
    'a:hover{color:#fff}'
    'i{width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;'
    'background:linear-gradient(135deg,#00d4ff,#7c3aed);color:#fff;font:800 11px/1 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;'
    'font-style:normal;box-shadow:0 2px 8px rgba(124,58,237,.35)}'
    'b{color:#f4f6fa;font-weight:700}'
    '</style>'
    f'<a href="{BADGE_URL}" target="_blank" rel="noopener">Developed by <i>J</i><b>JamiiTek</b></a>'
)

_SCRIPT = """(function(){
var STYLE=%(style)s,HTML=%(html)s,b,root;
function build(){
  b=document.createElement('jamiitek-badge');b.setAttribute('style',STYLE);
  try{root=b.attachShadow({mode:'closed'});root.innerHTML=HTML;}
  catch(e){b.innerHTML=%(fallback)s;}
}
var onRoot=false;
function home(){return onRoot?document.documentElement:(document.querySelector('.jt-body')||document.body);}
// Template yenye body{display:flex} (au grid) iliifanya alama kuwa safu pembeni na
// kuibana website (simu: website ilibaki nusu ya skrini). Hapo alama inahamia chini
// ya <body> — ndani ya <html> — ambako inakaa chini ya ukurasa kwa upana wote.
function check(){
  if(onRoot||!b||!b.isConnected)return;
  var d=getComputedStyle(b.parentNode).display||'';
  if(/flex|grid/.test(d)){onRoot=true;fix();}
}
function fix(){
  if(!document.body)return;
  if(!b)build();
  var h=home();
  if(!b.isConnected||b.parentNode!==h)h.appendChild(b);
  if(b.getAttribute('style')!==STYLE)b.setAttribute('style',STYLE);
  if(b.hasAttribute('hidden'))b.removeAttribute('hidden');
}
function start(){
  document.querySelectorAll('jamiitek-badge').forEach(function(n){n.remove();});
  fix();check();
  window.addEventListener('load',check);
  new MutationObserver(fix).observe(document.documentElement,{childList:true,subtree:true,attributes:true,
    attributeFilter:['style','hidden','class']});
  setInterval(fix,2500);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();"""


def badge_html():
    import json
    link = (f'<a href="{BADGE_URL}" target="_blank" rel="noopener" style="{_LINK_STYLE}">'
            'Developed by <b style="color:#fff!important">JamiiTek</b></a>')
    script = _SCRIPT % {'style': json.dumps(_HOST_STYLE), 'html': json.dumps(_SHADOW_HTML),
                        'fallback': json.dumps(link)}
    # </script> ndani ya JSON haiwezekani hapa (maandishi ni yetu), lakini linda hata hivyo
    script = script.replace('</', '<\\/')
    return (f'<jamiitek-badge style="{_HOST_STYLE}">{link}</jamiitek-badge>'
            f'<script data-jt-badge>{script}</script>')


_BODY_END = re.compile(r'</body\s*>', re.IGNORECASE)


def inject_badge(html):
    """Weka alama kabla ya </body> ya mwisho (au mwishoni kama haipo)."""
    matches = list(_BODY_END.finditer(html))
    badge = badge_html()
    if not matches:
        return html + badge
    i = matches[-1].start()
    return html[:i] + badge + html[i:]


def add_badge_to_response(response, site=None):
    """Kwa middleware/views: ongeza alama kwenye jibu la HTML (200) tu.

    Website iliyolipiwa (premium — template iliyonunuliwa au "Remove JamiiTek
    logo", builder/billing.py) haipati alama.
    """
    if site is not None and getattr(site, 'is_premium', False):
        return response
    if getattr(response, 'streaming', False) or response.status_code != 200:
        return response
    if not response.get('Content-Type', '').startswith('text/html'):
        return response
    charset = getattr(response, 'charset', None) or 'utf-8'
    try:
        html = response.content.decode(charset)
    except UnicodeDecodeError:
        return response
    response.content = inject_badge(html).encode(charset)
    if response.has_header('Content-Length'):
        response['Content-Length'] = str(len(response.content))
    return response
