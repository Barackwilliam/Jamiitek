"""
Status Guard ya SERVER kwa static websites (index.html) — kama jamiitek_middleware.py ya Django.

Script ya JS (/api/js/<key>/) inazuia kwenye browser tu: ikiondolewa, au JavaScript ikizimwa,
website inaonekana hata bila kulipa — na kila ukurasa unasubiri JamiiTek kabla ya kuonekana.
Hapa uamuzi unafanyika KABLA ukurasa haujatoka, na ukurasa wa "Suspended" unatoka kwenye
server kwa HTTP 503 (Google inaelewa ni wa muda, si maudhui mapya ya website):

  • Cloudflare Worker moja kwa domain zote za wateja zilizo Cloudflare (pamoja na Render /
    GitHub Pages zilizo nyuma ya Cloudflare) — inauliza /api/site-guard/host/<domain>/.
  • cPanel / shared hosting: jamiitek-guard.php + .htaccess — inauliza /api/site-guard/<key>/.

Zote zinahifadhi jibu kwa dakika 5 na zinaachia website ionekane JamiiTek isipojibu (fail-open):
kosa letu halipaswi kumzima mteja aliyelipa. Maelekezo: scripts/static_guard/README.md
"""
from html import escape
from urllib.parse import urlsplit

TITLES = {
    'maintenance': ('🔧', 'Under Maintenance', 'Maintenance Mode', '#f59e0b'),
    'suspended': ('🔒', 'Service Suspended', 'Suspended', '#ef4444'),
}
DEFAULT_MESSAGE = 'This website is temporarily unavailable. Please contact the administrator.'


def host_of(value):
    """'https://WWW.Duka.co.tz/x' au 'duka.co.tz:443' → 'duka.co.tz'."""
    value = (value or '').strip().lower()
    if '//' not in value:
        value = '//' + value
    host = urlsplit(value).hostname or ''
    return host[4:] if host.startswith('www.') else host


def find_by_host(host):
    """ManagedWebsite ambayo URL yake ni domain hii (www au bila www), au None."""
    from .models import ManagedWebsite
    host = host_of(host)
    if not host:
        return None
    for site in ManagedWebsite.objects.filter(url__icontains=host).only('url', 'status', 'name',
                                                                          'suspension_message'):
        if host_of(site.url) == host:
            return site
    return None


def block_page(website):
    """Ukurasa wa 'Suspended' / 'Maintenance' — muundo uleule wa Status Guard ya JS."""
    icon, title, badge, accent = TITLES.get(website.status, TITLES['suspended'])
    msg = escape((website.suspension_message or '').strip() or DEFAULT_MESSAGE)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title} — {escape(website.name)}</title>
</head>
<body style="margin:0;padding:0;min-height:100vh;background:#0b0f1a;font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;display:flex;align-items:center;justify-content:center">
<div style="text-align:center;padding:32px;max-width:520px;width:100%;box-sizing:border-box">
<div style="display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);padding:7px 16px;border-radius:100px;font-size:12px;color:rgba(255,255,255,0.4);font-weight:600;letter-spacing:0.5px;margin-bottom:32px"><span style="width:7px;height:7px;border-radius:50%;background:{accent};display:inline-block"></span>{badge}</div>
<div style="font-size:72px;margin-bottom:24px;line-height:1">{icon}</div>
<h1 style="font-size:clamp(22px,4vw,32px);font-weight:800;color:#fff;margin:0 0 16px;letter-spacing:-0.5px">{title}</h1>
<p style="font-size:16px;color:rgba(255,255,255,0.5);line-height:1.7;margin:0 auto 32px;max-width:400px">{msg}</p>
<div style="display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:10px;border:1px solid rgba(255,255,255,0.08);color:rgba(255,255,255,0.25);font-size:13px">Managed by JamiiTek</div>
</div>
</body>
</html>"""


def payload(website):
    """Jibu kwa Worker / PHP. Website isiyojulikana = hai (fail-open)."""
    if website is None or website.is_active:
        return {'active': True, 'status': getattr(website, 'status', 'active')}
    return {'active': False, 'status': website.status, 'html': block_page(website)}


PHP_GUARD = r"""<?php
/*
 * JamiiTek Status Guard (server) — {name}
 * Weka faili hii pamoja na .htaccess kwenye folda ya website (public_html), kando ya index.html.
 * Kila ukurasa wa .html unapita hapa kwanza. JamiiTek ikisema website imesimamishwa, mgeni
 * anapata ukurasa wa "Service Suspended" (HTTP 503). Jibu linahifadhiwa dakika 5; JamiiTek
 * isipojibu, website inaonekana kama kawaida.
 * Usibadilishe API — inatoka JamiiTek (Manage → Websites → {name}).
 */
$JT_API = '{api}';
$JT_TTL = 300;

function jt_state($api, $ttl) {
    $cache = sys_get_temp_dir() . '/jt_guard_' . md5($api) . '.json';
    $old = is_file($cache) ? json_decode((string) @file_get_contents($cache), true) : null;
    if (is_array($old) && time() - filemtime($cache) < $ttl) {
        return $old;
    }
    $raw = false;
    if (function_exists('curl_init')) {
        $ch = curl_init($api);
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 3, CURLOPT_CONNECTTIMEOUT => 3]);
        $raw = curl_exec($ch);
        if (curl_getinfo($ch, CURLINFO_HTTP_CODE) !== 200) { $raw = false; }
        curl_close($ch);
    } elseif (ini_get('allow_url_fopen')) {
        $raw = @file_get_contents($api, false, stream_context_create(['http' => ['timeout' => 3]]));
    }
    $data = $raw === false ? null : json_decode($raw, true);
    if (is_array($data) && isset($data['active'])) {
        @file_put_contents($cache, $raw, LOCK_EX);
        return $data;
    }
    return is_array($old) ? $old : null;   // JamiiTek haijibu: jibu la mwisho, au fail-open
}

$root = realpath(__DIR__);
$uri  = rawurldecode((string) parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH));
$file = realpath($root . '/' . ltrim($uri, '/'));
if ($file !== false && is_dir($file)) {
    $file = realpath($file . '/index.html');
}
// Faili ya .html ndani ya folda ya website tu (hakuna ../ wala mafaili ya PHP)
if ($file === false || strpos($file, $root . DIRECTORY_SEPARATOR) !== 0
        || !preg_match('/\.html?$/i', $file) || !is_file($file)) {
    http_response_code(404);
    $nf = $root . '/404.html';
    if (is_file($nf)) { header('Content-Type: text/html; charset=utf-8'); readfile($nf); }
    exit;
}

$state = jt_state($JT_API, $JT_TTL);
if (is_array($state) && empty($state['active']) && !empty($state['html'])) {
    http_response_code(503);
    header('Retry-After: 3600');
    header('Cache-Control: no-store');
    header('Content-Type: text/html; charset=utf-8');
    echo $state['html'];
    exit;
}
header('Content-Type: text/html; charset=utf-8');
readfile($file);
"""

HTACCESS = """# JamiiTek Status Guard (server) — kurasa zote za .html zinapita jamiitek-guard.php kwanza
DirectoryIndex index.html
RewriteEngine On
RewriteCond %{REQUEST_FILENAME} -d [OR]
RewriteCond %{REQUEST_URI} \\.html?$ [NC]
RewriteRule ^ jamiitek-guard.php [L,QSA]
"""


def php_guard(website, api_url):
    return PHP_GUARD.replace('{name}', website.name.replace('*/', '')).replace(
        '{api}', api_url.replace("'", ''))
