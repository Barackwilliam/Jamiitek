# apps/site_admin.py
"""
Admin for the homepage content models.

Register by adding this line to the bottom of apps/admin.py:

    from .site_admin import *   # noqa
"""

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .site_content import HeroSlide, PortfolioItem, Testimonial
from .supabase_widget import SupabaseImageWidget


# ──────────────────────────────────────────────────────────────
# Forms — each gets an upload button with the right crop shape
# ──────────────────────────────────────────────────────────────
class HeroSlideForm(forms.ModelForm):
    class Meta:
        model = HeroSlide
        fields = '__all__'
        widgets = {'image': SupabaseImageWidget(folder='hero')}


class PortfolioItemForm(forms.ModelForm):
    class Meta:
        model = PortfolioItem
        fields = '__all__'
        widgets = {'image': SupabaseImageWidget(folder='portfolio')}


class TestimonialForm(forms.ModelForm):
    class Meta:
        model = Testimonial
        fields = '__all__'
        widgets = {'image': SupabaseImageWidget(folder='testimonials')}


# ──────────────────────────────────────────────────────────────
class PreviewMixin:
    @admin.display(description='Preview')
    def preview(self, obj):
        if not obj.image:
            return format_html('<span style="color:#999">— no image —</span>')
        return format_html(
            '<img src="{}" style="height:52px;width:92px;object-fit:cover;'
            'border-radius:6px;border:1px solid #ddd">',
            obj.cdn(184, 104),
        )


@admin.register(HeroSlide)
class HeroSlideAdmin(PreviewMixin, admin.ModelAdmin):
    form = HeroSlideForm
    list_display = ('preview', 'headline', 'eyebrow', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    list_display_links = ('headline',)
    fieldsets = (
        ('Photo', {
            'fields': ('image', 'focal'),
            'description': 'Click the upload button, choose a landscape photo '
                           '(at least 1920&times;1080), then Save.',
        }),
        ('Text', {
            'fields': ('eyebrow', 'headline', 'subheadline'),
            'description': 'Wrap words in *asterisks* to colour them gold, '
                           'e.g. <code>That *Drive Success*</code>',
        }),
        ('Buttons', {
            'fields': ('cta_label', 'cta_url', 'cta2_label', 'cta2_url'),
            'description': 'Usiandike namba za simu hapa. Tumia njia fupi — zinafuata namba '
                           'zilizowekwa kwenye Render:<br>'
                           '<code>whatsapp:bot</code> → JamiiBot ya demo &nbsp;·&nbsp; '
                           '<code>whatsapp:team</code> → WhatsApp ya timu &nbsp;·&nbsp; '
                           '<code>tel:team</code> → kupiga simu timu',
        }),
        ('Display', {'fields': ('is_active', 'order')}),
    )


@admin.register(PortfolioItem)
class PortfolioItemAdmin(PreviewMixin, admin.ModelAdmin):
    form = PortfolioItemForm
    list_display = ('preview', 'title', 'client', 'category', 'year', 'order', 'is_featured')
    list_editable = ('order', 'is_featured')
    list_display_links = ('title',)
    list_filter = ('category', 'is_featured')
    search_fields = ('title', 'client', 'summary')
    fieldsets = (
        ('Photo', {
            'fields': ('image',),
            'description': 'A screenshot of the live site works best — '
                           'at least 1600&times;1200, landscape.',
        }),
        ('Details', {'fields': ('title', 'client', 'category', 'summary', 'live_url', 'year')}),
        ('Display', {'fields': ('is_featured', 'order')}),
    )


@admin.register(Testimonial)
class TestimonialAdmin(PreviewMixin, admin.ModelAdmin):
    form = TestimonialForm
    list_display = ('preview', 'name', 'role', 'rating', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    list_display_links = ('name',)
    fieldsets = (
        ('Photo', {
            'fields': ('image',),
            'description': 'Square headshot, at least 320&times;320. '
                           'Leave empty to show the person&rsquo;s initials instead.',
        }),
        ('Quote', {'fields': ('quote', 'name', 'role', 'rating')}),
        ('Display', {'fields': ('is_active', 'order')}),
    )