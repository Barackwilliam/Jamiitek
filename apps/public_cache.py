"""
Cache ya maudhui ya kurasa za umma (Home, Services, About, footer ya SEO).

KWA NINI SI CACHE YA KAWAIDA

Bila Redis, `caches['default']` ni DatabaseCache (lazima iwe hivyo kwa ratiba
ya DailyTasksMiddleware — angalia settings.py). Lakini kusoma DatabaseCache ni
ombi la database lenyewe: kwenye Render → Supabase kila ombi ni safari ya
mtandao. Kwa maudhui ya ukurasa wa nyumbani hilo halisaidii kitu.

Hii inatumia `caches['local']` (RAM ya process) — haina gharama ya mtandao.

UPYA WA MAUDHUI

  - Kila kitu kinaisha muda baada ya sekunde PUBLIC_TTL (60).
  - Admin akihifadhi au kufuta Service, HeroSlide, PortfolioItem, Testimonial,
    Team, Question, BlogPost, CompanyProfile au WebsiteTemplate, toleo linapanda na cache ya process hiyo
    inafutika papo hapo. Process nyingine (kama gunicorn ina workers
    kadhaa) zinaona badiliko ndani ya dakika moja.

Kwa hiyo hakuna data ya mteja wala ya siri hapa — maudhui ya umma tu.
"""
from django.core.cache import caches
from django.db.models.signals import post_delete, post_save

PUBLIC_TTL = 60
_VERSION_KEY = 'public:ver'


def _cache():
    return caches['local']


def _version():
    c = _cache()
    v = c.get(_VERSION_KEY)
    if v is None:
        v = 1
        c.set(_VERSION_KEY, v, None)
    return v


def get_or_build(name, builder, ttl=PUBLIC_TTL):
    """Rudisha thamani iliyohifadhiwa, au ijenge (orodha/dict — si QuerySet)."""
    c = _cache()
    key = f'public:{_version()}:{name}'
    value = c.get(key)
    if value is None:
        value = builder()
        c.set(key, value, ttl)
    return value


def bump(*_args, **_kwargs):
    c = _cache()
    try:
        c.incr(_VERSION_KEY)
    except ValueError:
        c.set(_VERSION_KEY, 2, None)


def connect_signals():
    """Inaitwa kutoka AppConfig.ready()."""
    from .models import BlogPost, CompanyProfile, Question, Service, Team, WebsiteTemplate
    from .site_content import HeroSlide, PortfolioItem, Testimonial

    for model in (Service, Team, Question, BlogPost, CompanyProfile,
                  HeroSlide, PortfolioItem, Testimonial, WebsiteTemplate):
        post_save.connect(bump, sender=model, dispatch_uid=f'public_cache_save_{model.__name__}')
        post_delete.connect(bump, sender=model, dispatch_uid=f'public_cache_del_{model.__name__}')
