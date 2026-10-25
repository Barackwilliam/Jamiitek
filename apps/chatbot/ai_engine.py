"""
JamiiTek ChatBot — AI Engine (Groq)
Uses Groq API (FREE tier) — 14,400 requests/day, responds in under 1 second.
Get your free key at: https://console.groq.com

MODEL: mnyororo ni BotConfig.ai_model -> GROQ_MODEL (env) -> default.

Kabla, `GROQ_MODEL` ilikuwa hardcoded hapa wakati `BotConfig.ai_model`
ilikuwa inaonekana kwenye admin na portal. Kubadilisha field hakukufanya
kitu — bot zote zilitumia model ile ile. Sasa field inafanya kazi kweli,
na kila bot inaweza kuwa na model yake.
"""
import os
import re
import time
import logging
import requests
from django.conf import settings

logger = logging.getLogger('chatbot.ai')


def clean_reply(text: str) -> str:
    """
    Safisha markdown ya AI ili ionekane vizuri WhatsApp na kwenye widget.

    Model inatoa `**bold**` (markdown) — WhatsApp inaonyesha nyota mbili
    kama zilivyo, jambo linaloharibu mwonekano. WhatsApp inatumia nyota
    MOJA `*bold*`. Kwa hiyo tunabadilisha, tunaondoa vichwa vya markdown,
    na tunasafisha nafasi za ziada.
    """
    if not text:
        return text
    t = text
    t = re.sub(r'\*\*(.+?)\*\*', r'*\1*', t, flags=re.S)   # **x** -> *x*
    t = re.sub(r'__(.+?)__',     r'*\1*', t, flags=re.S)    # __x__ -> *x*
    t = re.sub(r'^#{1,6}\s*(.+)$', r'*\1*', t, flags=re.M)  # ### Heading -> *Heading*
    t = re.sub(r'^\s*[-*]\s+', '• ', t, flags=re.M)          # "- item" / "* item" -> "• item"
    t = t.replace('**', '')                                  # ondoa nyota mbili zilizobaki
    t = re.sub(r'[ \t]+\n', '\n', t)                         # nafasi mwisho wa mstari
    t = re.sub(r'\n{3,}', '\n\n', t)                         # mistari mitupu mingi
    return t.strip()

GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

# BotConfig.ai_model == GEMINI/OPENAI/DEEPSEEK/CLAUDE -> bot hii inajibu kwa AI hiyo kwa
# KEY YA MTEJA mwenyewe (BotConfig.ai_secrets). Key ikikosekana, au AI hiyo ikishindwa
# (kikomo, salio, mtandao), inajibu kwa Groq kama kawaida.
GEMINI = 'gemini'
OPENAI = 'openai'
DEEPSEEK = 'deepseek'
CLAUDE = 'claude'

# secret: jina ndani ya ai_secrets. verify: GET ya bure (orodha ya model) kukagua key.
PROVIDERS = {
    GEMINI:   {'label': 'Gemini',   'secret': 'gemini_api_key',    'prefix': 'AIza',
               'verify': 'https://generativelanguage.googleapis.com/v1beta/models'},
    OPENAI:   {'label': 'OpenAI',   'secret': 'openai_api_key',    'prefix': 'sk-',
               'verify': 'https://api.openai.com/v1/models',
               'chat': 'https://api.openai.com/v1/chat/completions', 'model': 'gpt-4o-mini',
               'max_field': 'max_completion_tokens'},
    DEEPSEEK: {'label': 'DeepSeek', 'secret': 'deepseek_api_key',  'prefix': 'sk-',
               'verify': 'https://api.deepseek.com/models',
               'chat': 'https://api.deepseek.com/chat/completions', 'model': 'deepseek-chat',
               'max_field': 'max_tokens'},
    CLAUDE:   {'label': 'Claude',   'secret': 'anthropic_api_key', 'prefix': 'sk-ant-',
               'model': 'claude-opus-5-5'},
}

