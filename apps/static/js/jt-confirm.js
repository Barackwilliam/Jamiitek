/* ═══════════════════════════════════════════════════════════════
   Mteja anathibitisha kupokea risiti — mara moja tu.

   Njia kuu: kidole / Face ID / PIN ya simu (WebAuthn).
     1. POST …/confirm/options/  → server inatoa challenge
     2. navigator.credentials.create() → simu inamwomba mteja afungue
     3. POST …/confirm/device/   → server inahakiki na kuandika
   Alama ya kidole haitoki kwenye simu kamwe.

   Njia mbadala: kuchora sahihi au kuandika jina → …/confirm/sign/

   Ikifaulu: kadi inageuka "Confirmed", na PDF inashuka yenyewe.
   ═══════════════════════════════════════════════════════════════ */
(function(){
'use strict';
var box = document.getElementById('confirm');
if (!box) return;

var base = box.getAttribute('data-base');              // /receipt/<token>/confirm/
var csrf = box.getAttribute('data-csrf');
var bioBtn = document.getElementById('cfBio');
var bioWrap = document.getElementById('cfBioWrap');
var alt = document.getElementById('cfAlt');
var altToggle = document.getElementById('cfAltToggle');
var noBio = document.getElementById('cfNoBio');
var err = document.getElementById('cfErr');
var dl = document.querySelector('a.dl');
var sheet = document.getElementById('cfSheet');
var bar = document.getElementById('cfBar');
var confirmed = false, opener = null;

/* ── base64url <-> ArrayBuffer ── */
function b64uToBuf(s){
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  var bin = atob(s), out = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}
function bufToB64u(buf){
  var bytes = new Uint8Array(buf), bin = '';
  for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function post(url, body, json){
  var headers = {'X-CSRFToken': csrf};
  if (json) headers['Content-Type'] = 'application/json';
  return fetch(url, {method: 'POST', credentials: 'same-origin', headers: headers, body: body})
    .then(function(r){
      return r.json().catch(function(){ return {ok: false, message: 'Something went wrong. Please try again.'}; })
        .then(function(data){ data.status = r.status; return data; });
    });
}

function showError(msg){
  err.textContent = msg || '';
  err.hidden = !msg;
}

function busy(btn, on, text){
  if (!btn) return;
  btn.disabled = on;
  btn.setAttribute('data-state', on ? 'busy' : 'idle');
  var label = btn.querySelector('[data-label]');
  if (label) {
    if (!label.getAttribute('data-idle')) label.setAttribute('data-idle', label.textContent);
    label.textContent = on ? text : label.getAttribute('data-idle');
  }
}

/* ── Imefaulu: alama ya tiki, funga paneli, fungua kupakua, pakua ── */
function success(data){
  box.classList.remove('is-scanning');
  box.classList.add('is-done');
  confirmed = true;
  var when = document.getElementById('cfWhen');
  if (when) when.textContent = data.when;
  var how = document.getElementById('cfHow');
  if (how) how.textContent = data.label;
  var sig = document.getElementById('sigState');
  if (sig) sig.innerHTML = '<span class="sig yes">' + data.label + '</span><small>' + data.when + '</small>';

  [].forEach.call(document.querySelectorAll('[data-needs-confirm]'), function(el){ el.removeAttribute('data-needs-confirm'); });
  if (bar) bar.classList.remove('is-on');
  document.body.classList.remove('has-cfbar');

  if (dl && data.pdf_url) {
    dl.href = data.pdf_url;
    dl.setAttribute('data-download', data.filename || 'receipt.pdf');
    var lbl = dl.querySelector('[data-label]');
    if (lbl) lbl.textContent = 'Download receipt';
    if (window.JTDownload) window.JTDownload.bind(dl);
  }
  /* Mteja aone tiki kwanza, kisha paneli ishuke na PDF ianze */
  setTimeout(function(){
    closeSheet();
    if (dl && data.pdf_url) setTimeout(function(){ dl.click(); }, 380);
  }, 1500);
}

function handle(data){
  if (data.ok) { success(data); return true; }
  if (data.error === 'already') { location.reload(); return true; }
  showError(data.message);
  return false;
}

/* ── 1. Kidole / Face ID ── */
function confirmWithDevice(){
  showError('');
  busy(bioBtn, true, 'Waiting for your phone…');
  box.classList.add('is-scanning');
  post(base + 'options/', '', false).then(function(opts){
    if (opts.status && opts.status >= 400) { handle(opts); throw null; }
    var pk = {
      challenge: b64uToBuf(opts.challenge),
      rp: opts.rp,
      user: {id: b64uToBuf(opts.user.id), name: opts.user.name, displayName: opts.user.displayName},
      pubKeyCredParams: opts.pubKeyCredParams,
      timeout: opts.timeout,
      attestation: opts.attestation || 'none',
      authenticatorSelection: opts.authenticatorSelection,
      excludeCredentials: []
    };
    return navigator.credentials.create({publicKey: pk});
  }).then(function(cred){
    if (!cred) throw null;
    busy(bioBtn, true, 'Confirming…');
    var r = cred.response;
    var payload = {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64u(r.clientDataJSON),
        attestationObject: bufToB64u(r.attestationObject),
        transports: r.getTransports ? r.getTransports() : []
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      authenticatorAttachment: cred.authenticatorAttachment || 'platform'
    };
    return post(base + 'device/', JSON.stringify(payload), true);
  }).then(function(data){
    box.classList.remove('is-scanning');
    if (data) handle(data);
    busy(bioBtn, false);
  }).catch(function(e){
    box.classList.remove('is-scanning');
    busy(bioBtn, false);
    if (e === null) return;
    /* Mteja alighairi, au simu haikuruhusu */
    if (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) {
      showError('Cancelled. Tap the button to try again — or sign instead.');
    } else {
      showError('Your phone could not confirm here. Please sign instead.');
      openAlt();
    }
  });
}

/* ── 2. Sahihi / jina ── */
function openAlt(){
  alt.hidden = false;
  if (altToggle) altToggle.setAttribute('aria-expanded', 'true');
  sizePad();
}

var pad = document.getElementById('cfPad'), ctx = pad && pad.getContext('2d');
var drawn = false, drawing = false, last = null, mode = 'draw';
var typed = document.getElementById('cfName'), agree = document.getElementById('cfAgree');
var signBtn = document.getElementById('cfSign');

function sizePad(){
  if (!pad || alt.hidden) return;
  var ratio = window.devicePixelRatio || 1, rect = pad.getBoundingClientRect();
  var snap = drawn ? pad.toDataURL() : null;
  pad.width = Math.round(rect.width * ratio);
  pad.height = Math.round(rect.height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.lineWidth = 2.4; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#0B1730';
  if (snap) { var img = new Image(); img.onload = function(){ ctx.drawImage(img, 0, 0, rect.width, rect.height); }; img.src = snap; }
}
function pos(e){ var r = pad.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; }
function ready(){
  var has = mode === 'draw' ? drawn : (typed.value.trim().length > 1);
  signBtn.disabled = !(has && agree.checked);
}
if (pad) {
  pad.addEventListener('pointerdown', function(e){
    drawing = true; drawn = true; pad.setPointerCapture(e.pointerId); last = pos(e);
    ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(last.x + .1, last.y); ctx.stroke(); ready();
  });
  pad.addEventListener('pointermove', function(e){
    if (!drawing) return; var p = pos(e);
    ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke(); last = p;
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(function(ev){ pad.addEventListener(ev, function(){ drawing = false; }); });
  document.getElementById('cfClear').addEventListener('click', function(){ ctx.clearRect(0, 0, pad.width, pad.height); drawn = false; ready(); });
  addEventListener('resize', sizePad);
  [].forEach.call(box.querySelectorAll('.cf-tab'), function(t){
    t.addEventListener('click', function(){
      [].forEach.call(box.querySelectorAll('.cf-tab'), function(x){ x.classList.toggle('on', x === t); x.setAttribute('aria-selected', x === t ? 'true' : 'false'); });
      mode = t.getAttribute('data-mode');
      document.getElementById('cfDraw').hidden = mode !== 'draw';
      document.getElementById('cfType').hidden = mode !== 'type';
      if (mode === 'draw') sizePad(); ready();
    });
  });
  typed.addEventListener('input', ready);
  agree.addEventListener('change', ready);
  signBtn.addEventListener('click', function(){
    showError('');
    var fd = new FormData();
    if (mode === 'draw') fd.append('signature_data', pad.toDataURL('image/png'));
    else fd.append('signature_name', typed.value.trim());
    busy(signBtn, true, 'Saving…');
    post(base + 'sign/', fd, false).then(function(data){ handle(data); busy(signBtn, false); });
  });
}
if (altToggle) altToggle.addEventListener('click', function(){ alt.hidden ? openAlt() : (alt.hidden = true, altToggle.setAttribute('aria-expanded', 'false')); });

/* ── Je simu hii inaweza kuthibitisha kwa kidole? ── */
function noDevice(){
  bioWrap.hidden = true;
  noBio.hidden = false;
  if (altToggle) altToggle.hidden = true;
  openAlt();
}
if (!window.PublicKeyCredential || !navigator.credentials || !window.isSecureContext) {
  noDevice();
} else if (PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable) {
  PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()
    .then(function(ok){ if (!ok) noDevice(); })
    .catch(function(){});
}
if (bioBtn) bioBtn.addEventListener('click', confirmWithDevice);

/* ── Paneli inayoelea ── */
function openSheet(){
  if (!sheet || confirmed) return;
  opener = document.activeElement;
  sheet.classList.add('is-open');
  sheet.setAttribute('aria-hidden', 'false');
  document.body.classList.add('sheet-open');
  if (bar) bar.classList.remove('is-on');
  setTimeout(function(){
    /* Lenga paneli yenyewe (si kitufe) — skrini ya simu isionyeshe pete ya focus */
    var panel = sheet.querySelector('.sheet__panel');
    if (panel) panel.focus({preventScroll: true});
    sizePad();
  }, 420);
}
function closeSheet(){
  if (!sheet) return;
  sheet.classList.remove('is-open');
  sheet.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('sheet-open');
  if (!confirmed && bar) {
    bar.classList.add('is-on');
    document.body.classList.add('has-cfbar');
  }
  if (opener && opener.focus) opener.focus({preventScroll: true});
}
[].forEach.call(document.querySelectorAll('[data-close]'), function(el){ el.addEventListener('click', closeSheet); });
[].forEach.call(document.querySelectorAll('[data-open-confirm]'), function(el){ el.addEventListener('click', openSheet); });
addEventListener('keydown', function(e){
  if (e.key === 'Escape' && sheet.classList.contains('is-open') && !box.classList.contains('is-done')) closeSheet();
  /* Tab ibaki ndani ya paneli ikiwa wazi */
  if (e.key === 'Tab' && sheet.classList.contains('is-open')) {
    var f = [].filter.call(sheet.querySelectorAll('button,a[href],input,canvas'), function(el){ return el.offsetParent !== null && !el.disabled; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

/* Kupakua au kuangalia kabla ya kuthibitisha → fungua paneli */
document.addEventListener('click', function(e){
  var el = e.target.closest && e.target.closest('[data-needs-confirm]');
  if (!el) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  openSheet();
  box.classList.remove('is-shake'); void box.offsetWidth; box.classList.add('is-shake');
}, true);

/* Fungua yenyewe ukurasa ukifunguka — mteja aone kinachohitajika mara moja */
setTimeout(openSheet, location.hash === '#confirm' ? 150 : 650);
})();
