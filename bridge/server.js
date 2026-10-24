/**
 * JamiiTek WhatsApp Bridge
 * ------------------------------------------------------------
 * Bridge ni INJINI tu. Haina akili ya biashara, haina database ya
 * mazungumzo, haiamui chochote. Kazi yake ni mbili:
 *
 *   1. Kupokea ujumbe wa WhatsApp -> kuutuma Django
 *   2. Kupokea amri kutoka Django -> kutuma ujumbe WhatsApp
 *
 * Udhibiti wote (bot ipi, jibu gani, nani analipa) uko JamiiTek.
 *
 * HAIJIBU KWA SYNCHRONOUS. Toleo la kwanza lilisubiri jibu la Django
 * hadi sekunde 120 kisha likatuma `response.data.reply`. Haiwezekani
 * hapa: `_process_message` ya Django inatuma jumbe MBILI mteja
 * anapoanza (salamu, kisha "niambie jina lako"). Mkataba wa jibu moja
 * ungelazimisha kuandika upya state machine nzima.
 *
 * Sasa: bridge inatuma, Django inajibu 200 mara moja, kisha Django
 * inatuma majibu yote kupitia POST /send. Jumbe ngapi inataka.
 */

require('dotenv').config();

const express = require('express');
const axios = require('axios');

const {
    startSession,
    restartSession,
    stopSession,
    getSession,
    listSessions,
    sessions,
} = require('./sessionManager');

const { getPool, closePool, pruneOldKeys } = require('./supabaseAuth');

const app = express();
app.use(express.json({ limit: '1mb' }));

const PORT           = process.env.PORT || 3001;
const DJANGO_URL     = (process.env.DJANGO_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const BRIDGE_API_KEY = process.env.BRIDGE_API_KEY || '';

if (!BRIDGE_API_KEY) {
    console.error('BRIDGE_API_KEY haijawekwa. Bridge haitaanza bila hiyo.');
    process.exit(1);
}


// ============================================================
// ULINZI — kila njia isipokuwa /health
// ============================================================
// Toleo la kwanza lililinda /logout pekee. /qr ilikuwa wazi: mtu
// yeyote aliyejua URL angeweza kuiscan, na namba yake ingekuwa ndiyo
// bot — akisoma mazungumzo yote ya wateja na kuandika kwa niaba yako.

function auth(req, res, next) {
    const given = req.headers['x-bridge-key'] || '';
    if (given !== BRIDGE_API_KEY) {
        return res.status(401).json({ success: false, error: 'Unauthorized' });
    }
    next();
}


// ============================================================
// KUPELEKA UJUMBE DJANGO
// ============================================================

async function forwardToDjango(payload) {
    try {
        const res = await axios.post(
            `${DJANGO_URL}/chatbot/webhook/baileys/`,
            payload,
            {
                headers: {
                    'Content-Type': 'application/json',
                    'X-Bridge-Key': BRIDGE_API_KEY,
                },
                // Django inaji-ack mara moja na kuendelea nyuma, kwa hiyo
                // 15s ingetosha — LAKINI kwenye Render free tier Django
                // inalala baada ya dakika 15 na inachukua sekunde 30-60
                // kuamka. Kwa timeout ya 15s, ujumbe wa KWANZA baada ya
                // kulala unapotea kila mara.
                timeout: Number(process.env.DJANGO_TIMEOUT_MS || 60000),
            }
        );
        console.log(`[${payload.session}]   -> Django: ${res.status}`
                    + ` ${JSON.stringify(res.data).slice(0, 120)}`);
    } catch (e) {
        const detail = e.response
            ? `${e.response.status} ${JSON.stringify(e.response.data).slice(0, 200)}`
            : `${e.code || ''} ${e.message}`;
        console.error(`[${payload.session}]   -> Django IMESHINDWA:`, detail);
    }
}

const sessionOpts = { onMessage: forwardToDjango };


// ============================================================
// HEALTH — njia pekee isiyo na ulinzi
// ============================================================

app.get('/health', (req, res) => {
    res.json({
        success: true,
        service: 'JamiiTek WhatsApp Bridge',
        sessions: sessions.size,
        connected: listSessions().filter((s) => s.connected).length,
        uptime_seconds: Math.round(process.uptime()),
    });
});


// ============================================================
// SESSIONS
// ============================================================

app.get('/sessions', auth, (req, res) => {
    res.json({ success: true, sessions: listSessions() });
});

app.get('/sessions/:name', auth, (req, res) => {
    const s = getSession(req.params.name);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });
    res.json({ success: true, ...s.toJSON() });
});

app.post('/sessions/:name/start', auth, async (req, res) => {
    try {
        const s = await startSession(req.params.name, sessionOpts);
        res.json({ success: true, ...s.toJSON() });
    } catch (e) {
        res.status(500).json({ success: false, error: String(e.message || e) });
    }
});

app.post('/sessions/:name/restart', auth, async (req, res) => {
    try {
        const s = await restartSession(req.params.name, sessionOpts);
        res.json({ success: true, ...s.toJSON() });
    } catch (e) {
        res.status(500).json({ success: false, error: String(e.message || e) });
    }
});

