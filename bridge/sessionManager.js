/**
 * Session Manager — sessions nyingi kwenye mchakato mmoja.
 *
 * Toleo la kwanza lilikuwa la session MOJA: `whatsappSocket`,
 * `connectionStatus`, `connectedNumber` zote zilikuwa variables za
 * module. Deployment moja = bot moja.
 *
 * Hapa kila session ni kitu chake ndani ya Map. `supabaseAuth.js`
 * ilikuwa tayari kwa hili tangu mwanzo — PRIMARY KEY yake ni
 * (session_name, key_id).
 *
 * MAMBO MATATU YALIYOREKEBISHWA KUTOKA TOLEO LA KWANZA:
 *
 * 1. Socket ya zamani inafungwa kabla ya reconnect.
 *    Zamani `connectToWhatsApp()` ilijiita yenyewe na kuacha socket
 *    ya zamani hai pamoja na listeners zake. Sasa tunaita
 *    `teardown()` kwanza.
 *
 * 2. Backoff inapanda na ina kikomo.
 *    Zamani ilikuwa sekunde 3 zisizobadilika, bila kikomo — WhatsApp
 *    ikikataa, bot iliipiga kila sekunde 3 milele.
 *
 * 3. Jumbe zinashughulikiwa kwa pamoja.
 *    Zamani `await` ilikuwa ndani ya `for` loop yenye timeout ya
 *    sekunde 120. Mkulima wa tano alisubiri wanne wamalize.
 */

const {
    default: makeWASocket,
    DisconnectReason,
    fetchLatestBaileysVersion,
    downloadMediaMessage,
} = require('@whiskeysockets/baileys');

const { Boom } = require('@hapi/boom');
const QRCode = require('qrcode');
const pino = require('pino');

const { getPool, useSupabaseAuthState } = require('./supabaseAuth');

const logger = pino({ level: process.env.BAILEYS_LOG_LEVEL || 'silent' });

// Baileys ina log nyingi sana; tunaituliza na kutumia console yetu.
const log = (session, ...args) => console.log(`[${session}]`, ...args);

const RECONNECT_BASE_MS = 3000;
const RECONNECT_MAX_MS  = 5 * 60 * 1000;   // dakika 5
const MAX_ATTEMPTS      = 20;

// Ukubwa wa juu wa sauti tunayopakua. Voice note ya dakika moja ni
// ~100KB; dakika tano ni ~500KB. 5MB inatosha kwa ujumbe wowote wa
// kawaida, na inazuia mtu kutuma faili kubwa kuchoma bandwidth.
const MAX_AUDIO_BYTES = 5 * 1024 * 1024;

// Baileys haitoi kosa lolote ikishindwa kufikia WhatsApp — inakaa kimya.
// Bila hii, session inakwama 'starting' milele na dashboard inaonyesha
// "Inaanza" bila kikomo, bila sababu. Tunaweka mpaka.
const CONNECT_TIMEOUT_MS = 60000;

/** @type {Map<string, Session>} */
const sessions = new Map();


class Session {
    constructor(name, { onMessage }) {
        this.name = name;
        this.onMessage = onMessage;

        this.sock = null;
        this.status = 'starting';      // starting | waiting_qr | connected | disconnected | logged_out
        this.number = '';
        this.qrDataUrl = '';
        this.qrAt = 0;
        this.lastError = '';
        this.attempts = 0;
        this.startedAt = Date.now();
        this.lastMessageAt = null;
        this.connectedAt = null;

        this._reconnectTimer = null;
        this._watchdog = null;
        this._stopping = false;

        // Hesabu ya KILA tukio linalotoka WhatsApp.
        //
        // `connection: open` haimaanishi ujumbe unafika. WhatsApp
        // inaweza kuondoa kifaa (mtu amebonyeza "Log out from all
        // devices", au kifaa kipya kimechukua nafasi) na client
        // ikaendelea kudhani imeunganishwa. Socket inakuwa maiti
        // inayoonekana hai.
        //
        // Socket HAI daima ina kelele: presence, receipts, chats.update.
        // Ikiwa kimya kabisa, imekufa.
        this.events = {};
        this.lastEventAt = null;
        this._clearAuth = null;
    }

