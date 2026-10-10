"""
Admin ya integrations.

Credentials hazionekani baada ya kuhifadhiwa — unaandika mpya au unaacha.
Kila kufichua au kubadilisha kunaingia IntegrationAuditLog.
"""
import json

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from .integrations import ADAPTERS
from .models import Integration, IntegrationAuditLog, IntegrationSnapshot


class IntegrationForm(forms.ModelForm):

    credentials_input = forms.CharField(
        label='Credentials (JSON)',
        widget=forms.Textarea(attrs={'rows': 4, 'style': 'font-family:monospace'}),
        required=False,
        help_text='Acha wazi usipotaka kubadilisha. Mfano: {"api_key": "rnd_..."}',
    )

    class Meta:
        model = Integration
        exclude = ('credentials',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['provider'] = forms.ChoiceField(
            choices=[(k, c.label) for k, c in ADAPTERS.items()])

    def clean(self):
        cleaned = super().clean()
        raw = (cleaned.get('credentials_input') or '').strip()

        if raw:
            try:
                creds = json.loads(raw)
            except ValueError:
                raise forms.ValidationError({'credentials_input': 'JSON si sahihi.'})
            if not isinstance(creds, dict):
                raise forms.ValidationError({'credentials_input': 'Inatakiwa iwe object.'})
            self._new_creds = creds
        else:
            self._new_creds = None
            if not self.instance.pk:
                raise forms.ValidationError({'credentials_input': 'Credentials zinahitajika.'})
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self._new_creds is not None:
            obj.credentials = self._new_creds
        if commit:
            obj.save()
        return obj


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    form = IntegrationForm

    list_display = ('website', 'provider', 'display_name',
                    'health_badge', 'last_synced_at', 'monthly_cost_usd')
    list_filter = ('provider', 'is_active', 'sync_error')
    search_fields = ('website__name', 'display_name', 'external_id', 'account_email')
    readonly_fields = ('cached_summary_pretty', 'last_synced_at',
                       'sync_error', 'created_at', 'updated_at')
    actions = ['action_sync']

    fieldsets = (
        (None, {'fields': ('website', 'provider', 'display_name',
                           'external_id', 'is_active')}),
        ('Credentials', {'fields': ('credentials_input',),
                         'description': 'Zimefichwa kwa Fernet. Hazionekani tena.'}),
        ('Biashara', {'fields': ('account_email', 'plan', 'monthly_cost_usd',
                                 'renews_on', 'notes')}),
        ('Hali ya sync', {'fields': ('cached_summary_pretty', 'last_synced_at',
                                     'sync_error', 'created_at', 'updated_at')}),
    )

    @admin.display(description='Health')
    def health_badge(self, obj):
        colors = {'ok': '#1D9E75', 'stale': '#BA7517',
                  'error': '#E24B4A', 'disabled': '#888780'}
        h = obj.health
        return format_html(
            '<span style="color:{};font-weight:500">● {}</span>',
            colors.get(h, '#888780'), h)

    @admin.display(description='Data ya mwisho')
    def cached_summary_pretty(self, obj):
        if not obj.cached_summary:
            return '—'
        return format_html('<pre style="margin:0">{}</pre>',
                           json.dumps(obj.cached_summary, indent=2, default=str))

    @admin.action(description='Sync sasa')
    def action_sync(self, request, queryset):
        ok = sum(1 for i in queryset if i.sync())
        for i in queryset:
            IntegrationAuditLog.record('sync_manual', user=request.user,
                                       integration=i, request=request)
        self.message_user(request, f'Zimefanikiwa {ok}/{queryset.count()}.',
                          messages.SUCCESS if ok else messages.WARNING)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        IntegrationAuditLog.record(
            'update' if change else 'connect',
            user=request.user, integration=obj, request=request,
            detail={'provider': obj.provider,
                    'creds_changed': form._new_creds is not None})
        obj.sync()


@admin.register(IntegrationSnapshot)
class IntegrationSnapshotAdmin(admin.ModelAdmin):
    list_display = ('integration', 'checked_at')
    list_select_related = ('integration',)

    def get_queryset(self, request):
        # metrics ni JSON kubwa; orodha haiitumii
        return super().get_queryset(request).defer('metrics')
    list_filter = ('integration__provider',)
    date_hierarchy = 'checked_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(IntegrationAuditLog)
class IntegrationAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'action', 'website', 'ip_address')
    list_select_related = ('user', 'website')
    list_filter = ('action',)
    search_fields = ('user__username', 'website__name')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