app.post('/sessions/:name/stop', auth, async (req, res) => {
    const ok = await stopSession(req.params.name);
    res.json({ success: ok });
});

// QR — sasa ina ulinzi. Picha yenyewe iko hapa tu, si kwenye /sessions,
// ili orodha isiwe nzito bila sababu.
app.get('/sessions/:name/qr', auth, (req, res) => {
    const s = getSession(req.params.name);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });
    res.json({ success: true, ...s.toJSON(), qr: s.qrDataUrl });
});

// Logout — inafuta auth. Django ndiyo inayodai uthibitisho kwa mtumiaji;
// hapa tunatekeleza tu.
app.post('/sessions/:name/logout', auth, async (req, res) => {
    const s = getSession(req.params.name);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });
    try {
        await s.logout();
        // Anzisha upya ili QR mpya itokee mara moja
        await s.connect();
        res.json({ success: true, ...s.toJSON() });
    } catch (e) {
        res.status(500).json({ success: false, error: String(e.message || e) });
    }
});


// ============================================================
// KUTUMA UJUMBE
// ============================================================

// ── KUTAFSIRI NAMBA -> LID ───────────────────────────────────
// WhatsApp inatumia LID (tarakimu 15) badala ya namba kwa wateja
// wengi. Baileys 6.7.18 haina njia ya LID -> namba, LAKINI
// `onWhatsApp()` inatoa namba -> LID.
//
// Hiyo inatosha kwa tatizo halisi: kutambua MMILIKI. Tunatafsiri
// namba yake mara moja, tunahifadhi LID, kisha tunalinganisha LID
// na LID. Amri zake zinafanya kazi tena.

app.post('/resolve', auth, async (req, res) => {
    const { session, phones } = req.body || {};
    const s = getSession(session);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });
    if (!s.sock || s.status !== 'connected') {
        return res.status(503).json({ success: false, error: `Session ${s.status}` });
    }

    const list = (Array.isArray(phones) ? phones : [phones])
        .filter(Boolean)
        .map((p) => `${String(p).replace(/\D/g, '')}@s.whatsapp.net`);

    if (!list.length) {
        return res.status(400).json({ success: false, error: '`phones` inahitajika' });
    }

    try {
        const out = await s.sock.onWhatsApp(...list);
        const map = {};
        for (const r of out || []) {
            const phone = String(r.jid || '').split('@')[0].split(':')[0];
            map[phone] = {
                exists: Boolean(r.exists),
                jid: r.jid || '',
                lid: r.lid ? String(r.lid).split('@')[0] : '',
            };
        }
        res.json({ success: true, resolved: map });
    } catch (e) {
        res.status(500).json({ success: false, error: String(e.message || e) });
    }
});

// ── UCHUNGUZI ────────────────────────────────────────────────
// Inatenganisha tatizo katika sehemu mbili:
//   /sessions/:name/debug — je, WhatsApp inaongea nasi kabisa?
//   /sessions/:name/ping  — je, tunaweza kutuma?
// Njia ya kuingia ikiwa imekufa na ya kutoka ikiwa hai, tatizo liko
// upande mmoja tu. Zote mbili zikiwa zimekufa, session ni maiti.

app.get('/sessions/:name/debug', auth, (req, res) => {
    const s = getSession(req.params.name);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });

    const d = s.toJSON();
    let verdict;
    if (d.status !== 'connected') {
        verdict = `Haijaunganishwa (${d.status})`;
    } else if (d.event_total === 0) {
        verdict = 'MAITI — imeunganishwa lakini WhatsApp haijatuma tukio hata moja. '
                + 'Kifaa kimeondolewa upande wa WhatsApp. Scan QR upya.';
    } else if (d.silent_seconds > 900) {
        verdict = `Kimya kwa ${Math.round(d.silent_seconds / 60)} dakika — inaweza kuwa imekufa`;
    } else {
        verdict = 'HAI — WhatsApp inaongea nasi';
    }
    res.json({ success: true, verdict, ...d, qr: undefined });
});

// Tuma ujumbe wa majaribio ili kupima njia ya kutoka peke yake
app.post('/sessions/:name/ping', auth, async (req, res) => {
    const s = getSession(req.params.name);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });

    const to = req.body?.to;
    if (!to) return res.status(400).json({ success: false, error: '`to` inahitajika' });

    try {
        const id = await s.sendText(to, req.body?.text || 'Jaribio la JamiiTek bridge.');
        res.json({ success: true, message_id: id,
                   note: 'Imetumwa. Ikiwa haijafika WhatsApp, session ni maiti.' });
    } catch (e) {
        res.status(503).json({ success: false, error: String(e.message || e) });
    }
});

