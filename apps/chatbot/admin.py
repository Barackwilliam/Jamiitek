"""
JamiiTek ChatBot SaaS — Django Admin
Full admin panel registration with all models.
"""
from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    SubscriptionPlan, ChatbotClient, BotConfig, BotService, BotFAQ,
    BotSubscription, SubscriptionPayment, Conversation, Message, BotAnalytics
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display  = ['name', 'price_tzs', 'msg_limit', 'max_services', 'is_active', 'sort_order']
    list_editable = ['is_active', 'sort_order', 'price_tzs']
    prepopulated_fields = {'slug': ('name',)}


class BotConfigInline(admin.TabularInline):
    model  = BotConfig
    fields = ['bot_name', 'status', 'is_active', 'whatsapp_number']
    extra  = 0
    readonly_fields = ['created_at']


@admin.register(ChatbotClient)
class ChatbotClientAdmin(admin.ModelAdmin):
    list_display  = ['business_name', 'full_name', 'email', 'phone', 'is_active', 'is_verified', 'created_at']
    list_filter   = ['is_active', 'is_verified', 'country']
    search_fields = ['business_name', 'full_name', 'email', 'phone']
    readonly_fields = ['api_key', 'created_at']
    inlines       = [BotConfigInline]
    fieldsets = [
        ('Identity', {'fields': ['user', 'full_name', 'business_name', 'email', 'phone']}),
        ('Location', {'fields': ['country', 'city']}),
        ('Status',   {'fields': ['is_active', 'is_verified', 'notes']}),
        ('API',      {'fields': ['api_key'], 'classes': ['collapse']}),
    ]


class BotServiceInline(admin.TabularInline):
    model  = BotService
    fields = ['name', 'description', 'price', 'is_active', 'sort_order']
    extra  = 1


class BotFAQInline(admin.TabularInline):
    model  = BotFAQ
    fields = ['question', 'answer', 'is_active', 'sort_order']
    extra  = 1


@admin.register(BotConfig)
class BotConfigAdmin(admin.ModelAdmin):
    list_display   = ['bot_name', 'business_name', 'client_link', 'status_badge', 'whatsapp_number', 'conversations_count', 'created_at']
    list_filter    = ['status', 'is_active', 'language', 'tone']
    search_fields  = ['bot_name', 'business_name', 'client__business_name', 'whatsapp_number']
    readonly_fields = ['id', 'webhook_verify_token', 'deployed_at', 'created_at', 'updated_at', 'webhook_url_display']
    inlines        = [BotServiceInline, BotFAQInline]
    list_editable  = []
    # Kasi: client kwa JOIN, idadi ya mazungumzo kwa annotate (si swali kwa kila mstari)
    list_select_related = ('client',)
    autocomplete_fields = ('client',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_conv=Count('conversations'))

    fieldsets = [
        ('Identity',      {'fields': ['id', 'client', 'bot_name', 'business_name', 'description']}),
        ('Personality',   {'fields': ['language', 'tone', 'ai_model', 'ai_temperature', 'max_context_msgs']}),
        ('Messages',      {'fields': ['greeting_msg', 'fallback_msg', 'human_handoff_msg']}),
        ('Collection',    {'fields': ['collect_name', 'collect_phone']}),
        ('WhatsApp',      {'fields': ['whatsapp_number', 'whatsapp_phone_id', 'whatsapp_token', 'webhook_verify_token', 'webhook_url_display']}),
        ('Status',        {'fields': ['status', 'is_active', 'deployed_at']}),
        ('Admin',         {'fields': ['admin_suspended_reason', 'admin_notes'], 'classes': ['collapse']}),
        ('Timestamps',    {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}),
    ]

    def client_link(self, obj):
        return format_html('<a href="/admin/chatbot/chatbotclient/{}/change/">{}</a>', obj.client.id, obj.client.business_name)
    client_link.short_description = 'Client'

    def status_badge(self, obj):
        colors = {'active': '#00dc82', 'draft': '#3b82f6', 'suspended': '#ef4444', 'cancelled': '#6b7280'}
        color  = colors.get(obj.status, '#6b7280')
        return format_html('<span style="background:{};color:#fff;padding:2px 8px;border-radius:5px;font-size:11px">{}</span>', color, obj.status)
    status_badge.short_description = 'Status'

    def conversations_count(self, obj):
        return obj._conv if hasattr(obj, '_conv') else obj.conversations.count()
    conversations_count.short_description = 'Convs'

    def webhook_url_display(self, obj):
        if obj.pk:
            return format_html('<code style="font-size:12px">{}</code>', obj.webhook_url)
        return "Save first to generate URL"
    webhook_url_display.short_description = 'Webhook URL'


