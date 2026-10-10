import os
from pathlib import Path
from dotenv import load_dotenv
import cloudinary

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
WEBSITE_TYPES_DIR = BASE_DIR / 'website_types'

# ── Security ──────────────────────────────────────────
_DEV_SECRET_KEY = 'django-insecure-dev-only-key-change-me'
SECRET_KEY = os.getenv('SECRET_KEY', '').strip() or _DEV_SECRET_KEY
# Local development sets DEBUG=True in .env; Render leaves it unset so
# production is safe by default rather than by remembering.
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
# SECRET_KEY inasaini sessions, password-reset tokens na cookies. Key ya
# default iko wazi kwenye GitHub — kwa production ingemruhusu yeyote
# kutengeneza session ya admin. Kama ilivyo kwa DB_PASSWORD, tunakataa kuanza.
# (Key halali za Django nyingi zinaanza na 'django-insecure-' — hizo ni sawa;
# tunakataa tu key tupu au hii ya default iliyo wazi.)
if not DEBUG and SECRET_KEY == _DEV_SECRET_KEY:
    raise RuntimeError(
        'SECRET_KEY ya production haijawekwa. Weka SECRET_KEY ndefu ya siri '
        '(herufi 50+) kwenye Render → Environment.'
    )
# MUHIMU: dot ya mwanzo (.jamiitek.com / .localhost) inaruhusu SUBDOMAINS ZOTE.
# 'localhost' pekee HAIRUHUSU duka.localhost — lazima '.localhost' iwepo.
ALLOWED_HOSTS = [h.strip() for h in os.getenv(
    'ALLOWED_HOSTS',
    '.jamiitek.com,jamiitek.onrender.com,127.0.0.1,localhost,.localhost'
).split(',') if h.strip()]


CSRF_TRUSTED_ORIGINS = [
    'https://jamiitek.com',
    'https://www.jamiitek.com',
    'https://jamiitek.onrender.com',
]

# ── Usalama nyuma ya Cloudflare / Render proxy ─────────────────
# Cloudflare (na Render) zinaishia TLS na kupitisha ombi kwa Django
# zikiwa na header `X-Forwarded-Proto`. Bila mstari huu, Django
# ingedhani kila ombi ni http, na `SECURE_SSL_REDIRECT` ingesababisha
# mzunguko usioisha. IP halisi ya mteja inasomwa na
# `apps.turnstile.get_client_ip` kupitia `CF-Connecting-IP`.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Hardening — inawaka kwenye production pekee (DEBUG=False), ili dev ya
# http isivunjike. Kila moja ina njia ya kuzima kwa env kama ikileta
# tatizo (mfano bridge ikishindwa kufika webhook, weka SSL_REDIRECT=0).
if not DEBUG:
    SECURE_SSL_REDIRECT   = os.getenv('SSL_REDIRECT', 'True').lower() == 'true'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE    = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    X_FRAME_OPTIONS = 'SAMEORIGIN'
    # HSTS: browser inakumbuka kutumia https pekee (inazuia SSL-stripping).
    # SSL_REDIRECT tayari inalazimisha https, kwa hiyo mwaka mmoja ni salama;
    # weka HSTS_SECONDS=0 kuzima.
    SECURE_HSTS_SECONDS = int(os.getenv('HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('HSTS_SUBDOMAINS', 'False').lower() == 'true'
    SECURE_HSTS_PRELOAD = False

# ── Sessions & cookies ────────────────────────────────
# Cookie za session hazisomeki na JavaScript (XSS haiwezi kuziiba), hazitumwi
# na tovuti za nje kwenye POST (SameSite=Lax), na session inaisha baada ya
# siku 7 baada ya kuingia.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE    = 'Lax'
SESSION_COOKIE_AGE      = int(os.getenv('SESSION_COOKIE_AGE', str(7 * 24 * 3600)))
SESSION_SAVE_EVERY_REQUEST = False

# Login zote (portal, JamiiBot, builder, manage, admin) zinafungwa kwa muda
# baada ya makosa mengi — angalia apps/security.py.
AUTHENTICATION_BACKENDS = ['apps.security.ThrottledModelBackend']

# Link ya "Forgot password" inatumika mara moja na inakufa baada ya saa 1
PASSWORD_RESET_TIMEOUT = 60 * 60

# Kwa DEV tu: ruhusu host yoyote (inarahisisha kutest custom domains kwa hosts file)


INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sitemaps',
    # 'django.contrib.sites' imeondolewa kwa makusudi.
    #
    # Ilikuwepo bila SITE_ID. Katika hali hiyo get_current_site()
    # inatafuta Site kwa host ya ombi. Row pekee iliyokuwepo ni
    # 'example.com' (default ya migration), kwa hiyo /sitemap.xml
    # ilikuwa inaanguka kwa Site.DoesNotExist -> 500 kwenye jamiitek.com.
    #
    # Ikiondolewa, Django inatumia RequestSite(request) — host halisi ya
    # ombi. Ndiyo sahihi hapa: builder inahudumia subdomains na custom
    # domains, kila moja inahitaji sitemap yenye domain yake.
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'apps',
    'apps.chatbot',
    'apps.wafanyakazi',
    'cloudinary',
    'builder',
]

# 'uploadcare' imeondolewa kabisa. Image zote sasa ziko Supabase Storage
# (apps/storage.py). Uploadcare imebaki kama integration ya kufuatilia
# akaunti kwenye /manage/infra/ pekee — si kupakia.

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',      # <- hapa
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # Staff lazima wapite 2FA kabla ya ukurasa wowote (apps/two_factor.py)
    'apps.two_factor.StaffTwoFactorMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.turnstile_middleware.TurnstileMiddleware',
    'builder.middleware.SubdomainMiddleware',
    'apps.seo.middleware.NoIndexMiddleware',
    'apps.daily_tasks.DailyTasksMiddleware',
    'apps.security.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'jamiitek.urls'

# @login_required ilipeleka watu /accounts/login/ — ukurasa usiokuwepo (404).
# Login ya web builder ndiyo ya wateja wa platform.
LOGIN_URL = '/builder/login/'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'apps' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.context_processors.turnstile_context',
                'apps.context_processors.sidebar_nav',
                'apps.context_processors.social_links',

            ],
        },
    },
]




