/**
 * Supabase (Postgres) Auth State kwa Baileys
 * ------------------------------------------------------------
 * Badala ya kuhifadhi session kwenye folda (auth_info_baileys),
 * tunaihifadhi kwenye database. Ni muhimu kwa Render na hosting
 * yoyote yenye filesystem ya muda — bila hii, session inafutwa
 * kila deploy na inabidi uscan QR upya.
 *
 * TOFAUTI NA TOLEO LA KWANZA: module hii HAIUNDI pool yake.
 * Inapokea pool kutoka nje.
 *
 * Sababu: `connectToWhatsApp()` inajiita yenyewe kila reconnect.
 * Toleo la zamani liliunda `new Pool({max: 3})` kila mwito na
 * halikufunga ya zamani. Mtandao ukikatika mara 20 usiku mmoja,
 * ulikuwa na connections 60 zinazoelekea Supabase — na Django
 * inashiriki database ile ile, kwa hiyo si bot pekee
 * iliyokufa.
 *
 * Pool moja ya mchakato mzima inaondoa tatizo kwenye mzizi
 * badala ya kuweka kiraka cha `close()` mahali pengi.
 *
 * Matumizi:
 *   const { getPool, useSupabaseAuthState } = require('./supabaseAuth');
 *   const pool = getPool(process.env.DATABASE_URL);
 *   const { state, saveCreds, clearAuth } =
 *       await useSupabaseAuthState(pool, 'kilimoni');
 */

const { Pool } = require('pg');

const {
    initAuthCreds,
    BufferJSON,
    proto,
} = require('@whiskeysockets/baileys');


// ── Pool moja kwa mchakato mzima ──────────────────────────────

let _pool = null;

function getPool(connectionString) {
    if (_pool) return _pool;

    if (!connectionString) {
        throw new Error('DATABASE_URL haijawekwa kwa Supabase auth state');
    }

    // Supabase inadai SSL; Postgres ya kwenye kompyuta yako haina.
    // Kulazimisha SSL kila mara kunazuia development ya ndani kabisa.
    const local = /(^|[@/])localhost|127\.0\.0\.1|host=\//.test(connectionString)
        || process.env.PGSSL === 'disable';

    _pool = new Pool({
        connectionString,
        ssl: local ? false : { rejectUnauthorized: false },
        // Sessions zote zinashiriki pool hii. 10 inatosha kwa sessions
        // nyingi kwa sababu maswali ni mafupi; Supabase pooler ina kikomo
        // na Django inahitaji nafasi yake pia.
        max: Number(process.env.PG_POOL_MAX || 10),
        idleTimeoutMillis: 30000,
        connectionTimeoutMillis: 10000,
    });

    _pool.on('error', (err) => {
        console.error('[pg] pool error:', err.message);
    });

    return _pool;
}

async function closePool() {
    if (_pool) {
        await _pool.end();
        _pool = null;
    }
}


// ── Jedwali — linaundwa mara moja tu ──────────────────────────

let _schemaReady = null;

async function ensureSchema(pool) {
    if (_schemaReady) return _schemaReady;

    _schemaReady = (async () => {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS baileys_auth (
                session_name TEXT NOT NULL,
                key_id       TEXT NOT NULL,
                value        JSONB,
                updated_at   TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (session_name, key_id)
            )
        `);
        // Kwa prune_baileys_keys — inachuja kwa updated_at
        await pool.query(`
            CREATE INDEX IF NOT EXISTS baileys_auth_updated_idx
            ON baileys_auth (updated_at)
        `);
    })();

    return _schemaReady;
}


// ── Auth state kwa session moja ───────────────────────────────

async function useSupabaseAuthState(pool, sessionName = 'default') {

    if (!pool) {
        throw new Error('pool inahitajika — tumia getPool() kwanza');
    }

    await ensureSchema(pool);

    async function readData(keyId) {
        try {
            const res = await pool.query(
                'SELECT value FROM baileys_auth WHERE session_name = $1 AND key_id = $2',
                [sessionName, keyId]
            );
            if (!res.rows.length) return null;
            return JSON.parse(JSON.stringify(res.rows[0].value), BufferJSON.reviver);
        } catch (e) {
            console.log(`[auth:${sessionName}] read error:`, keyId, e.message);
            return null;
        }
    }

    async function writeData(keyId, value) {
        try {
            // Tunatuma maandishi ya JSON (si object) na ::jsonb — `pg` hubadilisha array ya JS
            // kuwa array ya Postgres ('{"0","84"}'), si JSON, kwa hiyo funguo kama
            // device-list zilikataliwa ("invalid input syntax for type json").
            const json = JSON.stringify(value, BufferJSON.replacer);
            await pool.query(
                `INSERT INTO baileys_auth (session_name, key_id, value, updated_at)
                 VALUES ($1, $2, $3::jsonb, NOW())
                 ON CONFLICT (session_name, key_id)
                 DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()`,
                [sessionName, keyId, json]
            );
        } catch (e) {
            console.log(`[auth:${sessionName}] write error:`, keyId, e.message);
        }
    }

    async function removeData(keyId) {
        try {
            await pool.query(
                'DELETE FROM baileys_auth WHERE session_name = $1 AND key_id = $2',
                [sessionName, keyId]
            );
        } catch (e) {
            console.log(`[auth:${sessionName}] delete error:`, keyId, e.message);
        }
    }

    const creds = (await readData('creds')) || initAuthCreds();

    const state = {
        creds,
        keys: {
            get: async (type, ids) => {
                const data = {};
                await Promise.all(ids.map(async (id) => {
                    let value = await readData(`${type}-${id}`);
                    if (type === 'app-state-sync-key' && value) {
                        value = proto.Message.AppStateSyncKeyData.fromObject(value);
                    }
                    data[id] = value;
                }));
                return data;
            },
            set: async (data) => {
                const tasks = [];
                for (const type in data) {
                    for (const id in data[type]) {
                        const value = data[type][id];
                        const keyId = `${type}-${id}`;
                        tasks.push(value ? writeData(keyId, value) : removeData(keyId));
                    }
                }
                await Promise.all(tasks);
            },
        },
    };

    return {
        state,

        saveCreds: async () => {
            await writeData('creds', state.creds);
        },

        // Inatumika baada ya logout ili session ianze upya
        clearAuth: async () => {
            await pool.query(
                'DELETE FROM baileys_auth WHERE session_name = $1',
                [sessionName]
            );
            console.log(`[auth:${sessionName}] session imefutwa`);
        },
    };
}


// ── Usafi: funguo za app-state-sync za zamani ─────────────────
// Baileys inatengeneza app-state-sync-key nyingi zinazoacha kutumika.
// Zikikaa, jedwali linakua bila sababu. Hii inaitwa na Django
// (`prune_baileys_keys`) au kwa mkono.

async function pruneOldKeys(pool, days = 30) {
    const res = await pool.query(
        `DELETE FROM baileys_auth
         WHERE key_id LIKE 'app-state-sync-key-%'
           AND updated_at < NOW() - ($1 || ' days')::interval`,
        [String(days)]
    );
    return res.rowCount;
}


module.exports = {
    getPool,
    closePool,
    useSupabaseAuthState,
    pruneOldKeys,
};
