from django.contrib import admin
from .models import (ClientWebsite, SitePage, SiteCollection, SiteItem, SiteAsset, AiUsageLog, SiteInquiry,
                     BuilderPricing, BuildRequest)


@admin.register(ClientWebsite)
class ClientWebsiteAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'subdomain', 'website_type', 'owner',
                    'is_published', 'is_premium', 'hosting_until', 'is_suspended', 'created_at')
    list_filter = ('website_type', 'is_published', 'is_premium', 'legacy_free', 'is_suspended')
    search_fields = ('site_name', 'subdomain', 'owner__username')
    actions = ['suspend_sites', 'unsuspend_sites']

    @admin.action(description='Simamisha websites (suspend)')
    def suspend_sites(self, request, queryset):
        queryset.update(is_suspended=True)

    @admin.action(description='Rudisha websites (unsuspend)')
    def unsuspend_sites(self, request, queryset):
        queryset.update(is_suspended=False)


@admin.register(BuilderPricing)
class BuilderPricingAdmin(admin.ModelAdmin):
    """Bei za jumla za Builder — rekodi moja tu."""
    fields = ('remove_logo_price', 'yearly_hosting_price', 'build_fee', 'badge_old_sites_from')

    def has_add_permission(self, request):
        return not BuilderPricing.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BuildRequest)
class BuildRequestAdmin(admin.ModelAdmin):
    """Maombi ya "Unahitaji tukutengenezee?" — 'Paid' = mteja amelipa, anza kazi."""
    list_display = ('business_name', 'name', 'phone', 'template_name', 'amount', 'status', 'paid_at', 'created_at')
    list_editable = ('status',)
    list_filter = ('status',)
    search_fields = ('business_name', 'name', 'phone', 'email', 'template_name')
    readonly_fields = ('token', 'template', 'template_name', 'template_price', 'build_fee', 'amount',
                       'paid_at', 'created_at', 'photo_links')
    fields = ('status', 'notes', 'business_name', 'name', 'phone', 'email', 'about', 'photo_links',
              'template', 'template_name', 'template_price', 'build_fee', 'amount', 'paid_at', 'created_at', 'token')

    @admin.display(description='Photos')
    def photo_links(self, obj):
        from django.utils.html import format_html_join
        return format_html_join(' ', '<a href="{}" target="_blank" rel="noopener">Photo {}</a>',
                                ((u, i + 1) for i, u in enumerate(obj.photos or []))) or '—'


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'website', 'updated_at')
    search_fields = ('title', 'website__subdomain')


@admin.register(SiteCollection)
class SiteCollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'website')


@admin.register(SiteItem)
class SiteItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'collection', 'is_visible', 'is_featured', 'updated_at')
    list_filter = ('is_visible', 'is_featured')


admin.site.register(SiteAsset)
admin.site.register(AiUsageLog)


@admin.register(SiteInquiry)
class SiteInquiryAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'website', 'item', 'status', 'created_at')
    list_select_related = ('website', 'item')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'phone', 'email', 'website__subdomain')