    // ── Hali kwa Django ───────────────────────────────────────
    toJSON() {
        const qrAge = this.qrAt ? Math.round((Date.now() - this.qrAt) / 1000) : null;
        return {
            session: this.name,
            status: this.status,
            connected: this.status === 'connected',
            number: this.number,
            qr_age_seconds: qrAge,
            qr_expired: qrAge !== null && qrAge > 60,
            last_error: this.lastError,
            attempts: this.attempts,
            started_at: new Date(this.startedAt).toISOString(),
            connected_at: this.connectedAt ? new Date(this.connectedAt).toISOString() : null,
            last_message_at: this.lastMessageAt ? new Date(this.lastMessageAt).toISOString() : null,

            // Uchunguzi
            wa_id: this.sock?.user?.id || '',
            wa_name: this.sock?.user?.name || '',
            ws_state: this.sock?.ws?.socket?.readyState ?? this.sock?.ws?.readyState ?? null,
            events: this.events,
            event_total: Object.values(this.events).reduce((a, b) => a + b, 0),
            last_event_at: this.lastEventAt ? new Date(this.lastEventAt).toISOString() : null,
            silent_seconds: this.lastEventAt
                ? Math.round((Date.now() - this.lastEventAt) / 1000)
                : null,
        };
    }

    // ── Kufunga socket ya zamani kabisa ───────────────────────
    _armWatchdog() {
        this._clearWatchdog();
        this._watchdog = setTimeout(() => {
            if (this.status === 'starting') {
                this.status = 'disconnected';
                this.lastError = 'WhatsApp haikujibu ndani ya sekunde 60 — angalia mtandao';
                log(this.name, this.lastError);
                this._scheduleReconnect();
            }
        }, CONNECT_TIMEOUT_MS);
    }

    _clearWatchdog() {
        if (this._watchdog) {
            clearTimeout(this._watchdog);
            this._watchdog = null;
        }
    }

    async teardown() {
        this._clearWatchdog();
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        const sock = this.sock;
        this.sock = null;
        if (!sock) return;
        try {
            sock.ev.removeAllListeners();
        } catch (_) { /* tayari imefungwa */ }
        try {
            // end() bila error inafunga muunganisho bila kutoa logout
            sock.end(undefined);
        } catch (_) { /* tayari imefungwa */ }
    }

    async stop() {
        this._stopping = true;
        await this.teardown();
        this.status = 'disconnected';
    }

    // ── Kuanzisha ─────────────────────────────────────────────
    async connect() {
        this._stopping = false;
        await this.teardown();

        const pool = getPool(process.env.DATABASE_URL);
        const auth = await useSupabaseAuthState(pool, this.name);
        this._clearAuth = auth.clearAuth;

        const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

        const sock = makeWASocket({
            version,
            auth: auth.state,
            logger,
            markOnlineOnConnect: false,
            syncFullHistory: false,
            browser: ['JamiiTek', 'Chrome', '1.0.0'],
        });

        this.sock = sock;

        this._armWatchdog();

        // Hesabu kila tukio kabla ya handlers maalum
        sock.ev.process(async (events) => {
            for (const name of Object.keys(events)) {
                this.events[name] = (this.events[name] || 0) + 1;
                this.lastEventAt = Date.now();
            }
        });

        sock.ev.on('creds.update', auth.saveCreds);
        sock.ev.on('connection.update', (u) => this._onConnectionUpdate(u));
        sock.ev.on('messages.upsert', (e) => this._onMessages(e));

        return this;
    }

    _onConnectionUpdate(update) {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            this._clearWatchdog();
            this.status = 'waiting_qr';
            QRCode.toDataURL(qr, { width: 320, margin: 2 })
                .then((url) => {
                    this.qrDataUrl = url;
                    this.qrAt = Date.now();
                })
                .catch((e) => log(this.name, 'QR image error:', e.message));
            log(this.name, 'QR mpya — inasubiri kuscan');
        }

        if (connection === 'open') {
            this._clearWatchdog();
            this.status = 'connected';
            this.qrDataUrl = '';
            this.qrAt = 0;
            this.attempts = 0;
            this.lastError = '';
            this.connectedAt = Date.now();
            this.number = (this.sock?.user?.id || '').split(':')[0].replace(/\D/g, '');
            log(this.name, 'IMEUNGANISHWA —', this.number);
        }

