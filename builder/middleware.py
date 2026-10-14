"""
Subdomain routing: dukalangu.jamiitek.com → website ya mteja.
jamiitek.com / www.jamiitek.com / jamiitek.onrender.com → platform yenyewe.
"""
from django.conf import settings
from django.shortcuts import render

# Hosts zinazoserve platform kuu (si website za wateja)
PLATFORM_HOSTS = getattr(settings, 'BUILDER_PLATFORM_HOSTS', {
    'jamiitek.com', 'www.jamiitek.com', 'jamiitek.onrender.com',
    'localhost', '127.0.0.1', 'testserver',
})

BASE_DOMAIN = getattr(settings, 'BUILDER_BASE_DOMAIN', 'jamiitek.com')


class SubdomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self._dispatch(request)
        if getattr(request, 'client_site', None) is not None:
            # "Developed by JamiiTek" kwenye kila ukurasa wa mteja (builder/branding.py)
            from .branding import add_badge_to_response
            response = add_badge_to_response(response, request.client_site)
        return response

    def _dispatch(self, request):
        host = request.get_host().split(':')[0].lower()
        request.client_site = None
        request.subdomain = None

        if host in PLATFORM_HOSTS:
            return self.get_response(request)

        # ── Custom domain ya premium (mfano www.dukalangu.co.tz) ──
        from .models import ClientWebsite
        custom = (
            ClientWebsite.objects
            .filter(custom_domain=host, is_premium=True)
            .select_related('owner')
            .first()
        )
        if custom is None:
            # Fallback pande zote: aliyeingia na www wakati domain imehifadhiwa
            # bila www — au kinyume chake
            alt = host[4:] if host.startswith('www.') else f'www.{host}'
            custom = (
                ClientWebsite.objects
                .filter(custom_domain=alt, is_premium=True)
                .select_related('owner')
                .first()
            )
        if custom is not None:
            if custom.is_suspended:
                return render(request, 'builder/public/site_suspended.html',
                              {'site': custom}, status=403)
            request.client_site = custom
            request.subdomain = custom.subdomain
            request.urlconf = 'builder.public_urls'
            return self.get_response(request)

        subdomain = None
        if host.endswith('.' + BASE_DOMAIN):
            subdomain = host[: -(len(BASE_DOMAIN) + 1)]
        elif host.endswith('.localhost') or host == 'localhost':
            if host != 'localhost':                # duka.localhost:8000
                subdomain = host[: -len('.localhost')]
        else:
            # Host ngeni kabisa (si platform, si subdomain yetu, si custom domain
            # iliyosajiliwa) — USIONYESHE platform juu yake. Hii inaruhusu
            # ALLOWED_HOSTS='*' kwa usalama: middleware ndiyo whitelist.
            return render(request, 'builder/public/site_not_found.html',
                          {'subdomain': host}, status=404)

        if subdomain and '.' not in subdomain and subdomain != 'www':
            site = (
                ClientWebsite.objects
                .filter(subdomain=subdomain)
                .select_related('owner')
                .first()
            )
            if site is None:
                return render(request, 'builder/public/site_not_found.html',
                              {'subdomain': subdomain}, status=404)
            if site.is_suspended:
                return render(request, 'builder/public/site_suspended.html',
                              {'site': site}, status=403)
            request.client_site = site
            request.subdomain = subdomain
            request.urlconf = 'builder.public_urls'   # URLs za website ya mteja tu

        return self.get_response(request)