app.post('/send', auth, async (req, res) => {
    const { session, to, text, jid, image_url } = req.body || {};

    // `jid` inatangulia `to`. Django inahifadhi JID halisi iliyopokea,
    // na hiyo ndiyo sahihi daima — hasa kwa LID, ambayo haiwezi
    // kujengwa upya kutoka tarakimu.
    const target = jid || to;

    if (!session || !target || !text) {
        return res.status(400).json({ success: false, error: 'session, to/jid, text zinahitajika' });
    }

    const s = getSession(session);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });

    try {
        // Picha ya bidhaa (duka la JamiiBot): `text` ni maelezo yake. Ikishindwa
        // kupakuliwa, maelezo yanatumwa kama maandishi ili mteja apate bei hata hivyo.
        let id;
        if (image_url && /^https:\/\//.test(image_url)) {
            try {
                id = await s.sendImage(target, image_url, text);
            } catch (e) {
                console.error(`[${session}] picha imeshindwa, natuma maandishi:`, e.message);
                id = await s.sendText(target, text);
            }
        } else {
            id = await s.sendText(target, text);
        }
        res.json({ success: true, message_id: id });
    } catch (e) {
        console.error(`[${session}] /send imeshindwa:`, e.message);
        res.status(503).json({ success: false, error: String(e.message || e) });
    }
});

app.post('/read', auth, async (req, res) => {
    const { session, jid, message_id } = req.body || {};
    const s = getSession(session);
    if (!s) return res.status(404).json({ success: false, error: 'Session haipo' });
    await s.markRead(jid, message_id);
    res.json({ success: true });
});


// ============================================================
// USAFI
// ============================================================

app.post('/prune', auth, async (req, res) => {
    try {
        const days = Number(req.body?.days || 30);
        const removed = await pruneOldKeys(getPool(process.env.DATABASE_URL), days);
        res.json({ success: true, removed });
    } catch (e) {
        res.status(500).json({ success: false, error: String(e.message || e) });
    }
});


// ============================================================
// KUANZA
// ============================================================
// Bridge ikirestart (deploy, crash), inauliza Django ni sessions zipi
// zinapaswa kuwa hewani. Sessions zenyewe ziko Supabase, kwa hiyo
// hakuna kuscan QR upya — zinarudi zilipoishia.

// Django haiwi tayari mara zote bridge inapoanza. Kwenye Render, service
// mbili zinarestart kila moja peke yake, na Django ya free tier inachukua
// sekunde 30-60 kuamka. Bila kurudia, bridge ilikata tamaa mara moja
// (ECONNREFUSED) na bot ZOTE zilibaki chini hadi mtu abonyeze kwa mkono.
const RESTORE_RETRIES = 10;
const RESTORE_WAIT_MS = 15000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function askDjangoForSessions() {
    for (let attempt = 1; attempt <= RESTORE_RETRIES; attempt++) {
        try {
            const r = await axios.get(`${DJANGO_URL}/chatbot/bridge/sessions/`, {
                headers: { 'X-Bridge-Key': BRIDGE_API_KEY },
                timeout: 20000,
            });
            return r.data?.sessions || [];
        } catch (e) {
            const code = e.response?.status;

            // 401/403 si tatizo la muda — ni ufunguo usiolingana.
            // Kusubiri dakika mbili hakutaurekebisha; tunasimama na
            // kusema hasa tatizo ni nini.
            if (code === 401 || code === 403) {
                console.error('');
                console.error('Django imekataa ufunguo (HTTP ' + code + ').');
                console.error('BRIDGE_API_KEY ya bridge na ya Django hazilingani.');
                console.error('');
                return null;
            }

            const last = attempt === RESTORE_RETRIES;
            const why = code ? `HTTP ${code}` : (e.code || e.message);
            console.log(
                `Django haijajibu (${why}) — jaribio ${attempt}/${RESTORE_RETRIES}`
                + (last ? '' : `, inasubiri ${RESTORE_WAIT_MS / 1000}s`)
            );
            if (last) return null;
            await sleep(RESTORE_WAIT_MS);
        }
    }
    return null;
}

async function restoreSessions() {
    const names = await askDjangoForSessions();

    if (names === null) {
        console.error('');
        console.error('Django haikupatikana baada ya majaribio yote.');
        console.error('Anzisha sessions kwa mkono: /manage/chatbot/sessions/');
        console.error('');
        return;
    }

    if (!names.length) {
        console.log('Django haina session inayotakiwa kuanzishwa.');
        return;
    }

    console.log(`Inarudisha sessions ${names.length} kutoka Django...`);
    for (const name of names) {
        try {
            await startSession(name, sessionOpts);
            console.log(`  ${name}: imeanzishwa`);
        } catch (e) {
            console.error(`  ${name}: imeshindwa —`, e.message);
        }
    }
}

const server = app.listen(PORT, () => {
    console.log('');
    console.log('========================================');
    console.log('   JAMIITEK WHATSAPP BRIDGE');
    console.log('========================================');
    console.log(`Port:   ${PORT}`);
    console.log(`Django: ${DJANGO_URL}`);
    console.log('');
    restoreSessions();
});


// ── Kuzima kwa heshima ────────────────────────────────────────

async function shutdown(signal) {
    console.log(`\n${signal} — inazima...`);
    server.close();
    for (const name of Array.from(sessions.keys())) {
        await stopSession(name).catch(() => {});
    }
    await closePool().catch(() => {});
    process.exit(0);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

process.on('unhandledRejection', (e) => {
    console.error('unhandledRejection:', e?.message || e);
});
