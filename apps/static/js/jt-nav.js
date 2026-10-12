/* ═══════════════════════════════════════════════════════════════
   JamiiTek — header + sidebar ya simu. FAILI MOJA kwa tovuti nzima
   (site/base.html, base.html, /bot/). Angalia static/css/jt-nav.css.
   Hakuna maktaba; kila kipande kikikosa kitu kwenye ukurasa kinanyamaza.
   ═══════════════════════════════════════════════════════════════ */
(function(){
'use strict';
function $(s, r){ return (r || document).querySelector(s); }
function $$(s, r){ return [].slice.call((r || document).querySelectorAll(s)); }

/* Logo ikikosekana, ifiche badala ya kuonyesha alama ya picha iliyovunjika */
$$('.hdr .brand img, .side .brand img').forEach(function(img){
  img.addEventListener('error', function(){ (img.closest('picture') || img).style.display = 'none'; });
});

/* ── Header: inajificha ukishuka, inarudi ukipanda; mstari wa maendeleo.
      `data-pin` (blog, templates) = header inabaki juu kila wakati. ── */
var hdr = $('#hdr');
if (hdr) {
  var pinned = hdr.hasAttribute('data-pin');
  var lastY = scrollY, ticking = false;
  function onScroll(){
    var y = scrollY, max = document.documentElement.scrollHeight - innerHeight;
    hdr.classList.toggle('is-stuck', y > 8);
    if (!pinned) {
      hdr.classList.toggle('is-hidden', y > 320 && y > lastY + 4 && !document.body.classList.contains('nav-open'));
      if (y < lastY - 4) hdr.classList.remove('is-hidden');
    }
    hdr.style.setProperty('--p', max > 0 ? Math.min(1, y / max) : 0);
    lastY = y; ticking = false;
  }
  addEventListener('scroll', function(){ if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, {passive:true});
  onScroll();

  /* Kidonge kinateleza kwenda link unayoielekea */
  var nav = $('.nav', hdr), pill = $('.nav__pill', hdr);
  if (nav && pill) {
    var on = $('a.is-on', nav);
    function moveTo(a){
      if (!a) { pill.style.opacity = 0; return; }
      pill.style.width = a.offsetWidth + 'px';
      pill.style.transform = 'translateX(' + a.offsetLeft + 'px)';
      pill.style.opacity = 1;
    }
    $$('a', nav).forEach(function(a){ a.addEventListener('mouseenter', function(){ moveTo(a); }); });
    nav.addEventListener('mouseleave', function(){ moveTo(on); });
    addEventListener('load', function(){ moveTo(on); });
    addEventListener('resize', function(){ moveTo(on); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function(){ moveTo(on); });
  }
}

/* ── Sidebar ya simu ── */
var side = $('#side'), burger = $('#burger'), scrim = $('#scrim'), closeBtn = $('#sideX');
if (side && burger) {
  /* Link za sehemu za ukurasa huu (data-spy): angazia unayoisoma sasa */
  function spy(){
    var links = $$('a[data-spy]', side), cur = null, best = -1e9;
    links.forEach(function(a){
      var t = document.querySelector(a.getAttribute('href'));
      if (!t) return;
      var top = t.getBoundingClientRect().top;
      if (top < innerHeight * .4 && top > best) { best = top; cur = a; }
    });
    links.forEach(function(a){ a.classList.toggle('is-on', a === cur); });
  }
  function setNav(open){
    if (open) spy();
    side.classList.toggle('is-open', open);
    if (scrim) scrim.classList.toggle('is-on', open);
    side.setAttribute('aria-hidden', open ? 'false' : 'true');
    burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.classList.toggle('nav-open', open);
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) { if (closeBtn) closeBtn.focus(); }
    else if (side.contains(document.activeElement)) burger.focus();
  }
  burger.setAttribute('aria-controls', 'side');
  burger.setAttribute('aria-expanded', 'false');
  burger.addEventListener('click', function(){ setNav(!side.classList.contains('is-open')); });
  if (closeBtn) closeBtn.addEventListener('click', function(){ setNav(false); });
  if (scrim) scrim.addEventListener('click', function(){ setNav(false); });
  side.addEventListener('click', function(e){ if (e.target.closest('a')) setNav(false); });
  addEventListener('keydown', function(e){ if (e.key === 'Escape' && side.classList.contains('is-open')) setNav(false); });
  /* Skrini ikipanuka hadi desktop, sidebar inafichwa na CSS — fungua scroll pia */
  addEventListener('resize', function(){ if (innerWidth >= 1100 && side.classList.contains('is-open')) setNav(false); });
}
})();
