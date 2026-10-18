# apps/context_processors.py
"""
Context processors — kuweka variables zote za template kwenye context
"""

from django.conf import settings


def turnstile_context(request):
    """
    Sitekey ndiyo public, inaeleweka kwenye browser
    Secret hairuhusu kuonekana kwa frontend — stay kwenye backend tu
    """
    return {
        "TURNSTILE_ENABLED": settings.TURNSTILE_ENABLED,
        "TURNSTILE_SITEKEY": settings.TURNSTILE_SITEKEY if settings.TURNSTILE_ENABLED else "",
        "PESAPAL_ENABLED": getattr(settings, "PESAPAL_ENABLED", False),
    }


_NAV_EXACT = {
    'management_dashboard': 'dashboard',
    'manage_ai': 'ai',
    'manage_builder': 'builder',
    'manage_chatbot': 'chatbot',
    'manage_bot_clients': 'bot_clients',
    'manage_bot_payments': 'bot_payments',
    'infra_overview': 'infra',
    'infra_audit': 'infra_audit',
    'lead_list': 'leads',
    'profile_builder': 'profile',
    'email_log_list': 'emails',
    'site_domain_list': 'site_domains',
}

_NAV_PREFIX = (
    ('website',            'websites'),
    ('client',             'clients'),
    ('domain',             'domains'),
    ('email_hosting',      'email'),
    ('invoice',            'invoices'),
    ('receipt',            'receipts'),
    ('proposal_builder',   'proposals'),
    ('contract_builder',   'contracts'),
    ('infra',              'infra'),
)


def sidebar_nav(request):
    match = getattr(request, 'resolver_match', None)
    name = getattr(match, 'url_name', '') or ''

    if name in _NAV_EXACT:
        return {'nav': _NAV_EXACT[name]}

    for prefix, key in _NAV_PREFIX:
        if name.startswith(prefix):
            return {'nav': key}

    return {'nav': ''}


def social_links(request):
    """Links za mitandao ya kijamii — zilizowekwa pekee."""
    from django.conf import settings
    return {'SOCIAL': {k: v for k, v in getattr(settings, 'SOCIAL_LINKS', {}).items() if v}}


def ai_health(request):
    """Onyo la Gemini kushindwa kwa wafanyakazi (/manage na admin) — linasomwa tu kiolezo kikilitumia."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {}

    def load():
        from apps import llm
        try:
            return llm.health()
        except Exception:
            return None
    return {'ai_health': load}
