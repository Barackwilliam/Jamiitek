# Status Guard ya server kwa static websites (index.html)

Kama `jamiitek_middleware.py` ya Django: website ikisimamishwa kwenye `/manage/` (hosting imeisha,
au maintenance), mgeni anapata ukurasa wa **Service Suspended** kutoka kwenye server (HTTP 503),
si kwa JavaScript inayoweza kuondolewa. Jibu la JamiiTek linahifadhiwa dakika 5; JamiiTek
isipojibu, website inaonekana kama kawaida (fail-open).

Code ya JamiiTek: `apps/site_guard.py` · API: `/api/site-guard/<api_key>/` na `/api/site-guard/host/<domain>/`.

---

## A. Domain iko Cloudflare (pamoja na Render / GitHub Pages)

Worker **moja** inatumika kwa wateja wote — inatambua website kwa domain, hakuna API key ya kuweka.

1. Cloudflare → **Workers & Pages** → **Create** → **Worker** → jina `jamiitek-guard` → **Deploy**.
2. **Edit code** → futa kilichopo → bandika yote ya `worker.js` → **Deploy**.
3. Kwa kila website ya mteja: Worker `jamiitek-guard` → **Settings → Domains & Routes → Add → Route**:
   - `duka.co.tz/*` (zone: duka.co.tz)
   - `www.duka.co.tz/*`
4. Hakikisha DNS ya domain ina **wingu la chungwa (Proxied)** — bila hivyo ombi haliipiti Worker.

Masharti:
- Domain (zone) lazima iwe kwenye akaunti ya Cloudflare ya JamiiTek, ambapo Worker iko.
- URL ya website kwenye `/manage/` lazima iwe domain hiyo hiyo (mf. `https://duka.co.tz`).
- Mpango wa bure wa Workers una kikomo cha maombi kwa siku — angalia matumizi kwenye dashboard ya Cloudflare.

## B. cPanel / shared hosting (Apache + PHP)

1. `/manage/` → Websites → website ya mteja (aina **Static**) → **Integration** → **Download jamiitek-guard.php**
   (API ya website hiyo iko ndani tayari).
2. Pakia `jamiitek-guard.php` kwenye `public_html` (kando ya `index.html`).
3. Tengeneza `.htaccess` kwenye `public_html` na maandishi yaliyo kwenye kadi ya Integration
   (au ongeza juu ya `.htaccess` iliyopo).

Kurasa zote za `.html` (na `/`, `/about/`) zinapita `jamiitek-guard.php` kwanza. Picha, CSS na JS
hazipiti — zinatoka moja kwa moja.

## Kujaribu

1. `/manage/` → website → **Suspend**.
2. Fungua website ndani ya dakika 5 (au futa cache: Cloudflare → Caching → Purge, au subiri dakika 5)
   — ukurasa wa **Service Suspended** unaonekana, hata JavaScript ikiwa imezimwa.
3. **Restore** → baada ya dakika 5 website inarudi.

Script ya zamani ya JS (`/api/js/<key>/`) inaweza kubaki kama kinga ya ziada, au kuondolewa ili
kurasa zisisubiri JamiiTek kabla ya kuonekana.