@admin.register(BotSubscription)
class BotSubscriptionAdmin(admin.ModelAdmin):
    list_display  = ['bot_name', 'plan', 'status', 'end_date', 'days_remaining', 'messages_used', 'usage_percent']
    list_filter   = ['status', 'plan', 'auto_renew']
    search_fields = ['bot__bot_name', 'bot__client__business_name']
    list_editable = ['status', 'end_date']
    list_select_related = ('bot', 'plan')

    def bot_name(self, obj): return str(obj.bot)
    bot_name.short_description = 'Bot'

    def days_remaining(self, obj):
        d = obj.days_remaining
        if d is None: return '—'
        color = '#ef4444' if d <= 3 else '#f59e0b' if d <= 7 else '#00dc82'
        return format_html('<span style="color:{};font-weight:700">{}</span>', color, d)
    days_remaining.short_description = 'Days Left'

    def usage_percent(self, obj):
        pct = obj.usage_percent
        color = '#ef4444' if pct >= 90 else '#f59e0b' if pct >= 70 else '#00dc82'
        return format_html('<div style="background:#1a1a2e;border-radius:4px;height:8px;width:80px;overflow:hidden"><div style="background:{};height:100%;width:{}%"></div></div>{}%', color, pct, pct)
    usage_percent.short_description = 'Usage'


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display  = ['subscription_bot', 'amount_display', 'months_covered', 'payment_method', 'status_badge', 'payment_date', 'verified_by']
    list_filter   = ['status', 'payment_method', 'payment_date']
    search_fields = ['subscription__bot__bot_name', 'transaction_ref', 'subscription__bot__client__business_name']
    list_editable = []
    readonly_fields = ['payment_date', 'verified_at']
    list_select_related = ('subscription__bot', 'verified_by')
    raw_id_fields = ('subscription', 'verified_by')

    def subscription_bot(self, obj): return obj.subscription.bot.bot_name
    subscription_bot.short_description = 'Bot'

    def amount_display(self, obj):
        # format_html inaescape hoja kuwa maandishi kwanza, kwa hiyo '{:,}' ilivunja
        # ukurasa wote (500). Tunapanga namba kwanza.
        return format_html('<strong style="color:#00dc82">TZS {}</strong>', f'{int(obj.amount or 0):,}')
    amount_display.short_description = 'Amount'

    def status_badge(self, obj):
        colors = {'pending': '#f59e0b', 'verified': '#00dc82', 'rejected': '#ef4444'}
        color = colors.get(obj.status, '#6b7280')
        return format_html('<span style="background:{};color:#fff;padding:2px 8px;border-radius:5px;font-size:11px">{}</span>', color, obj.status)
    status_badge.short_description = 'Status'

    actions = ['verify_payments', 'reject_payments']

    def verify_payments(self, request, queryset):
        # Awali tarehe iliongezwa kuanzia end_date HATA IKIWA IMEPITA: mteja
        # aliyechelewa siku 20 akalipia mwezi, alipata siku 10 tu.
        from .billing import verify_payment
        count = sum(1 for pay in list(queryset.filter(status='pending'))
                    if verify_payment(pay, user=request.user))
        self.message_user(request, f"{count} malipo yamethibitishwa.")
    verify_payments.short_description = "✓ Thibitisha malipo yaliyochaguliwa"

    def reject_payments(self, request, queryset):
        count = queryset.filter(status='pending').update(status='rejected')
        self.message_user(request, f"{count} malipo yamekataliwa.")
    reject_payments.short_description = "✗ Kataa malipo yaliyochaguliwa"


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display  = ['customer_phone', 'customer_name', 'bot_name', 'message_count', 'is_human_handoff', 'started_at', 'last_message_at']
    list_filter   = ['is_human_handoff', 'is_active', 'bot']
    search_fields = ['customer_phone', 'customer_name', 'bot__bot_name']
    readonly_fields = ['id', 'started_at', 'last_message_at']
    list_select_related = ('bot',)
    raw_id_fields = ('bot',)

    def bot_name(self, obj): return obj.bot.bot_name
    bot_name.short_description = 'Bot'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display  = ['short_content', 'role', 'conversation_phone', 'tokens_used', 'latency_ms', 'created_at']
    list_filter   = ['role', 'created_at']
    search_fields = ['content', 'conversation__customer_phone']
    readonly_fields = ['id', 'created_at']
    # Jedwali kubwa: JOIN ya mazungumzo, hakuna dropdown ya mazungumzo yote,
    # na hakuna COUNT(*) ya jedwali zima kila ukurasa
    list_select_related = ('conversation',)
    raw_id_fields = ('conversation',)
    show_full_result_count = False

    def short_content(self, obj): return obj.content[:60] + '...' if len(obj.content) > 60 else obj.content
    short_content.short_description = 'Content'

    def conversation_phone(self, obj): return obj.conversation.customer_phone
    conversation_phone.short_description = 'Customer'


@admin.register(BotAnalytics)
class BotAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['bot', 'date', 'messages_in', 'messages_out', 'unique_users', 'tokens_used', 'errors']
    list_filter  = ['date', 'bot']
    ordering     = ['-date']