        if (connection === 'close') {
            const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode;
            const loggedOut = statusCode === DisconnectReason.loggedOut;

            this.lastError = `close ${statusCode ?? '?'}`;
            log(this.name, 'muunganisho umefungwa, code:', statusCode);

            if (this._stopping) return;

            if (loggedOut) {
                this.status = 'logged_out';
                this.number = '';
                log(this.name, 'imetolewa kwenye kifaa — inasubiri QR mpya');
                // Futa auth kisha anza upya ili QR mpya itokee
                const clear = this._clearAuth;
                this.teardown()
                    .then(() => (clear ? clear() : null))
                    .then(() => this._scheduleReconnect(true))
                    .catch((e) => log(this.name, 'clearAuth error:', e.message));
                return;
            }

            this.status = 'disconnected';
            this._scheduleReconnect();
        }
    }

    _scheduleReconnect(immediate = false) {
        if (this._stopping) return;
        if (this._reconnectTimer) return;

        this.attempts += 1;
        if (this.attempts > MAX_ATTEMPTS) {
            log(this.name, `imejaribu mara ${MAX_ATTEMPTS} — imesimama. Anzisha kwa mkono.`);
            this.status = 'disconnected';
            this.lastError = `imekata baada ya majaribio ${MAX_ATTEMPTS}`;
            return;
        }

        // Backoff: 3s, 6s, 12s, 24s ... hadi dakika 5
        const delay = immediate
            ? 2000
            : Math.min(RECONNECT_BASE_MS * 2 ** (this.attempts - 1), RECONNECT_MAX_MS);

        log(this.name, `inaunganisha upya baada ya ${Math.round(delay / 1000)}s (jaribio ${this.attempts})`);

        this._reconnectTimer = setTimeout(() => {
            this._reconnectTimer = null;
            this.connect().catch((e) => {
                log(this.name, 'reconnect imeshindwa:', e.message);
                this.lastError = e.message;
                this._scheduleReconnect();
            });
        }, delay);
    }

    _onMessages(event) {
        // MACHO KWENYE KILA HATUA.
        //
        // Toleo la kwanza lilikuwa na sehemu NNE zinazokata kimyakimya:
        // type si 'notify', fromMe, status@broadcast, kundi, na _extract
        // ikirudisha null. Ujumbe ukikufa mojawapo, logs zilikuwa kimya
        // kabisa — huwezi kutofautisha "haujafika" na "umechujwa".
        const n = (event.messages || []).length;
        log(this.name, `messages.upsert: type=${event.type} count=${n}`);

        if (event.type !== 'notify') {
            log(this.name, `  imerukwa: type ni '${event.type}', si 'notify'`);
            return;
        }

        // Hakuna `await` hapa — kila ujumbe una handler yake; mmoja
        // akichelewa, wengine hawasubiri.
        for (const message of event.messages) {
            this._handleOne(message).catch((e) =>
                log(this.name, '  handler error:', e.message)
            );
        }
    }

    async _handleOne(message) {
        const remoteJid = message.key.remoteJid || '';
        const mid = message.key.id || '?';

        if (message.key.fromMe) {
            log(this.name, `  ${mid}: imerukwa — fromMe`);
            return;
        }
        if (remoteJid === 'status@broadcast') {
            log(this.name, `  ${mid}: imerukwa — status@broadcast`);
            return;
        }
        if (remoteJid.endsWith('@g.us')) {
            log(this.name, `  ${mid}: imerukwa — kundi`);
            return;
        }

        const parsed = await this._extract(message, remoteJid);
        if (!parsed) {
            const kinds = Object.keys(message.message || {}).join(',') || '(tupu)';
            log(this.name, `  ${mid}: imerukwa — aina haijulikani: ${kinds}`);
            return;
        }

        log(this.name, `  ${mid}: kutoka ${parsed.phone} [${parsed.msg_type}] `
                     + `"${(parsed.text || '').slice(0, 60)}"`);

        this.lastMessageAt = Date.now();

        // Onyesha "anaandika..." — mteja anajua ujumbe umefika
        this.sendPresence(remoteJid, 'composing').catch(() => {});

        await this.onMessage({
            session: this.name,
            jid: remoteJid,
            ...parsed,
        });
    }

    async _extract(message, remoteJid) {
        // WhatsApp sasa hutumia @lid (kitambulisho) badala ya namba.
        // Tunajaribu kupata namba halisi kwa njia mbili; ikishindikana
        // TUNAENDELEA kwa LID — bot haipaswi kunyamaza kwa sababu ya
        // kitambulisho.
        let sourceJid = remoteJid;
        let isLid = false;

        if (remoteJid.endsWith('@lid')) {
            isLid = true;
            let pn = message.key.senderPn || '';
            if (!pn) {
                try {
                    pn = await this.sock?.signalRepository
                        ?.lidMapping?.getPNForLID?.(remoteJid) || '';
                } catch (_) { pn = ''; }
            }
            if (pn) { sourceJid = pn; isLid = false; }
        }

        // JID huwa na kiambishi cha kifaa: "255712345678:0@s.whatsapp.net".
        // Bila kuondoa ":0", tarakimu hiyo huungana na namba na mteja
        // huhifadhiwa kama 2557123456780 — na akitumia simu pamoja na
        // WhatsApp Web (:0 na :1) huonekana kama watu wawili tofauti.
        const phone = sourceJid.split('@')[0].split(':')[0].replace(/\D/g, '');
        if (!phone) return null;

        const m = message.message || {};
        let text = '';
        let msgType = 'text';
        let filename = '';
        let audio = null;

        if (m.conversation) {
            text = m.conversation;
        } else if (m.extendedTextMessage?.text) {
            text = m.extendedTextMessage.text;
        } else if (m.imageMessage) {
            msgType = 'image';
            text = m.imageMessage.caption || '';
        } else if (m.videoMessage) {
            msgType = 'video';
            text = m.videoMessage.caption || '';
        } else if (m.documentMessage) {
            msgType = 'document';
            text = m.documentMessage.caption || '';
            filename = m.documentMessage.fileName || '';
        } else if (m.audioMessage) {
            msgType = 'audio';
            // Sauti inapakuliwa hapa na kupelekwa Django ikiwa base64.
            // Django inaipeleka Groq Whisper na kupata maandishi.
            //
            // Bila hii, ujumbe wa sauti ulikuwa unakuwa "[Sauti]" na AI
            // haikuwa na cha kufanya nayo. Wateja wa Tanzania wanatuma
            // voice note nyingi kuliko maandishi.
            audio = await this._downloadAudio(message);
        } else if (m.stickerMessage) {
            msgType = 'sticker';
        } else if (m.locationMessage) {
            msgType = 'location';
        } else if (m.listResponseMessage?.singleSelectReply?.selectedRowId) {
            // Jibu la orodha — tunatuma kichwa chake kama maandishi
            text = m.listResponseMessage.title
                || m.listResponseMessage.singleSelectReply.selectedRowId;
        } else if (m.buttonsResponseMessage?.selectedDisplayText) {
            text = m.buttonsResponseMessage.selectedDisplayText;
        } else {
            return null;   // reactions, polls, n.k.
        }

        return {
            phone,
            is_lid: isLid,
            message_id: message.key.id || '',
            text: (text || '').trim(),
            msg_type: msgType,
            filename,
            contact_name: message.pushName || '',
            audio_base64: audio ? audio.data : '',
            audio_mime:   audio ? audio.mime : '',
            audio_seconds: m.audioMessage?.seconds || 0,
            location: m.locationMessage ? {
                latitude: m.locationMessage.degreesLatitude,
                longitude: m.locationMessage.degreesLongitude,
                name: m.locationMessage.name || '',
                address: m.locationMessage.address || '',
            } : null,
        };
    }

    async _downloadAudio(message) {
        const info = message.message?.audioMessage;
        if (!info) return null;

        const size = Number(info.fileLength || 0);
        if (size && size > MAX_AUDIO_BYTES) {
            log(this.name, `  sauti ni kubwa mno (${Math.round(size / 1024)}KB) — imerukwa`);
            return null;
        }

        try {
            const buf = await downloadMediaMessage(message, 'buffer', {},
                { logger, reuploadRequest: this.sock.updateMediaMessage });
            if (!buf || buf.length > MAX_AUDIO_BYTES) return null;
            log(this.name, `  sauti imepakuliwa: ${Math.round(buf.length / 1024)}KB`);
            return { data: buf.toString('base64'), mime: info.mimetype || 'audio/ogg' };
        } catch (e) {
            log(this.name, '  kupakua sauti kumeshindwa:', e.message);
            return null;
        }
    }

    // ── Kutuma ────────────────────────────────────────────────
    async sendText(to, text) {
        if (!this.sock || this.status !== 'connected') {
            throw new Error(`session ${this.name} haijaunganishwa (${this.status})`);
        }

        // MUHIMU: `to` inaweza kuwa JID kamili au namba.
        //
        // WhatsApp sasa inatumia LID (kitambulisho cha tarakimu 15) badala
        // ya namba kwa wateja wengi. LID inaishia `@lid`, si
        // `@s.whatsapp.net`. Kuijenga upya kutoka tarakimu kulikuwa
        // kunazalisha `158351803576497@s.whatsapp.net` — JID isiyo halali,
        // na jibu halikwenda popote. Django ilidhani imetuma.
        //
        // Kwa hiyo Django inatuma JID halisi iliyoipokea, na tunaitumia
        // kama ilivyo.
        const jid = this.constructor.toJid(to);
        const res = await this.sock.sendMessage(jid, { text: String(text) });
        await this.sendPresence(jid, 'paused').catch(() => {});
        log(this.name, `  -> imetumwa kwa ${jid}`);
        return res?.key?.id || '';
    }

    async sendImage(to, url, caption) {
        if (!this.sock || this.status !== 'connected') {
            throw new Error(`session ${this.name} haijaunganishwa (${this.status})`);
        }
        const jid = this.constructor.toJid(to);
        const res = await this.sock.sendMessage(jid, { image: { url: String(url) }, caption: String(caption || '').trim() });
        await this.sendPresence(jid, 'paused').catch(() => {});
        log(this.name, `  -> picha imetumwa kwa ${jid}`);
        return res?.key?.id || '';
    }

    static toJid(to) {
        const v = String(to || '').trim();
        if (v.includes('@')) return v;                 // tayari ni JID
        const digits = v.replace(/\D/g, '');
        // LID ni ndefu kuliko namba yoyote ya simu (tarakimu 15+).
        // Namba ndefu zaidi duniani ni 15, lakini pamoja na kiambishi
        // cha nchi haizidi 15 kwa vitendo. 15+ bila '+' ni LID.
        if (digits.length >= 15) return `${digits}@lid`;
        return `${digits}@s.whatsapp.net`;
    }

    async sendPresence(jid, kind) {
        if (!this.sock || this.status !== 'connected') return;
        await this.sock.sendPresenceUpdate(kind, jid);
    }

    async markRead(jid, messageId) {
        if (!this.sock || this.status !== 'connected' || !messageId) return;
        try {
            await this.sock.readMessages([{ remoteJid: jid, id: messageId, participant: undefined }]);
        } catch (_) { /* si muhimu */ }
    }

    async logout() {
        try {
            if (this.sock) await this.sock.logout();
        } catch (_) { /* tayari imekufa */ }
        if (this._clearAuth) await this._clearAuth();
        await this.teardown();
        this.status = 'logged_out';
        this.number = '';
        this.qrDataUrl = '';
        this.attempts = 0;
    }
}


// ── API ya manager ────────────────────────────────────────────

async function startSession(name, opts) {
    let s = sessions.get(name);
    if (s) {
        // Tayari ipo — ikiwa imekufa, anzisha upya tu
        if (s.status === 'connected') return s;
        await s.teardown();
    } else {
        s = new Session(name, opts);
        sessions.set(name, s);
    }
    s.attempts = 0;
    await s.connect();
    return s;
}

async function restartSession(name, opts) {
    const s = sessions.get(name);
    if (s) {
        await s.teardown();
        s.attempts = 0;
        await s.connect();
        return s;
    }
    return startSession(name, opts);
}

async function stopSession(name) {
    const s = sessions.get(name);
    if (!s) return false;
    await s.stop();
    sessions.delete(name);
    return true;
}

function getSession(name) {
    return sessions.get(name) || null;
}

function listSessions() {
    return Array.from(sessions.values()).map((s) => s.toJSON());
}


module.exports = {
    Session,
    startSession,
    restartSession,
    stopSession,
    getSession,
    listSessions,
    sessions,
};