WSGI_APPLICATION = 'jamiitek.wsgi.application'

# ── Database ──────────────────────────────────────────
# Njia mbili: DATABASE_URL moja (GitHub Actions inatumia hii), au DB_* moja
# moja (Render / .env yako). Hakuna nywila iliyoandikwa hapa kwa makusudi.
DATABASE_URL = os.getenv('DATABASE_URL', '')

if DATABASE_URL:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(
        DATABASE_URL, conn_max_age=60, ssl_require=True)}
else:
    _db_password = os.getenv('DB_PASSWORD', '')
    if not _db_password and not DEBUG:
        raise RuntimeError(
            'DB_PASSWORD (au DATABASE_URL) haijawekwa. Weka environment '
            'variables kabla ya kuanzisha mfumo kwenye production.'
        )
    DATABASES = {
        'default': {
            'ENGINE':   'django.db.backends.postgresql',
            'NAME':     os.getenv('DB_NAME', 'postgres'),
            'USER':     os.getenv('DB_USER', ''),
            'PASSWORD': _db_password,
            'HOST':     os.getenv('DB_HOST', ''),
            'PORT':     os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 60,
            'OPTIONS': {
                'sslmode': 'require',
                'connect_timeout': 10,
            },
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalization ───────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Dar_es_Salaam'
USE_I18N      = True
USE_TZ        = True

# ── Static & Media ─────────────────────────────────────
STATIC_URL          = '/static/'
# STATICFILES_DIRS    = [BASE_DIR / 'apps' / 'static']
STATIC_ROOT         = BASE_DIR / 'staticfiles'

# Django 5.1 REMOVED the old STATICFILES_STORAGE setting. Leaving it here did
# nothing at all — no manifest, no compression, no cache-busting — and Django
# gave no warning about it. STORAGES is the replacement.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# MEDIA_URL ilikuwa inaelekea Cloudinary, lakini hakuna ImageField hata
# moja kwenye models — image zote ni URL zilizohifadhiwa kama maandishi.
# Kwa hiyo haikuwa ikitumika kwa chochote. Imebaki kwa ajili ya Django
# admin pekee, ikielekea Supabase.
MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Jazzmin ────────────────────────────────────────────
JAZZMIN_SETTINGS = {
    "site_title":   "JamiiTek Admin",
    "site_header":  "JamiiTek Dashboard",
    "site_brand":   "JamiiTek",
    "welcome_sign": "Welcome to JamiiTek Dashboard",
    "copyright":    "JamiiTek © 2026",
    "search_model": "auth.User",
    "topmenu_links": [
        {"name": "Home",  "url": "admin:index", "permissions": ["auth.view_user"]},
        {"model": "auth.User"},
        {"app":   "JamiiTek System"},
    ],
    # BlogPost ina fieldsets 4 (Content/SEO/Publishing/Stats). Tunaionyesha
    # kama ukurasa mmoja (sio tabs) ili ifanane na fomu zingine kama Client.
    "changeform_format_overrides": {"apps.blogpost": "single"},
    # Bila hii Jazzmin inapakia Google Fonts kwa kila ukurasa (render-blocking)
    "use_google_fonts_cdn": False,
}

JAZZMIN_UI_TWEAKS = {
    "theme":           "darkly",
    "navbar_fixed":    True,
    "sidebar_fixed":   True,
    "footer_fixed":    False,
    # UI builder inaongeza JS/CSS kwenye kila ukurasa wa admin — imezimwa kwa kasi
    "show_ui_builder": False,
}

# ── Uploadcare & Cloudinary ────────────────────────────
WEASPRINT_BASEURL = BASE_DIR
 
# ── Email ──────────────────────────────────────────────
_email_user = os.getenv('EMAIL_HOST_USER', 'info@jamiitek.com')
_email_pass = os.getenv('EMAIL_HOST_PASSWORD', '')
 
# ── Njia ya kutuma, kwa mpangilio ─────────────────────────────
# 1. Brevo (HTTPS) — Render free INAZUIA ports 25/465/587 (tangu
#    26 Sep 2025). HTTPS haiwezi kuzuiliwa, kwa hiyo hii ndiyo pekee
#    inayofanya kazi hapo.
# 2. SMTP — inafanya kazi Render ya kulipia, au kwenye kompyuta yako.
# 3. Console — hakuna kinachotoka; dev pekee.
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')

if BREVO_API_KEY:
    EMAIL_BACKEND      = 'apps.email_backend.BrevoEmailBackend'
    EMAIL_HOST_USER    = _email_user
    DEFAULT_FROM_EMAIL = f"JamiiTek <{_email_user}>"

elif _email_user and _email_pass:
    # Host ilikuwa imefungwa kwa 'smtp.gmail.com'. jamiitek.com iko Zoho
    # (MX: mx.zoho.com), kwa hiyo Gmail haikuweza kutuma kamwe.
    EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST          = os.getenv('EMAIL_HOST', 'smtp.zoho.com')
    EMAIL_PORT          = int(os.getenv('EMAIL_PORT', '587'))
    EMAIL_USE_TLS       = os.getenv('EMAIL_USE_SSL', 'False').lower() != 'true'
    EMAIL_USE_SSL       = not EMAIL_USE_TLS
    EMAIL_HOST_USER     = _email_user
    EMAIL_HOST_PASSWORD = _email_pass
    DEFAULT_FROM_EMAIL  = f"JamiiTek <{_email_user}>"
    # Bila timeout, SMTP iliyozuiliwa inakwama hadi gunicorn inaua worker:
    #   Worker (pid:79) was sent SIGKILL!
    EMAIL_TIMEOUT       = int(os.getenv('EMAIL_TIMEOUT', '10'))
else:
    # Fallback: log emails to console instead of crashing
    EMAIL_BACKEND   = 'django.core.mail.backends.console.EmailBackend'
    EMAIL_HOST_USER = 'info@jamiitek.com'
    DEFAULT_FROM_EMAIL = 'JamiiTek <info@jamiitek.com>'
 
PORTAL_BASE_URL = os.getenv('PORTAL_BASE_URL', 'https://jamiitek.com/portal/')
 
# ── Cloudinary ─────────────────────────────────────────
CLOUDINARY_API_KEY    = os.getenv('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET', '')

# ── Chatbot / WhatsApp ─────────────────────────────────
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
# www ni MUHIMU. `jamiitek.com` ni redirect 301, na 301 kwenye POST
# inageuzwa kuwa GET — Django inajibu 405. Pia viungo vya email
# vinapaswa kwenda moja kwa moja, si kupitia redirect.
SITE_URL     = os.getenv('SITE_URL', 'https://www.jamiitek.com')

WHATSAPP_MASTER_TOKEN         = os.getenv('WHATSAPP_MASTER_TOKEN', '')
WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.getenv('WHATSAPP_WEBHOOK_VERIFY_TOKEN', '')
# App Secret ya Meta — inahitajika kuthibitisha X-Hub-Signature-256 ya webhook
WHATSAPP_APP_SECRET           = os.getenv('WHATSAPP_APP_SECRET', '')
WILLIAM_WHATSAPP              = os.getenv('WILLIAM_WHATSAPP', '')
WILLIAM_PHONE_NUMBER_ID       = os.getenv('WILLIAM_PHONE_NUMBER_ID', '')

# ── Supabase Storage (image zote) ──────────────────────
# Image hazihifadhiwi kwenye disk ya Render — filesystem yake ni ya
# muda, kila deploy inafuta kila kitu. Zinakwenda Supabase Storage,
# na database inahifadhi URL pekee.
#
# Funguo zinabaki SERVER. Zikifika browser, mtu anaweza kufuta
# storage yako yote.
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_BUCKET = os.getenv('SUPABASE_BUCKET', 'media')

# Funguo za S3, SI service_role.
#
# `service_role` inafungua database yote — wateja, mazungumzo, invoice
# — pamoja na Auth. S3 keys zinafungua Storage pekee. Kwa funguo
# inayokaa Render ikiwa na kazi moja ya kupakia picha, hizi ndizo
# sahihi.
#
# Supabase > Storage > S3 Access Keys > New access key
SUPABASE_S3_ACCESS_KEY = os.getenv('SUPABASE_S3_ACCESS_KEY', '')
SUPABASE_S3_SECRET_KEY = os.getenv('SUPABASE_S3_SECRET_KEY', '')
SUPABASE_S3_REGION     = os.getenv('SUPABASE_S3_REGION', 'us-east-1')

# ── Baileys Bridge ─────────────────────────────────────
# Bridge ni mchakato wa Node unaoshikilia socket za WhatsApp.
# Ufunguo mmoja unatumika pande zote mbili: Django inautuma kwenye
# kila ombi kwenda bridge, na inaukagua kwenye webhook inayoingia.
BRIDGE_URL     = os.getenv('BRIDGE_URL', '')
BRIDGE_API_KEY = os.getenv('BRIDGE_API_KEY', '')

CHATBOT_PAYMENT_INFO = {
    'bank':           'NMB Bank',
    'account_number': os.getenv('NMB_ACCOUNT', ''),
    'account_name':   os.getenv('NMB_NAME', ''),
    'branch':         'Dar es Salaam',
}

# ── JamiiTek Website Builder ──
BUILDER_BASE_DOMAIN = os.getenv('BUILDER_BASE_DOMAIN', 'jamiitek.com')
BUILDER_PLATFORM_HOSTS = {
    'jamiitek.com', 'www.jamiitek.com', 'jamiitek.onrender.com',
    'localhost', '127.0.0.1', 'testserver',
}

# ── Cache: Redis kwa production (weka REDIS_URL kwenye Render env), LocMem kwa dev ──
if os.getenv('REDIS_URL'):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': os.getenv('REDIS_URL'),
            'TIMEOUT': 3600,
        }
    }
