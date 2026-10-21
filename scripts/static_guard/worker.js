/*
 * JamiiTek Status Guard — Cloudflare Worker (moja kwa static websites ZOTE za wateja).
 *
 * Kila ombi linapita hapa kabla ya kufika kwenye website (Render, GitHub Pages, hosting yoyote).
 * Worker inaiuliza JamiiTek hali ya domain hii; ikiwa imesimamishwa (hosting imeisha) au iko
 * kwenye matengenezo, mgeni anapata ukurasa wa JamiiTek kwa HTTP 503 — hakuna JavaScript
 * ya kuondoa, na Google inaelewa ni hali ya muda.
 *
 *  • Jibu la JamiiTek linahifadhiwa dakika 5 kwa kila domain (Cloudflare cache).
 *  • JamiiTek isipojibu ndani ya sekunde 3, website inaonekana kama kawaida (fail-open):
 *    kosa letu halipaswi kumzima mteja aliyelipa.
 *  • Domain isiyojulikana JamiiTek inaachwa ipite.
 *
 * Kuweka: scripts/static_guard/README.md
 */
const JAMIITEK = 'https://www.jamiitek.com';
const TTL = 300;          // sekunde
const TIMEOUT = 3000;     // ms

async function siteState(host, ctx) {
  const api = `${JAMIITEK}/api/site-guard/host/${encodeURIComponent(host)}/`;
  const cache = caches.default;
  const key = new Request(api);
  const hit = await cache.match(key);
  if (hit) return hit.json();

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT);
  try {
    const res = await fetch(api, { signal: ctrl.signal, headers: { 'User-Agent': 'JamiiTek-Guard-Worker' } });
    if (!res.ok) return null;
    const data = await res.json();
    if (typeof data.active !== 'boolean') return null;
    ctx.waitUntil(cache.put(key, new Response(JSON.stringify(data), {
      headers: { 'Content-Type': 'application/json', 'Cache-Control': `max-age=${TTL}` },
    })));
    return data;
  } catch (e) {
    return null;                      // fail-open
  } finally {
    clearTimeout(timer);
  }
}

export default {
  async fetch(request, env, ctx) {
    const host = new URL(request.url).hostname.replace(/^www\./, '');   // www na bila www: cache moja
    const state = await siteState(host, ctx);
    if (state && state.active === false && state.html) {
      return new Response(state.html, {
        status: 503,
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Retry-After': '3600',
          'Cache-Control': 'no-store',
          'X-JamiiTek-Guard': state.status || 'suspended',
        },
      });
    }
    return fetch(request);
  },
};
