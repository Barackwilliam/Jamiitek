/* ═══════════════════════════════════════════════════════════════
   JamiiTek — JS ya pamoja ya Home, Services, About na Contact.
   Hakuna maktaba. Kila kipande kinajitegemea: kikikosa kitu kwenye
   ukurasa, kinanyamaza tu.
   ═══════════════════════════════════════════════════════════════ */
(function(){
'use strict';
var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
var IO = 'IntersectionObserver' in window;
function $(s, r){ return (r || document).querySelector(s); }
function $$(s, r){ return [].slice.call((r || document).querySelectorAll(s)); }
window.JT = {$:$, $$:$$, reduced:reduced, IO:IO};

/* Picha ikikosekana, ifiche badala ya kuonyesha alama ya picha iliyovunjika */
$$('img[data-hide-broken], .brand img').forEach(function(img){
  img.addEventListener('error', function(){ (img.closest('picture') || img).style.display = 'none'; });
});

/* Header na sidebar ya simu: static/js/jt-nav.js (moja kwa tovuti nzima) */

/* ── Kichwa (h1.split): maneno yanaingia moja moja ── */
$$('.split').forEach(function(h){
  if (reduced) return;
  var i = 0, label = h.textContent.replace(/\s+/g, ' ').trim();
  (function walk(node){
    [].slice.call(node.childNodes).forEach(function(n){
      if (n.nodeType === 3) {
        var frag = document.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach(function(part){
          if (!part) return;
          if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
          var s = document.createElement('span'); s.className = 'w'; s.setAttribute('aria-hidden', 'true');
          s.style.setProperty('--i', i++); s.textContent = part; frag.appendChild(s);
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1) walk(n);
    });
  })(h);
  h.setAttribute('aria-label', label);
});

/* ── Reveal + kuhesabu namba ── */
function countUp(el){
  var to = parseFloat(el.dataset.count), dec = +(el.dataset.dec || 0), suf = el.dataset.suffix || '', t0 = null;
  if (reduced || !to) { el.textContent = to.toFixed(dec) + suf; return; }
  requestAnimationFrame(function step(t){
    if (!t0) t0 = t;
    var p = Math.min((t - t0) / 1400, 1), v = to * (1 - Math.pow(1 - p, 3));
    el.textContent = (dec ? v.toFixed(dec) : Math.round(v).toLocaleString('en-US')) + suf;
    if (p < 1) requestAnimationFrame(step);
  });
}
var REV = '.rv, .kili, [data-count], .bars, .steps, .draw';
if (IO && !reduced) {
  var rv = new IntersectionObserver(function(en){
    en.forEach(function(e){
      if (!e.isIntersecting) return;
      e.target.classList.add('in');
      if (e.target.dataset.count) countUp(e.target);
      rv.unobserve(e.target);
    });
  }, {threshold:.15, rootMargin:'0px 0px -5% 0px'});
  $$(REV).forEach(function(el){ rv.observe(el); });
} else {
  $$(REV).forEach(function(el){ el.classList.add('in'); if (el.dataset.count) countUp(el); });
}

/* ── Michoro nje ya skrini inasimama ── */
if (IO) {
  var off = new IntersectionObserver(function(en){
    en.forEach(function(e){ e.target.classList.toggle('is-off', !e.isIntersecting); });
  });
  $$('[data-live]').forEach(function(el){ off.observe(el); });
}

/* ── Mwanga unaofuata kidole/kipanya kwenye kadi ── */
$$('[data-glow]').forEach(function(c){
  c.addEventListener('pointermove', function(e){
    var r = c.getBoundingClientRect();
    c.style.setProperty('--mx', (e.clientX - r.left) + 'px');
    c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  });
});

/* ── Mfuatano ([data-seq]): terminal, chat, builder, code editor ──
   Watoto wanaonekana mmoja mmoja, inasubiri, kisha inaanza upya —
   na inafanya kazi tu ikiwa kwenye skrini. */
function seq(root){
  var kids = root.dataset.seq === 'build' ? $$('.blk', root) : [].slice.call(root.children).filter(function(c){ return !c.hasAttribute('data-static'); }),
      step = +root.dataset.step || 800, hold = +root.dataset.hold || 3000,
      i = 0, timer = null, visible = false,
      cursor = $('.cursor', root), tag = root.dataset.tag ? document.getElementById(root.dataset.tag) : null;
  if (reduced) { kids.forEach(function(k){ if (!k.classList.contains('typing')) k.classList.add('on'); }); if (tag) tag.classList.add('on'); return; }
  function moveCursor(el){
    if (!cursor || !el) return;
    var pr = cursor.parentNode.getBoundingClientRect(), r = el.getBoundingClientRect();
    cursor.style.transform = 'translate(' + (r.left - pr.left + r.width * .7) + 'px,' + (r.top - pr.top + r.height * .55) + 'px)';
  }
  function tick(){
    if (!visible) { timer = null; return; }
    if (i < kids.length) {
      var el = kids[i];
      if (el.classList.contains('typing')) {
        el.classList.add('on');
        timer = setTimeout(function(){ el.classList.remove('on'); el.style.display = 'none'; i++; tick(); }, step);
        return;
      }
      el.classList.add('on'); moveCursor(el); i++;
      if (i === kids.length && tag) tag.classList.add('on');
      timer = setTimeout(tick, step);
    } else {
      timer = setTimeout(function(){
        kids.forEach(function(k){ k.classList.remove('on'); k.style.display = ''; });
        if (tag) tag.classList.remove('on');
        i = 0; timer = setTimeout(tick, 600);
      }, hold);
    }
  }
  if (IO) new IntersectionObserver(function(en){
    visible = en[0].isIntersecting;
    if (visible && !timer) timer = setTimeout(tick, 350);
  }, {threshold:.25}).observe(root);
  else { visible = true; tick(); }
}
$$('[data-seq]').forEach(seq);

/* ── Maandishi yanayojiandika ([data-type="a|b|c"]) ── */
$$('[data-type]').forEach(function(el){
  var words = el.dataset.type.split('|'), n = 0, c = 0, del = false;
  if (reduced) { el.textContent = words[0]; return; }
  (function tick(){
    var w = words[n % words.length];
    c += del ? -1 : 1; el.textContent = w.slice(0, c);
    if (!del && c === w.length) { del = true; return setTimeout(tick, 1800); }
    if (del && c === 0) { del = false; n++; }
    setTimeout(tick, del ? 40 : 85);
  })();
});

/* ── Carousel (scroll-snap) — inatumika na Home ── */
window.JT.carousel = function(trackId, prevId, nextId, barId){
  var track = document.getElementById(trackId);
  if (!track) return;
  var prev = document.getElementById(prevId), next = document.getElementById(nextId),
      bar = barId ? document.getElementById(barId) : null;
  function step(){
    var card = track.firstElementChild;
    return card ? card.getBoundingClientRect().width + (parseFloat(getComputedStyle(track).columnGap) || 20) : track.clientWidth * .8;
  }
  function sync(){
    var max = track.scrollWidth - track.clientWidth;
    if (prev) prev.disabled = track.scrollLeft < 8;
    if (next) next.disabled = track.scrollLeft > max - 8;
    if (bar) {
      var pct = max > 0 ? track.scrollLeft / max : 0,
          w = Math.max(18, Math.min(100, (track.clientWidth / track.scrollWidth) * 100));
      bar.style.width = w + '%';
      bar.style.transform = 'translateX(' + (pct * ((100 - w) / w) * 100) + '%)';
    }
  }
  if (prev) prev.addEventListener('click', function(){ track.scrollBy({left:-step(), behavior:'smooth'}); });
  if (next) next.addEventListener('click', function(){ track.scrollBy({left:step(), behavior:'smooth'}); });
  track.addEventListener('scroll', sync, {passive:true});
  addEventListener('resize', sync);
  var down = false, startX = 0, startL = 0, moved = 0;
  track.addEventListener('pointerdown', function(e){
    if (e.pointerType === 'touch') return;
    down = true; moved = 0; startX = e.clientX; startL = track.scrollLeft; track.classList.add('is-drag');
  });
  addEventListener('pointermove', function(e){
    if (!down) return;
    var dx = e.clientX - startX; moved = Math.abs(dx); track.scrollLeft = startL - dx;
  });
  addEventListener('pointerup', function(){ if (down) { down = false; track.classList.remove('is-drag'); } });
  track.addEventListener('click', function(e){ if (moved > 8) { e.preventDefault(); e.stopPropagation(); } }, true);
  sync();
};

/* ── Newsletter (footer): inatumwa bila kuacha ukurasa ── */
(function(){
  var f = $('#newsForm'), msg = $('#newsMsg');
  if (!f || !window.fetch || !window.FormData) return;
  f.addEventListener('submit', function(e){
    e.preventDefault();
    var btn = $('button', f), input = $('input[type=email]', f);
    function show(ok, text){ msg.textContent = text; msg.className = 'news__msg ' + (ok ? 'is-ok' : 'is-err'); }
    if (!input.checkValidity()) { show(false, 'Please enter a valid email address.'); input.focus(); return; }
    btn.disabled = true;
    fetch(f.action, {method:'POST', body:new FormData(f), headers:{'X-Requested-With':'XMLHttpRequest'}, credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){ show(d.ok, d.message); if (d.ok) f.reset(); })
      .catch(function(){ show(false, 'Connection problem. Please try again.'); })
      .then(function(){ btn.disabled = false; });
  });
})();

/* ── Scripts zisizo za lazima: baada ya ukurasa kufunguka ──
   Widget ya JamiiBot na interaction.js hazihitajiki kwa skrini ya kwanza. */
function later(){
  [].slice.call(document.querySelectorAll('script[type="text/later"]')).forEach(function(o){
    var s = document.createElement('script'); s.src = o.dataset.src; s.async = true; document.body.appendChild(s);
  });
}
addEventListener('load', function(){ ('requestIdleCallback' in window) ? requestIdleCallback(later, {timeout:2500}) : setTimeout(later, 1200); });
})();