else:
    # Bila Redis, cache INABIDI iwe ya database — si ya kumbukumbu.
    #
    # Ratiba yote ya mfumo (DailyTasksMiddleware) inatambua "kazi hii
    # imeshafanyika" kwa alama zilizohifadhiwa kwenye cache. LocMemCache
    # inakaa kwenye RAM ya process moja, kwa hiyo:
    #   • kila deploy au restart -> alama zinapotea -> digest, chatbot_digest
    #     na monthly_report zinatumwa TENA siku ile ile
    #   • gunicorn ikiwa na worker zaidi ya mmoja -> kila worker ina cache
    #     yake -> kazi ile ile inakimbia mara kadhaa kwa wakati mmoja
    #
    # DatabaseCache inashirikiwa na workers wote na inadumu baada ya
    # restart. Jedwali linaundwa na migration (createcachetable).
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': 'jamiitek_cache',
            'TIMEOUT': 3600,
            'OPTIONS': {'MAX_ENTRIES': 5000, 'CULL_FREQUENCY': 4},
        }
    }


# ── Mitandao ya kijamii ───────────────────────────────
# Vitufe vya footer vilikuwa href="#" — mtu anabonyeza, hakuna kinachotokea.
# Sasa kitufe kinaonekana TU kama link yake imewekwa hapa au kwenye Render.
SOCIAL_LINKS = {
    'facebook':  os.getenv('SOCIAL_FACEBOOK', ''),
    'linkedin':  os.getenv('SOCIAL_LINKEDIN', ''),
    'instagram': os.getenv('SOCIAL_INSTAGRAM', ''),
    'github':    os.getenv('SOCIAL_GITHUB', 'https://github.com/Barackwilliam'),
    'twitter':   os.getenv('SOCIAL_TWITTER', ''),
    'youtube':   os.getenv('SOCIAL_YOUTUBE', ''),
}