MODEL_CHOICES = [
    ('', 'Groq (default ya mfumo)'),
    (GEMINI, 'Gemini Flash — key ya mteja (Groq akiba)'),
    (OPENAI, 'OpenAI — key ya mteja (Groq akiba)'),
    (DEEPSEEK, 'DeepSeek — key ya mteja (Groq akiba)'),
    (CLAUDE, 'Claude — key ya mteja (Groq akiba)'),
    ('llama-3.3-70b-versatile', 'Groq · Llama 3.3 70B'),
    ('openai/gpt-oss-120b', 'Groq · GPT-OSS 120B'),
    ('openai/gpt-oss-20b', 'Groq · GPT-OSS 20B'),
]

# Sheria za mmiliki zikiwepo, AI inapunguziwa "ubunifu" ili izifuate kikamilifu.
RULES_TEMPERATURE = 0.3


def verify_provider_key(provider, key, timeout=10):
    """(ok, ujumbe) — inakagua key kwa kuomba orodha ya model (haitumii salio la mteja)."""
    info = PROVIDERS[provider]
    if provider == CLAUDE:
        import anthropic
        try:
            anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=0).models.list(limit=1)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            return False, f"{info['label']} rejected this key. Copy the full key (starts with {info['prefix']})."
        except anthropic.APIConnectionError:
            return True, 'Saved — could not be checked right now (network).'
        except anthropic.APIStatusError as exc:
            return True, f"Saved — {info['label']} replied HTTP {exc.status_code}; it will be retried on the next reply."
        return True, f"{info['label']} key accepted."
    try:
        if provider == GEMINI:
            r = requests.get(info['verify'], params={'key': key}, timeout=timeout)
        else:
            r = requests.get(info['verify'], headers={'Authorization': f'Bearer {key}'}, timeout=timeout)
    except requests.RequestException:
        return True, 'Saved — could not be checked right now (network).'
    if r.status_code == 200:
        return True, f"{info['label']} key accepted."
    if r.status_code in (400, 401, 403):
        return False, f"{info['label']} rejected this key. Copy the full key (starts with {info['prefix']})."
    return True, f"Saved — {info['label']} replied HTTP {r.status_code}; it will be retried on the next reply."


# Hitilafu ya kiufundi (mtandao, Groq) — si kosa la mteja. Tofauti na
# `bot.fallback_msg`, ambayo ni ya "sielewi swali lako".
TECH_ERROR_MSG = ("Samahani, nimechelewa kidogo kukujibu. "
                  "Tafadhali tuma ujumbe wako tena baada ya dakika moja. 🙏")


