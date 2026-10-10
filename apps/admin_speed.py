"""
Kasi ya Django admin: dropdown za ForeignKey kwenye fomu za kuongeza/kuhariri.

`ManagedWebsite.__str__` na `EmailHostingPlan.__str__` zinasoma `client.name`,
kwa hiyo dropdown ya tovuti 50 ilikuwa maswali 50 ya ziada kwenye kila fomu
(HostingPayment, ScheduledAction, ClientNotification, DomainRecord ...).
Hapa kila dropdown ya aina hizo inapata `select_related('client')` — swali moja.
Inaitwa kutoka AppsConfig.ready(), baada ya admin kusajili ModelAdmins zote.
"""
from django.contrib import admin


def _patch(model_admin):
    from apps.models import ManagedWebsite, EmailHostingPlan
    fast = {ManagedWebsite: ('client',), EmailHostingPlan: ('client',)}
    original = model_admin.formfield_for_foreignkey

    def formfield_for_foreignkey(db_field, request, **kwargs):
        rel = db_field.remote_field.model
        if rel in fast and 'queryset' not in kwargs:
            kwargs['queryset'] = rel._default_manager.select_related(*fast[rel])
        return original(db_field, request, **kwargs)

    model_admin.formfield_for_foreignkey = formfield_for_foreignkey


def speed_up_admin():
    from apps.models import ManagedWebsite, EmailHostingPlan
    for model, model_admin in admin.site._registry.items():
        fks = [f for f in model._meta.get_fields()
               if getattr(f, 'many_to_one', False) and getattr(f, 'remote_field', None)
               and f.remote_field.model in (ManagedWebsite, EmailHostingPlan)]
        if fks:
            _patch(model_admin)
