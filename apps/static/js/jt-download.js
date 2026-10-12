/* ═══════════════════════════════════════════════════════════════
   Kupakua PDF ya risiti — haraka, na mtumiaji anaona kinachoendelea.

   <a href="…?pdf=1&v=…" data-download="RCP-2026-0008.pdf">

   1. Ukurasa ukishafunguka, PDF inaombwa kimya kimya nyuma (prefetch).
      Server inaitengeneza mara moja na kuitunza kwenye cache, kwa hiyo
      mtu akigusa kitufe, faili liko tayari — linashuka papo hapo.
   2. Akigusa kabla haijawa tayari, kitufe kinaonyesha "Preparing…"
      pamoja na mstari unaosogea, kisha "Downloaded".
   3. Kivinjari cha ndani ya app (WhatsApp, Facebook, Instagram) mara nyingi
      hakiwezi kuhifadhi blob — hapo tunafungua link yenyewe; server
      inaijibu kutoka cache, kwa hiyo bado ni haraka.
   Bila JS, ni link ya kawaida tu — bado inafanya kazi.
   ═══════════════════════════════════════════════════════════════ */
(function(){
'use strict';
var inApp = /; wv\)|FBAN|FBAV|Instagram|WhatsApp|Line\/|Snapchat|TikTok/i.test(navigator.userAgent);
var canBlob = !inApp && 'download' in document.createElement('a') && window.URL && URL.createObjectURL;
var idle = window.requestIdleCallback || function(f){ return setTimeout(f, 500); };

function bind(a){
  if (a.__jtdl) return;
  a.__jtdl = true;
  var url = a.href, name = a.getAttribute('data-download') || 'receipt.pdf', job = null, timer = null;
  var label = a.querySelector('[data-label]');
  var texts = {
    idle: label ? label.textContent : '',
    busy: a.getAttribute('data-busy') || 'Preparing your receipt…',
    done: a.getAttribute('data-done') || 'Downloaded',
    fail: a.getAttribute('data-fail') || 'Try again'
  };

  function warm(){
    if (job) return job;
    if (!window.fetch) return (job = Promise.resolve(null));
    job = fetch(url, {credentials: 'same-origin'}).then(function(r){
      var type = r.headers.get('content-type') || '';
      if (!r.ok || type.indexOf('pdf') < 0) throw new Error('not a pdf');
      return r.blob();
    }).catch(function(){ job = null; return null; });
    return job;
  }

  function state(s){
    a.setAttribute('data-state', s);
    a.setAttribute('aria-busy', s === 'busy' ? 'true' : 'false');
    if (label) label.textContent = texts[s];
  }

  function save(blob){
    if (blob && canBlob) {
      var href = URL.createObjectURL(blob), tmp = document.createElement('a');
      tmp.href = href; tmp.download = name; tmp.rel = 'noopener';
      document.body.appendChild(tmp); tmp.click(); tmp.remove();
      setTimeout(function(){ URL.revokeObjectURL(href); }, 30000);
    } else {
      window.location.href = url;          // server ina PDF kwenye cache tayari
    }
  }

  /* Andaa mapema, bila kuzuia ukurasa */
  if (window.fetch) idle(function(){ warm(); });

  a.addEventListener('click', function(e){
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;   // "fungua tab mpya" ibaki
    e.preventDefault();
    if (a.getAttribute('data-state') === 'busy') return;
    clearTimeout(timer);
    state('busy');
    var t0 = Date.now();
    warm().then(function(blob){
      /* Spinner ikae angalau kidogo — kubonyeza kuonekane kumepokelewa */
      setTimeout(function(){
        if (!blob && window.fetch && canBlob) {
          /* Prefetch ilishindwa (mtandao?) — jaribu link yenyewe */
          window.location.href = url;
        } else {
          save(blob);
        }
        state('done');
        timer = setTimeout(function(){ state('idle'); }, 3200);
      }, Math.max(0, 300 - (Date.now() - t0)));
    });
  });
}

[].forEach.call(document.querySelectorAll('a[data-download]'), bind);

/* Ukurasa wa uthibitisho unaitumia baada ya mteja kuthibitisha */
window.JTDownload = {bind: bind};
})();