class BotAIEngine:

    def __init__(self, bot_config):
        self.bot     = bot_config
        self.api_key = getattr(settings, 'GROQ_API_KEY', '')

    @property
    def provider(self):
        """AI ya key ya mteja ('gemini'/'openai'/'deepseek'/'claude'), au '' kwa Groq."""
        chosen = (getattr(self.bot, 'ai_model', '') or '').strip()
        return chosen if chosen in PROVIDERS else ''

    @property
    def uses_gemini(self):
        return self.provider == GEMINI

    @property
    def model(self):
        """Model ya Groq ya bot hii. Ikiwa tupu (au ni AI ya key ya mteja), tunatumia ya mfumo mzima."""
        chosen = (getattr(self.bot, 'ai_model', '') or '').strip()
        return DEFAULT_MODEL if chosen == '' or chosen in PROVIDERS else chosen

    @property
    def temperature(self):
        t = float(getattr(self.bot, 'ai_temperature', 0.7))
        if (getattr(self.bot, 'custom_rules', '') or '').strip():
            t = min(t, RULES_TEMPERATURE)
        return t

    def _provider_reply(self, messages, start_time):
        """Jibu kwa AI ya key ya MTEJA mwenyewe, au None (basi Groq inajibu)."""
        provider = self.provider
        key = self.bot.ai_key(provider) if hasattr(self.bot, 'ai_key') else ''
        if not key:
            return None
        try:
            if provider == GEMINI:
                text, tokens = self._gemini(messages, key), 0
            elif provider == CLAUDE:
                text, tokens = self._claude(messages, key)
            else:
                text, tokens = self._openai_compatible(provider, messages, key)
        except Exception as exc:
            logger.warning("%s imeshindwa kwa bot %s (%s) — natumia Groq", provider, self.bot.id, exc)
            return None
        if not (text or '').strip():
            return None
        return {'success': True, 'content': clean_reply(text.strip()), 'tokens': tokens,
                'latency_ms': int((time.time() - start_time) * 1000), 'model': provider, 'is_handoff': False}

    def _gemini(self, messages, key):
        from apps import llm
        text, _ = llm.gemini_chat(messages, 500, self.temperature, timeout=25,
                                  model=llm.flash_model(), api_key=key)
        return text

    def _openai_compatible(self, provider, messages, key):
        """OpenAI na DeepSeek zinatumia muundo uleule wa chat/completions."""
        info = PROVIDERS[provider]
        r = requests.post(info['chat'], headers={'Authorization': f'Bearer {key}'}, timeout=25,
                          json={'model': info['model'], 'messages': messages,
                                'temperature': self.temperature, info['max_field']: 500})
        if r.status_code != 200:
            raise RuntimeError(f'HTTP {r.status_code}')
        data = r.json()
        return data['choices'][0]['message']['content'] or '', data.get('usage', {}).get('total_tokens', 0)

    def _claude(self, messages, key):
        """Claude (Anthropic SDK). System prompt ni sehemu yake, si ujumbe."""
        import anthropic
        system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
        chat = [{'role': m['role'], 'content': m['content']} for m in messages if m['role'] != 'system']
        while chat and chat[0]['role'] != 'user':     # mazungumzo lazima yaanze na mteja
            chat.pop(0)
        client = anthropic.Anthropic(api_key=key, timeout=40, max_retries=1)
        # fallbacks="default": Claude ikikataa ombi (refusal), API inajaribu model nyingine yenyewe.
        response = client.beta.messages.create(
            model=PROVIDERS[CLAUDE]['model'], max_tokens=2000, system=system, messages=chat,
            output_config={'effort': 'low'},
            betas=['server-side-fallback-2026-07-01'], fallbacks='default')
        if response.stop_reason == 'refusal':
            raise RuntimeError('refusal')
        text = ''.join(b.text for b in response.content if b.type == 'text')
        return text, response.usage.input_tokens + response.usage.output_tokens

    def build_messages(self, conversation, new_user_message: str) -> list:
        messages = []
        messages.append({
            "role":    "system",
            "content": self.bot.build_system_prompt()
        })
        # Kumbukumbu ya mteja huyu — inaingia kama sehemu ya system
        # prompt, si kama ujumbe. Ni mambo yanayodumu (alichonunua,
        # anapoishi, alichoahidiwa), si nakala ya mazungumzo.
        mem = (getattr(conversation, 'memory', '') or '').strip()
        if mem:
            messages.append({
                "role": "system",
                "content": (
                    "Unachokijua kuhusu mteja huyu kutoka mazungumzo ya nyuma:\n"
                    f"{mem}\n\n"
                    "Tumia taarifa hizi kumjibu kwa ukaribu, lakini USIZITAJE "
                    "moja kwa moja kana kwamba unasoma faili. Kama zinapingana "
                    "na anachosema sasa, anachosema SASA ndicho sahihi."
                ),
            })

        limit  = getattr(self.bot, 'max_context_msgs', 10)
        recent = list(conversation.messages.order_by('-created_at')[:limit * 2])
        recent.reverse()
        for msg in recent:
            if msg.role == 'user':
                messages.append({"role": "user",      "content": msg.content})
            elif msg.role == 'assistant':
                messages.append({"role": "assistant", "content": msg.content})
        messages.append({"role": "user", "content": new_user_message})
        return messages

    def get_response(self, conversation, user_message: str) -> dict:
        start_time = time.time()

        if not self.bot.is_active or self.bot.status != 'active':
            return {'success': False, 'content': self.bot.fallback_msg, 'tokens': 0, 'latency_ms': 0, 'error': 'Bot not active'}

        try:
            sub = self.bot.subscription
            if not sub.is_active:
                return {'success': False, 'content': '', 'tokens': 0, 'latency_ms': 0, 'error': 'Subscription inactive'}
            if sub.messages_remaining <= 0 and not sub.plan.is_unlimited:
                return {'success': False, 'content': self.bot.fallback_msg, 'tokens': 0, 'latency_ms': 0, 'error': 'Message limit reached'}
        except Exception:
            pass

        # Orodha ilikuwa hapa NA kwenye views.py, na hazikulingana —
        # 'mwambie mtu' ilikuwa hapa pekee, 'operator' kule pekee.
        # Sasa ni moja: handoff.TRIGGERS.
        from . import handoff as _ho
        needs_human, _why = _ho.detect(user_message)
        if needs_human:
            return {'success': True, 'content': self.bot.human_handoff_msg,
                    'tokens': 0, 'latency_ms': 0, 'is_handoff': True}

        if self.provider:
            reply = self._provider_reply(self.build_messages(conversation, user_message), start_time)
            if reply:
                return reply

        if not self.api_key:
            logger.error("GROQ_API_KEY not set in settings.py")
            return {'success': False, 'content': self.bot.fallback_msg, 'tokens': 0, 'latency_ms': 0, 'error': 'GROQ_API_KEY not configured'}

        try:
            messages = self.build_messages(conversation, user_message)

            payload = {
                "model":       self.model,
                "messages":    messages,
                "temperature": self.temperature,
                "max_tokens":  500,
                "top_p":       0.9,
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }

            # Jaribu mara mbili. Groq ikirudisha 429 (kikomo cha dakika) au
            # 5xx (hitilafu yao), subiri kidogo ujaribu tena. Awali jaribio
            # moja likishindwa, mteja alijibiwa `fallback_msg` — kwa kawaida
            # "Samahani, sijaelewa" — wakati tatizo halikuwa lake. Alirudia
            # swali, akapata jibu lile lile, akaondoka.
            response = None
            for attempt in (1, 2):
                try:
                    response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=25)
                except requests.Timeout:
                    if attempt == 2:
                        raise
                    time.sleep(1.5)
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                    time.sleep(1.5)
                    continue
                break

            latency = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                try:
                    error_msg = response.json().get('error', {}).get('message', 'Unknown error')
                except ValueError:
                    # Cloudflare/proxy mara nyingi inarudisha HTML, si JSON
                    error_msg = f'HTTP {response.status_code}'
                logger.error(f"Groq API error {response.status_code}: {error_msg}")
                return {'success': False, 'content': TECH_ERROR_MSG, 'tokens': 0, 'latency_ms': latency, 'error': error_msg}

            data    = response.json()
            content = clean_reply(data['choices'][0]['message']['content'].strip())
            tokens  = data.get('usage', {}).get('total_tokens', 0)

            return {'success': True, 'content': content, 'tokens': tokens, 'latency_ms': latency, 'model': self.model, 'is_handoff': False}

        except requests.Timeout:
            latency = int((time.time() - start_time) * 1000)
            return {'success': False, 'content': TECH_ERROR_MSG, 'tokens': 0, 'latency_ms': latency, 'error': 'Request timeout'}
        except Exception as e:
            logger.exception(f"Unexpected AI error for bot {self.bot.id}: {e}")
            return {'success': False, 'content': TECH_ERROR_MSG, 'tokens': 0, 'latency_ms': 0, 'error': str(e)}

    def get_greeting(self, customer_name: str = "") -> str:
        if customer_name:
            return self.bot.greeting_msg.replace('{name}', customer_name)
        return self.bot.greeting_msg