# ── Cloudflare Turnstile (Bot Protection) ──────────────
TURNSTILE_SITEKEY = os.getenv('TURNSTILE_SITEKEY', '')
TURNSTILE_SECRET  = os.getenv('TURNSTILE_SECRET', '')
TURNSTILE_ENABLED = bool(TURNSTILE_SITEKEY and TURNSTILE_SECRET)


# ── Pesapal (Malipo — API 3.0) ─────────────────────────
# Weka hizi kwenye env. PESAPAL_ENV: 'sandbox' (default) au 'live'.
# PESAPAL_IPN_ID ni hiari — ikikosekana tunasajili IPN moja kwa moja.
# PESAPAL_BASE_URL: root ya tovuti kwa callback/IPN (mfano https://www.jamiitek.com)
PESAPAL_CONSUMER_KEY    = os.getenv('PESAPAL_CONSUMER_KEY', '')
PESAPAL_CONSUMER_SECRET = os.getenv('PESAPAL_CONSUMER_SECRET', '')
PESAPAL_ENV             = os.getenv('PESAPAL_ENV', 'sandbox')
PESAPAL_IPN_ID          = os.getenv('PESAPAL_IPN_ID', '')
PESAPAL_BASE_URL        = os.getenv('PESAPAL_BASE_URL', 'https://www.jamiitek.com')
PESAPAL_ENABLED         = bool(PESAPAL_CONSUMER_KEY and PESAPAL_CONSUMER_SECRET)
# Nakala ya risiti/arifa za malipo humwendea mmiliki
PAYMENTS_OWNER_EMAIL    = os.getenv('PAYMENTS_OWNER_EMAIL', 'info@jamiitek.com')

# ── AI Newsroom (rasimu za habari za kila siku) ────────
SITE_BASE_URL        = os.getenv('SITE_BASE_URL', 'https://www.jamiitek.com')
BLOG_REVIEW_EMAIL    = os.getenv('BLOG_REVIEW_EMAIL', 'info@jamiitek.com')
UNSPLASH_ACCESS_KEY  = os.getenv('UNSPLASH_ACCESS_KEY', '')

# ── Logging ──────────────────────────────────────────────────────
# Bila hii, DEBUG=False inaficha traceback za makosa ya 500: Django inazituma
# kwa ADMINS (hawajawekwa) tu. Sasa zinaandikwa kwenye stderr, na zinaonekana
# kwenye Render → Logs.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
    },
}

# ── Namba za mawasiliano (apps/contact.py) ─────────────────
# Timu (simu + WhatsApp + M-Pesa) na JamiiBot ya majaribio. Zisipowekwa,
# apps/contact.py inatumia namba rasmi za sasa.
JAMIITEK_PHONE = os.getenv('JAMIITEK_PHONE', '')
JAMIIBOT_DEMO_WHATSAPP = os.getenv('JAMIIBOT_DEMO_WHATSAPP', '')
