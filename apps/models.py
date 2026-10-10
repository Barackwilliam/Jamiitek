# app/models.py

import re

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from .receipt_models import DevelopmentReceipt  

from .integration_models import ResolverMixin
import secrets
from .site_content import HeroSlide, PortfolioItem, Testimonial  # noqa: F401
from .pesapal_models import PesapalTransaction  # noqa: F401
from .security_models import StaffTwoFactor  # noqa: F401


# ============================================================
# SERVICES
# ============================================================

# Ikoni za kadi za huduma (njia za SVG, viewBox 0 0 24 24, fill=currentColor).
# `icon_path` na `home_url` zilipotea kwenye model — template ziliziomba,
# zikapata kitu kitupu: vibandiko vya rangi bila ikoni, na kila "Learn more"
# ikielekeza anwani tupu.
SERVICE_ICONS = {
    'code':    'M8.7 16.6 4.1 12l4.6-4.6L7.3 6 1.3 12l6 6zm6.6 0 4.6-4.6-4.6-4.6L16.7 6l6 6-6 6z',
    'bot':     'M12 2a2 2 0 0 1 1 3.7V7h4a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-7a3 3 0 0 1 3-3h4V5.7A2 2 0 0 1 12 2zM9 11.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm6 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zM1 12h2v4H1zm20 0h2v4h-2z',
    'server':  'M4 3h16a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm0 10h16a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1zm3-8a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm0 10a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z',
    'globe':   'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm6.9 6h-2.9a15.6 15.6 0 0 0-1.4-3.6A8 8 0 0 1 18.9 8zM12 4c.8 1.2 1.5 2.5 1.9 4h-3.8c.4-1.5 1.1-2.8 1.9-4zM4.3 14a8 8 0 0 1 0-4h3.4a16.5 16.5 0 0 0 0 4zm.8 2H8a15.6 15.6 0 0 0 1.4 3.6A8 8 0 0 1 5.1 16zM8 8H5.1a8 8 0 0 1 4.3-3.6A15.6 15.6 0 0 0 8 8zm4 12c-.8-1.2-1.5-2.5-1.9-4h3.8c-.4 1.5-1.1 2.8-1.9 4zm2.3-6H9.7a14.7 14.7 0 0 1 0-4h4.6a14.7 14.7 0 0 1 0 4zm.3 5.6A15.6 15.6 0 0 0 16 16h2.9a8 8 0 0 1-4.3 3.6zM16.3 14a16.5 16.5 0 0 0 0-4h3.4a8 8 0 0 1 0 4z',
    'mobile':  'M7 1h10a2 2 0 0 1 2 2v18a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2zm0 4v14h10V5zm5 15.5a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
    'design':  'M12 2a10 10 0 0 0 0 20c1 0 1.7-.8 1.7-1.7 0-.4-.2-.8-.4-1.1a1.7 1.7 0 0 1 1.3-2.9H17a5 5 0 0 0 5-5C22 6.5 17.5 2 12 2zM6.5 12a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3-4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3 4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z',
    'builder': 'M3 3h8v8H3zm10 0h8v5h-8zM3 13h8v8H3zm10-3h8v11h-8z',
    'layout':  'M3 3h18v5H3zm0 7h7v11H3zm9 0h9v11h-9z',
    # Ikoni za ziada — zinachaguliwa kiotomatiki kutoka jina la huduma (Service.art)
    'network': 'M12 2a3 3 0 0 1 1 5.8V11h6a2 2 0 0 1 2 2v3.2a3 3 0 1 1-2 0V13h-6v3.2a3 3 0 1 1-2 0V13H5v3.2a3 3 0 1 1-2 0V13a2 2 0 0 1 2-2h6V7.8A3 3 0 0 1 12 2z',
    'cctv':    'M3 6l13-3 2 6-13 3zm15.5 2.5 3 1-1 4-3-1zM6 12l1.5 4H4v3H2v-8h2v3h1.2l-.9-2.3z',
    'graphic': 'M14.6 2.6a2 2 0 0 1 2.8 0l4 4a2 2 0 0 1 0 2.8l-1.7 1.7-6.8-6.8zM11.5 5.7l6.8 6.8-8.6 8.6a2 2 0 0 1-1 .6l-5.2 1.2 1.2-5.2a2 2 0 0 1 .6-1z',
    'support': 'M12 2a9 9 0 0 0-9 9v5a3 3 0 0 0 3 3h2v-7H5v-1a7 7 0 0 1 14 0v1h-3v7h3v1h-6v2h6a2 2 0 0 0 2-2v-9a9 9 0 0 0-9-9z',
    'growth':  'M3 20h18v2H3zM4 16l5-5 4 4 7-7v4h2V4h-8v2h4l-5 5-4-4-6.4 6.4z',
    'dashboard': 'M3 3h8v10H3zm10 0h8v6h-8zM3 15h8v6H3zm10-4h8v10h-8z',
}

# Mchoro wa huduma kwenye /service/ huchaguliwa kwa maneno ya jina lake
# (huduma nyingi kwenye admin zina ikoni ya default 'code', hivyo zote
# zilikuwa zikionyesha code editor). Mpangilio una maana: la kwanza linashinda.
SERVICE_ART_KEYWORDS = [
    ('bot',       ('chatbot', 'bot', 'whatsapp', 'ai assistant')),
    ('network',   ('network', 'lan', 'wlan', 'wifi', 'wi-fi', 'cabling', 'router', 'internet', 'mtandao')),
    ('cctv',      ('cctv', 'camera', 'surveillance', 'security system', 'alarm', 'kamera')),
    ('graphic',   ('graphic', 'logo', 'brand', 'poster', 'flyer', 'print', 'michoro')),
    ('design',    ('ui/ux', 'ux', 'ui design', 'user interface')),
    ('server',    ('hosting', 'server', 'cloud', 'backup', 'vps')),
    ('globe',     ('domain', 'dns')),
    ('mobile',    ('mobile', 'android', 'ios', 'app development', 'apps')),
    ('builder',   ('builder',)),
    ('layout',    ('template',)),
    ('growth',    ('seo', 'marketing', 'social media', 'ads', 'advert', 'masoko')),
    ('dashboard', ('system', 'software', 'erp', 'pos', 'management', 'database', 'school', 'mfumo')),
    ('support',   ('support', 'maintenance', 'repair', 'helpdesk', 'training', 'consult', 'it service')),
    ('code',      ('website', 'web development', 'web design', 'e-commerce', 'ecommerce', 'tovuti')),
]


def _art_match(text):
    for kind, words in SERVICE_ART_KEYWORDS:
        # \b ili 'lan' isiguse 'plan', 'pos' isiguse 'post', n.k.
        if any(re.search(r'\b' + re.escape(w) + r's?\b', text) for w in words):
            return kind
    return None


def service_art_for(name, icon='code', description=''):
    kind = _art_match((name or '').lower())
    if kind:
        return kind
    if icon and icon != 'code':
        return icon
    return _art_match((description or '').lower()[:300]) or 'code'


class Service(models.Model):
    ICON_CHOICES = [
        ('code', 'Code — websites'),
        ('bot', 'Robot — chatbot'),
        ('server', 'Server — hosting'),
        ('globe', 'Globe — domains'),
        ('mobile', 'Phone — mobile apps'),
        ('design', 'Palette — design'),
        ('builder', 'Builder — site builder'),
        ('layout', 'Layout — templates'),
    ]

    service_type = models.CharField('Name', max_length=255, db_column='Service_type')
    image = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(help_text='Full description (shown on the /service/ page).')
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Homepage "What we build" card ─────────────────────
    summary = models.CharField(
        max_length=200, blank=True,
        help_text='One or two short sentences for the homepage card. Leave empty to use the start of the description.')
    icon = models.CharField(max_length=20, choices=ICON_CHOICES, default='code')
    accent = models.CharField(max_length=7, default='#2E7BF6',
                              help_text='Badge colour as a hex code, e.g. #2E7BF6')
    link_label = models.CharField(max_length=40, default='Learn more')
    link_url = models.CharField(
        max_length=300, blank=True,
        help_text='Where the card goes, e.g. /bot/ or #hosting. Empty = the /service/ page.')
    order = models.IntegerField(default=0, help_text='Smaller numbers appear first.')
    show_on_home = models.BooleanField(
        default=False,
        help_text='Show this service in the homepage "What we build" section.')

    @property
    def art(self):
        """Aina ya mchoro hai kwenye /service/ (angalia service_art_for)."""
        if not hasattr(self, '_art'):
            self._art = service_art_for(self.service_type, self.icon, self.description)
        return self._art

    @property
    def icon_path(self):
        # Ikoni iliyochaguliwa kwenye admin inashinda; 'code' (default) inafuata aina ya huduma
        key = self.icon if self.icon and self.icon != 'code' else self.art
        return SERVICE_ICONS.get(key, SERVICE_ICONS['code'])

    @property
    def home_url(self):
        """Kitufe cha kadi: link_url ikiwekwa kwenye admin, vinginevyo ukurasa wa huduma."""
        return (self.link_url or '').strip() or '/service/'

    def __str__(self):
        return self.service_type

    # Open Graph image (Facebook / WhatsApp preview)
    def get_og_image_url(self):
        if self.image:
            return self.image  # URL kamili ya Supabase
        return ""

    # Optimized image for normal website usage
    def get_image_url(self):
        if self.image:
            return self.image  # URL kamili ya Supabase
        return ""


# ============================================================
# FAQ
# ============================================================

class Question(models.Model):
    question = models.CharField(max_length=500)
    answer = models.TextField()

    def __str__(self):
        return self.question


# ============================================================
# TEAM MEMBERS
# ============================================================

class Team(models.Model):
    full_name = models.CharField(max_length=255)
    image = models.CharField(max_length=255, blank=True, null=True)
    position = models.CharField(max_length=255)

    facebook_link = models.URLField(max_length=300, blank=True, null=True)
    twitter_link = models.URLField(max_length=300, blank=True, null=True)
    instagram_link = models.URLField(max_length=300, blank=True, null=True)
    linkedin_link = models.URLField(max_length=300, blank=True, null=True)

    def __str__(self):
        return self.full_name

    # Open Graph preview
    def get_og_image_url(self):
        if self.image:
            return self.image  # URL kamili ya Supabase
        return ""

    # Optimized image
    def get_image_url(self):
        if self.image:
            return self.image  # URL kamili ya Supabase
        return ""


# ============================================================
# CONTACT MESSAGES
# ============================================================

class Contact(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    subject = models.CharField(max_length=500)
    message = models.TextField()

    def __str__(self):
        return f"{self.full_name} - {self.subject}"


# ============================================================
# WEBSITE PROJECT SYSTEM
# ============================================================

class WebsiteType(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name


class Client(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)

    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.name


class ProjectProposal(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    website_type = models.ForeignKey(WebsiteType, on_delete=models.CASCADE)

    requirements = models.JSONField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    pdf_file = models.URLField(blank=True)

    def __str__(self):
        return f"{self.client.name} - {self.website_type.name}"


# ============================================================
# WEBSITE MANAGEMENT SYSTEM
# ============================================================

class ManagedWebsite(ResolverMixin, models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("suspended", "Suspended"),
        ("maintenance", "Maintenance"),
        ("terminated", "Terminated"),
    ]

    SITE_TYPE_CHOICES = [
        ("django", "Django Website"),
        ("static", "Static HTML/CSS"),
        ("wordpress", "WordPress"),
        ("other", "Other"),
    ]

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="managed_websites"
    )

    name = models.CharField(max_length=200)
    url = models.URLField()

    site_type = models.CharField(
        max_length=20,
        choices=SITE_TYPE_CHOICES,
        default="django"
    )

    api_key = models.CharField(
        max_length=64,
        unique=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    suspension_message = models.TextField(
        blank=True,
        default="This service has been temporarily suspended. Please contact the administrator."
    )

    suspension_reason = models.TextField(blank=True)

    # Hosting Billing
    hosting_start_date = models.DateField()
    hosting_end_date = models.DateField()

    monthly_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # ── PUNGUZO KWA MALIPO YA MUDA MREFU ──
    # Mteja akilipa miezi mingi kwa mkupuo, anapata punguzo.
    # Hii inapunguza usumbufu wa malipo ya kila mwezi.
    discount_3m = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
        verbose_name='3-month discount (%)',
        help_text='Percent off when paying for 3 months at once')
    discount_6m = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        verbose_name='6-month discount (%)',
        help_text='Percent off when paying for 6 months at once')
    discount_12m = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        verbose_name='12-month discount (%)',
        help_text='Percent off when paying for 12 months at once')

    # Notification Settings
    auto_suspend_on_expiry = models.BooleanField(default=True)
    send_expiry_warnings = models.BooleanField(default=True)

    # ── Kumbukumbu ya barua zilizotumwa ──────────────────────────
    # Awali onyo lilitumwa kwa usawa kamili: `raw_days == 7`. Kazi ya
    # siku moja ikikosa kukimbia (server chini, deploy), siku inayofuata
    # raw_days = 6 na onyo la siku 7 halikutumwa KAMWE. Sasa tunatumia
    # madirisha (<=) pamoja na kumbukumbu hii, ili onyo lisirudiwe.
    #
    # 7 = onyo la kirafiki, 3 = onyo la haraka, 1 = onyo la mwisho.
    last_warning_stage = models.PositiveSmallIntegerField(
        null=True, blank=True, editable=False,
        help_text='Hatua ya mwisho ya onyo iliyotumwa (7, 3 au 1).')
    last_warning_at = models.DateTimeField(null=True, blank=True, editable=False)

    # Inazuia barua ya kusitishwa kutumwa mara mbili kwa kusitishwa
    # kumoja. Inafutwa website inaporejeshwa.
    suspension_notified_at = models.DateTimeField(null=True, blank=True, editable=False)

    warning_days_before = models.IntegerField(default=7)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def days_until_expiry(self):
        delta = (self.hosting_end_date - timezone.now().date()).days
        return max(delta, 0)

    @property
    def is_overdue(self):
        return self.hosting_end_date <= timezone.now().date()

    @property
    def expiry_status(self):
        d = (self.hosting_end_date - timezone.now().date()).days
        if d <= 0:  return 'expired'
        if d <= 3:  return 'critical'
        if d <= 7:  return 'warning'
        return 'ok'

    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments.all())

    # ── BEI ZA MUDA (1 / 3 / 6 / 12 miezi) ──

    def discount_for(self, months):
        """Punguzo (%) kwa idadi ya miezi."""
        return {3: self.discount_3m, 6: self.discount_6m,
                12: self.discount_12m}.get(int(months), 0) or 0

    def price_for(self, months):
        """
        Bei ya jumla kwa idadi ya miezi, punguzo likishawekwa.
        Rudisha dict: base, discount_pct, discount_amount, total, per_month, saving.
        """
        months = int(months)
        monthly = float(self.monthly_cost or 0)
        base = monthly * months
        pct = float(self.discount_for(months))
        discount = base * pct / 100
        total = base - discount
        return {
            'months': months,
            'base': base,
            'discount_pct': pct,
            'discount_amount': discount,
            'total': total,
            'per_month': (total / months) if months else 0,
            'saving': discount,
        }

    @property
    def billing_options(self):
        """Chaguo zote za malipo — kwa ajili ya portal na management form."""
        labels = {
            1: ('1 Month', 'Mwezi 1'),
            3: ('3 Months', 'Miezi 3'),
            6: ('6 Months', 'Miezi 6'),
            12: ('12 Months', 'Mwaka 1'),
        }
        options = []
        for m in (1, 3, 6, 12):
            opt = self.price_for(m)
            opt['label_en'], opt['label_sw'] = labels[m]
            opt['is_best'] = (m == 12)
            options.append(opt)
        return options

    def __str__(self):
        return f"{self.name} ({self.client.name})"

    class Meta:
        verbose_name = "Managed Website"
        verbose_name_plural = "Managed Websites"
        ordering = ["-created_at"]


# ============================================================
# HOSTING PAYMENTS
# ============================================================

class HostingPayment(models.Model):

    website = models.ForeignKey(
        ManagedWebsite,
        on_delete=models.CASCADE,
        related_name="payments"
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    payment_date = models.DateField()

    months_covered = models.IntegerField(default=1)

    payment_method = models.CharField(
        max_length=50,
        blank=True
    )

    transaction_ref = models.CharField(
        max_length=100,
        blank=True
    )

    notes = models.TextField(blank=True)

    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.website.name} - TZS {self.amount} ({self.payment_date})"

    class Meta:
        verbose_name = "Hosting Payment"
        verbose_name_plural = "Hosting Payments"
        ordering = ["-payment_date"]


# ============================================================
# WEBSITE FEATURES
# ============================================================

class WebsiteFeature(models.Model):

    website = models.ForeignKey(
        ManagedWebsite,
        on_delete=models.CASCADE,
        related_name="features"
    )

    feature_key = models.CharField(max_length=100)
    feature_name = models.CharField(max_length=200)

    is_enabled = models.BooleanField(default=True)

    disabled_reason = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        status = "Enabled" if self.is_enabled else "Disabled"
        return f"{status} - {self.website.name} → {self.feature_name}"

    class Meta:
        unique_together = ["website", "feature_key"]
        verbose_name = "Website Feature"
        verbose_name_plural = "Website Features"


# ============================================================
# SCHEDULED ACTIONS
# ============================================================

class ScheduledAction(models.Model):

    ACTION_TYPES = [
        ("suspend", "Suspend Website"),
        ("restore", "Restore Website"),
        ("maintenance", "Enable Maintenance Mode"),
        ("send_email", "Send Email"),
        ("disable_feature", "Disable Feature"),
        ("enable_feature", "Enable Feature"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    website = models.ForeignKey(
        ManagedWebsite,
        on_delete=models.CASCADE,
        related_name="scheduled_actions"
    )

    action_type = models.CharField(
        max_length=30,
        choices=ACTION_TYPES
    )

    scheduled_at = models.DateTimeField()

    action_data = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    executed_at = models.DateTimeField(null=True, blank=True)

    result_message = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action_type} → {self.website.name} @ {self.scheduled_at}"

    class Meta:
        verbose_name = "Scheduled Action"
        verbose_name_plural = "Scheduled Actions"
        ordering = ["scheduled_at"]


# ============================================================
# CLIENT NOTIFICATIONS
# ============================================================

class ClientNotification(models.Model):

    NOTIFICATION_TYPES = [
        ("payment_reminder", "Payment Reminder"),
        ("payment_received", "Payment Received"),
        ("suspension_warning", "Suspension Warning"),
        ("suspension", "Website Suspended"),
        ("restoration", "Website Restored"),
        ("maintenance", "Maintenance Notice"),
        ("update", "General Update"),
        ("invoice", "Invoice"),
        ("support", "Support Request"),
        ("general", "General Message"),
        ("custom", "Custom Message"),
    ]

    website = models.ForeignKey(
        ManagedWebsite,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True
    )

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="notifications"
    )

    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPES,
        default="custom"
    )

    subject = models.CharField(max_length=200)

    message = models.TextField()

    sent_at = models.DateTimeField(auto_now_add=True)

    sent_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    email_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.subject} → {self.client.name} ({self.sent_at.date()})"

    class Meta:
        verbose_name = "Client Notification"
        verbose_name_plural = "Client Notifications"
        ordering = ["-sent_at"]

# ============================================================
# DOMAIN RENEWAL SYSTEM
# ============================================================

class DomainRecord(models.Model):

    STATUS_CHOICES = [
        ('active',          'Active'),
        ('expiring_soon',   'Expiring Soon'),
        ('expired',         'Expired'),
        ('pending_renewal', 'Pending Renewal'),
        ('transferred',     'Transferred Out'),
    ]

    REGISTRAR_CHOICES = [
        ('zicta',      'ZICTA (.co.tz / .tz)'),
        ('godaddy',    'GoDaddy'),
        ('cloudflare', 'Cloudflare'),
        ('namecheap',  'Namecheap'),
        ('other',      'Other'),
    ]

    website     = models.ForeignKey(ManagedWebsite, on_delete=models.CASCADE, related_name='domains')
    domain_name = models.CharField(max_length=253)
    registrar   = models.CharField(max_length=30, choices=REGISTRAR_CHOICES, default='other')
    registrar_other = models.CharField(max_length=100, blank=True)

    registration_date = models.DateField()
    expiry_date       = models.DateField()

    renewal_cost             = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    auto_renew               = models.BooleanField(default=True)
    send_renewal_warnings    = models.BooleanField(default=True)
    warning_days_before      = models.IntegerField(default=30)

    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    dns_nameservers = models.TextField(blank=True, help_text='One per line')
    notes           = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def days_until_expiry(self):
        delta = (self.expiry_date - timezone.now().date()).days
        return max(delta, 0)

    @property
    def is_expired(self):
        return self.expiry_date < timezone.now().date()

    def __str__(self):
        return f'{self.domain_name} (expires {self.expiry_date})'

    class Meta:
        verbose_name = 'Domain Record'
        verbose_name_plural = 'Domain Records'
        ordering = ['expiry_date']


class DomainRenewalPayment(models.Model):
    domain          = models.ForeignKey(DomainRecord, on_delete=models.CASCADE, related_name='renewal_payments')
    amount          = models.DecimalField(max_digits=10, decimal_places=2)
    paid_date       = models.DateField()
    renewed_until   = models.DateField()
    payment_method  = models.CharField(max_length=50, blank=True)
    transaction_ref = models.CharField(max_length=100, blank=True)
    notes           = models.TextField(blank=True)
    recorded_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.domain.domain_name} renewed → {self.renewed_until}'

    class Meta:
        ordering = ['-paid_date']


# ============================================================
# EMAIL HOSTING SYSTEM
# ============================================================

class EmailHostingPlan(models.Model):

    STATUS_CHOICES = [
        ('active',    'Active'),
        ('suspended', 'Suspended'),
        ('expired',   'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    client   = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='email_plans')
    website  = models.ForeignKey(ManagedWebsite, on_delete=models.CASCADE,
                                 related_name='email_plans', null=True, blank=True)

    plan_name      = models.CharField(max_length=200)
    email_domain   = models.CharField(max_length=253, help_text='e.g. yourcompany.co.tz')
    accounts_count = models.PositiveIntegerField(default=1)
    storage_gb     = models.DecimalField(max_digits=6, decimal_places=1, default=5.0)

    monthly_cost   = models.DecimalField(max_digits=10, decimal_places=2)
    start_date     = models.DateField()
    end_date       = models.DateField()

    status             = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    suspension_message = models.TextField(
        blank=True,
        default='Your email hosting has been suspended. Please contact JamiiTek.')

    auto_suspend_on_expiry = models.BooleanField(default=True)
    send_expiry_warnings   = models.BooleanField(default=True)
    warning_days_before    = models.IntegerField(default=7)

    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def days_until_expiry(self):
        delta = (self.end_date - timezone.now().date()).days
        return max(delta, 0)

    @property
    def is_overdue(self):
        return self.end_date <= timezone.now().date()

    @property
    def expiry_status(self):
        d = (self.end_date - timezone.now().date()).days
        if d <= 0:  return 'expired'
        if d <= 3:  return 'critical'
        if d <= 7:  return 'warning'
        return 'ok'

    @property
    def total_paid(self):
        return sum(p.amount for p in self.email_payments.all())

    def __str__(self):
        return f'{self.plan_name} ({self.client.name})'

    class Meta:
        verbose_name = 'Email Hosting Plan'
        verbose_name_plural = 'Email Hosting Plans'
        ordering = ['-created_at']


class EmailHostingPayment(models.Model):
    plan            = models.ForeignKey(EmailHostingPlan, on_delete=models.CASCADE,
                                        related_name='email_payments')
    amount          = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date    = models.DateField()
    months_covered  = models.IntegerField(default=1)
    payment_method  = models.CharField(max_length=50, blank=True)
    transaction_ref = models.CharField(max_length=100, blank=True)
    notes           = models.TextField(blank=True)
    recorded_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.plan.plan_name} – TZS {self.amount} ({self.payment_date})'

    class Meta:
        ordering = ['-payment_date']


# ============================================================
# HOSTING CONFIGURATION (Advanced Panel)
# ============================================================

class HostingConfiguration(models.Model):

    SERVER_CHOICES = [
        ('shared',    'Shared Hosting'),
        ('vps',       'VPS Server'),
        ('dedicated', 'Dedicated Server'),
        ('cloud',     'Cloud Hosting'),
    ]

    OS_CHOICES = [
        ('ubuntu_22', 'Ubuntu 22.04 LTS'),
        ('ubuntu_20', 'Ubuntu 20.04 LTS'),
        ('debian_12', 'Debian 12'),
        ('centos_8',  'CentOS Stream 8'),
    ]

    STACK_CHOICES = [
        ('django',    'Python / Django'),
        ('php_apache','PHP / Apache'),
        ('php_nginx', 'PHP / Nginx'),
        ('node',      'Node.js'),
        ('static',    'Static / Nginx'),
    ]

    SSL_CHOICES = [
        ('lets_encrypt', "Let's Encrypt (Free)"),
        ('comodo',       'Comodo SSL'),
        ('wildcard',     'Wildcard SSL'),
        ('none',         'No SSL'),
    ]

    website = models.OneToOneField(
        ManagedWebsite, on_delete=models.CASCADE, related_name='hosting_config')

    # Server Info
    server_type     = models.CharField(max_length=20, choices=SERVER_CHOICES, default='shared')
    server_os       = models.CharField(max_length=20, choices=OS_CHOICES, default='ubuntu_22')
    stack           = models.CharField(max_length=20, choices=STACK_CHOICES, default='django')
    server_location = models.CharField(max_length=100, blank=True, default='',
        help_text='Acha wazi. Usidai data iko Tanzania kama iko nje — PDP Act 2022.')
    ip_address      = models.GenericIPAddressField(null=True, blank=True,
        help_text='Acha wazi — inatoka kwa provider ikiwa integration imeunganishwa.')
    server_hostname = models.CharField(max_length=200, blank=True, default='')

    # Resources
    disk_total_gb   = models.DecimalField(max_digits=6, decimal_places=1, default=10.0)
    disk_used_gb    = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    bandwidth_gb    = models.DecimalField(max_digits=8, decimal_places=1, default=100.0)
    bandwidth_used  = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    ram_mb          = models.IntegerField(default=512)
    cpu_cores       = models.IntegerField(default=1)
    monthly_visits  = models.IntegerField(default=0)

    # Stack versions
    python_version  = models.CharField(max_length=20, blank=True, default='3.11.6')
    php_version     = models.CharField(max_length=20, blank=True)
    django_version  = models.CharField(max_length=20, blank=True, default='5.1')
    db_engine       = models.CharField(max_length=50, default='PostgreSQL 15')
    web_server      = models.CharField(max_length=50, default='Nginx 1.24')

    # FTP / SFTP
    ftp_host        = models.CharField(max_length=200, blank=True, default='')
    ftp_username    = models.CharField(max_length=100, blank=True)
    ftp_port        = models.IntegerField(default=22)

    # Database
    db_host         = models.CharField(max_length=200, blank=True, default='')
    db_name         = models.CharField(max_length=100, blank=True)
    db_username     = models.CharField(max_length=100, blank=True)
    db_port         = models.IntegerField(default=5432)

    # SSL
    ssl_type        = models.CharField(max_length=20, choices=SSL_CHOICES, default='lets_encrypt')
    ssl_issued_date = models.DateField(null=True, blank=True)
    ssl_expiry_date = models.DateField(null=True, blank=True)
    ssl_issuer      = models.CharField(max_length=100, default="Let's Encrypt Authority X3")
    https_redirect  = models.BooleanField(default=True)

    # Features
    auto_backup     = models.BooleanField(default=True)
    backup_frequency= models.CharField(max_length=20, default='Daily')
    last_backup     = models.DateField(null=True, blank=True)
    cdn_enabled     = models.BooleanField(default=False)
    firewall_enabled= models.BooleanField(default=True)
    ddos_protection = models.BooleanField(default=True)

    # Uptime
    uptime_percent  = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Acha wazi — inahesabiwa kutoka snapshots halisi.')
    last_downtime   = models.DateTimeField(null=True, blank=True)

    notes           = models.TextField(blank=True)
    updated_at      = models.DateTimeField(auto_now=True)

    @property
    def disk_percent(self):
        # disk_used_gb inaweza kuwa None tangu defaults za kubuni ziondolewe
        if self.disk_total_gb and self.disk_used_gb is not None:
            return round((float(self.disk_used_gb) / float(self.disk_total_gb)) * 100, 1)
        return 0

    @property
    def bandwidth_percent(self):
        if self.bandwidth_gb and self.bandwidth_used is not None:
            return round((float(self.bandwidth_used) / float(self.bandwidth_gb)) * 100, 1)
        return 0

    @property
    def ssl_days_left(self):
        if self.ssl_expiry_date:
            from django.utils import timezone
            return (self.ssl_expiry_date - timezone.now().date()).days
        return None

    def __str__(self):
        return f'Hosting Config — {self.website.name}'

    class Meta:
        verbose_name = 'Hosting Configuration'
        verbose_name_plural = 'Hosting Configurations'


# ============================================================
# DOMAIN DNS CONFIGURATION
# ============================================================

class DomainDNSRecord(models.Model):

    RECORD_TYPES = [
        ('A',     'A — IPv4 Address'),
        ('AAAA',  'AAAA — IPv6 Address'),
        ('CNAME', 'CNAME — Canonical Name'),
        ('MX',    'MX — Mail Exchange'),
        ('TXT',   'TXT — Text Record'),
        ('NS',    'NS — Name Server'),
        ('SRV',   'SRV — Service Record'),
        ('CAA',   'CAA — Certification Authority'),
    ]

    STATUS_CHOICES = [
        ('active',      'Active'),
        ('propagating', 'Propagating'),
        ('inactive',    'Inactive'),
    ]

    domain  = models.ForeignKey(
        DomainRecord, on_delete=models.CASCADE, related_name='dns_records')

    record_type = models.CharField(max_length=10, choices=RECORD_TYPES)
    name        = models.CharField(max_length=253, help_text='e.g. @ or www or mail')
    value       = models.TextField(help_text='e.g. 197.250.10.1 or target domain')
    ttl         = models.IntegerField(default=3600, help_text='Time to live in seconds')
    priority    = models.IntegerField(default=0, help_text='Used for MX and SRV records')
    status      = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active')
    proxy       = models.BooleanField(default=False, help_text='CDN/Proxy enabled (like Cloudflare)')

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.record_type} {self.name} → {self.value[:40]}'

    class Meta:
        verbose_name = 'DNS Record'
        verbose_name_plural = 'DNS Records'
        ordering = ['record_type', 'name']


# ============================================================
# WEBSITE TEMPLATES MARKETPLACE
# ============================================================

class WebsiteTemplate(models.Model):

    CATEGORY_CHOICES = [
        ('restaurant', '🍽️ Restaurant'),
        ('salon',      '💅 Salon & Beauty'),
        ('hotel',      '🏨 Hotel & Lodging'),
        ('shop',       '🛒 Shop / Duka'),
        ('clinic',     '🏥 Clinic & Healthcare'),
        ('church',     '⛪ Church & Religion'),
        ('school',     '🎓 School & Education'),
        ('portfolio',  '🎨 Portfolio & Personal'),
        ('Tourism',  '🎨 Safari & Travel website'),
        ('Real Estate',  '🎨 Real Estate'),
        ('Technology',  '🎨 Technology'),
        ('admin',  '🎨 Admin & Dashboard'),
        ('Booking',  '🎨 Booking system'),
        ('Real Estate',  '🎨 Real Estate'),
        ('Landing',  '🎨 Landing Page'),
        ('niche',  '🎨 Special Premium niche'),
        ('Media',  '🎨 Media & News'),
        ('other',      '🌐 Other'),
    ]

    BADGE_CHOICES = [
        ('HOT', '🔥 HOT'),
        ('NEW', '✨ NEW'),
        ('PRO', '⭐ PRO'),
        ('',    'No Badge'),
    ]

    name        = models.CharField(max_length=200, verbose_name='Template Name')
    # SEO: anwani yenye jina (/templates/savanna-luxe/) badala ya namba. Inajazwa
    # yenyewe kutoka jina ikiwa tupu.
    slug        = models.SlugField(max_length=220, unique=True, blank=True, null=True,
                                   help_text='Inajazwa yenyewe kutoka jina. Usibadilishe baada ya kuchapishwa (link za Google zingevunjika).')
    category    = models.CharField(max_length=50, choices=CATEGORY_CHOICES, verbose_name='Category')
    description = models.TextField(verbose_name='Description (Short)')
    # SEO (si lazima): ukurasa wa template una maandishi ya kutosha hata bila haya
    seo_title       = models.CharField(max_length=70, blank=True, help_text='Kichwa cha Google (≤60 herufi). Tupu = kinatengenezwa chenyewe.')
    seo_description = models.CharField(max_length=170, blank=True, help_text='Maelezo ya Google (≤155 herufi). Tupu = yanatengenezwa yenyewe.')
    long_description = models.TextField(blank=True, help_text='Maelezo marefu kwenye ukurasa wa template (aya kadhaa). Yanasaidia sana SEO.')
    badge       = models.CharField(max_length=10, choices=BADGE_CHOICES, blank=True, verbose_name='Badge')
    rating      = models.DecimalField(max_digits=2, decimal_places=1, default=4.9, verbose_name='Rating')

    # Pricing
    price_hosted_monthly = models.IntegerField(default=30000, verbose_name='Hosted Monthly Price (TSh)')
    price_source_code    = models.IntegerField(default=150000, verbose_name='Source Code Price (TSh)')

    # The full HTML code of the template — admin anaweka hapa
    preview_html = models.TextField(
        verbose_name='Preview HTML Code',
        help_text='Weka HTML code yote ya template hapa. Itaonekana kwenye preview page automatically.'
    )

    # Card gradient colors
    gradient_start = models.CharField(max_length=20, default='#6c63ff', verbose_name='Card Color Start')
    gradient_end   = models.CharField(max_length=20, default='#ff6584', verbose_name='Card Color End')

    is_active = models.BooleanField(default=True, verbose_name='Show on Website')
    order     = models.IntegerField(default=0, verbose_name='Display Order')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} ({self.get_category_display()})'

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name)[:200] or 'template'
            if base in ('preview', 'c'):  # zinagongana na /templates/preview/ na /templates/c/
                base += '-template'
            slug, n = base, 2
            while WebsiteTemplate.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('template_detail', args=[self.slug]) if self.slug else reverse('template_preview', args=[self.pk])

    def category_plain(self):
        """Jina la jamii bila emoji — kwa vichwa vya Google."""
        import re
        return re.sub(r'^[^A-Za-z0-9]+', '', self.get_category_display()).strip()

    def gradient_css(self):
        return f'linear-gradient(135deg, {self.gradient_start}, {self.gradient_end})'

    def price_hosted_formatted(self):
        return f"{self.price_hosted_monthly:,}"

    def price_source_formatted(self):
        return f"{self.price_source_code:,}"

    class Meta:
        verbose_name = 'Website Template'
        verbose_name_plural = 'Website Templates'
        ordering = ['order', '-created_at']


# ============================================================
# BLOG (SEO + social sharing)
# ============================================================

class BlogCategory(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=90, unique=True)

    class Meta:
        verbose_name_plural = 'Blog categories'

    def __str__(self):
        return self.name


# Alama inayowekwa na AI newsroom mahali ambapo mhariri LAZIMA aandike uchambuzi
# wake. Makala yenye alama hii haiwezi kuchapishwa (BlogPost.clean).
EDITOR_MARKER = '[[EDITOR-INSIGHT]]'


class BlogAuthor(models.Model):
    """Mwandishi/mhariri halisi — jina, wasifu na picha (E-E-A-T kwa Google)."""
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=90, unique=True)
    role = models.CharField(max_length=100, blank=True,
                            help_text='E.g. "Founder & Editor", "Tech Reporter".')
    bio = models.TextField(max_length=1200,
                           help_text='2-4 sentences: experience, what you cover, why readers can trust you.')
    photo = models.URLField(blank=True, help_text='Square photo of the real person (400x400+).')
    user = models.OneToOneField('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='blog_author',
                                help_text='Admin account of this author — their edits are credited automatically.')
    x_url = models.URLField('X / Twitter URL', blank=True)
    linkedin_url = models.URLField('LinkedIn URL', blank=True)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('blog_author', args=[self.slug])

    @property
    def same_as(self):
        return [u for u in (self.x_url, self.linkedin_url, self.website) if u]


class BlogPost(models.Model):
    STATUS = [('draft', 'Draft'), ('published', 'Published')]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True,
                            help_text='URL-friendly version, e.g. how-to-build-website-tanzania')
    category = models.ForeignKey(BlogCategory, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='posts')
    excerpt = models.TextField(max_length=320,
                               help_text='Short summary (shows on blog list + social shares + Google). 150-300 chars ideal.')
    body = models.TextField(help_text='Full article. Supports HTML. Write 800-1500 words for best SEO.')
    cover_image = models.URLField(blank=True,
                                  help_text='Cover image URL (Uploadcare/Cloudinary). 1200x630 ideal for social sharing.')

    # SEO
    meta_title = models.CharField(max_length=70, blank=True,
                                  help_text='Custom <title> (defaults to post title). Keep under 60 chars.')
    meta_description = models.CharField(max_length=170, blank=True,
                                        help_text='Custom meta description (defaults to excerpt). 150-160 chars ideal.')
    focus_keyword = models.CharField(max_length=100, blank=True,
                                     help_text='Main keyword this post targets, e.g. "website builder Tanzania"')

    author_name = models.CharField(max_length=80, default='JamiiTek')
    author = models.ForeignKey(BlogAuthor, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='posts',
                               help_text='Real author shown on the article (with bio). '
                                         'Leave empty to credit yourself automatically.')
    status = models.CharField(max_length=10, choices=STATUS, default='draft')
    is_featured = models.BooleanField(default=False, help_text='Show at top of blog')

    # ── AI newsroom (auto-drafted daily news) ─────────────
    is_news = models.BooleanField(default=False,
                                  help_text='Auto-generated news article (AI newsroom).')
    source_url = models.URLField(max_length=600, blank=True,
                                 help_text='Original news source (for attribution + dedup).')
    source_name = models.CharField(max_length=120, blank=True,
                                   help_text='Original news outlet, e.g. BBC, The Citizen.')

    views = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Auto-set published_at wakati inapo-publish kwa mara ya kwanza
        if self.status == 'published' and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.status == 'published' and EDITOR_MARKER in (self.body or ''):
            raise ValidationError({'body': (
                'Andika uchambuzi wako kwenye sehemu ya "What this means for Tanzanian '
                'businesses" (futa alama ' + EDITOR_MARKER + ') kabla ya kuchapisha.')})

    @property
    def byline(self):
        return self.author.name if self.author_id else (self.author_name or 'JamiiTek')

    @property
    def read_minutes(self):
        # Orodha za blog hazipakii `body` (kasi) — zinaleta `body_len` badala yake.
        n = getattr(self, 'body_len', None)
        if n is not None:
            return max(1, round(n / 6 / 200))     # ~6 herufi kwa neno (pamoja na HTML)
        words = len(self.body.split())
        return max(1, round(words / 200))


class BlogComment(models.Model):
    """Maoni ya wasomaji kwenye makala. Majibu yana ngazi moja (parent)."""
    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name='comments')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='replies')
    name = models.CharField(max_length=60)
    email = models.EmailField(blank=True, help_text='Not shown publicly.')
    body = models.TextField(max_length=2000)
    is_approved = models.BooleanField(default=True,
                                      help_text='Untick to hide this comment from the public page.')
    is_staff_reply = models.BooleanField(default=False,
                                         help_text='Written by the JamiiTek team (shows a badge).')
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.name} on {self.post.title[:40]}'


# ============================================================
# CONTRACTS (mikataba + e-signature)
# ============================================================

class Contract(models.Model):
    STATUS = [
        ('draft', 'Draft'),          # AI imeandaa / unahariri
        ('sent', 'Sent to client'),  # link imetumwa
        ('viewed', 'Viewed'),        # mteja amefungua
        ('signed', 'Signed'),        # mteja amesaini
        ('declined', 'Declined'),    # mteja amekataa
        ('cancelled', 'Cancelled'),  # umeghairi
    ]

    # Kitambulisho cha link ya kipekee (mteja anafikia kwa hii)
    token = models.CharField(max_length=48, unique=True, editable=False, db_index=True)

    # Nani — client ni HIARI sasa (huhitaji kusajili mteja database)
    client = models.ForeignKey('Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='contracts')

    # Client details moja kwa moja (kama huna Client object)
    client_name = models.CharField(max_length=160, blank=True)
    client_email = models.EmailField(blank=True)
    client_company = models.CharField(max_length=160, blank=True)
    client_phone = models.CharField(max_length=40, blank=True)
    client_address = models.CharField(max_length=300, blank=True)

    # Maelezo ya mkataba
    title = models.CharField(max_length=200, default='Service Agreement',
                             help_text='e.g. Website Development Agreement')
    project_name = models.CharField(max_length=200, blank=True)

    # ── DYNAMIC CONTENT (JSON) ──
    # Sections: [{"id","heading_en","heading_sw","body_en","body_sw"}, ...]
    sections = models.JSONField(default=list, blank=True)
    # Line items: [{"desc","qty","unit_price","amount"}, ...]
    line_items = models.JSONField(default=list, blank=True)
    # Custom fields za summary: [{"label","value"}, ...]
    custom_fields = models.JSONField(default=list, blank=True)

    # Branding
    accent_color = models.CharField(max_length=9, default='#25d366')
    logo_url = models.URLField(blank=True)

    # Maudhui — mbili: Kiingereza + Kiswahili (mteja anachagua)
    body_en = models.TextField(blank=True,
                               help_text='Contract text in English (HTML). AI can draft this.')
    body_sw = models.TextField(blank=True,
                               help_text='Contract text in Swahili (HTML). AI can draft this.')

    # Fedha & muda (kwa muhtasari juu ya mkataba)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default='TZS')
    payment_terms = models.CharField(max_length=300, blank=True,
                                     help_text='e.g. 50% deposit, 50% on completion')
    timeline = models.CharField(max_length=200, blank=True,
                                help_text='e.g. 3 weeks from deposit')

    status = models.CharField(max_length=12, choices=STATUS, default='draft')

    # Party ya JamiiTek (provider)
    provider_name = models.CharField(max_length=120, default='JamiiTek')
    provider_rep = models.CharField(max_length=120, default='W. Chipindi',
                                    help_text='Your name as the signing representative')
    # Sahihi yako (admin) — imesainiwa mapema, inaonekana kwenye mkataba
    provider_signature = models.CharField(max_length=120, default='W. Chipindi',
                                          blank=True,
                                          help_text='Your handwritten-style signature text (e.g. W. Chipindi)')
    provider_signed_date = models.DateField(null=True, blank=True,
                                            help_text='Date you signed (defaults to creation date)')
    # Maandishi ya sehemu ya 14 (signatures) — editable
    signature_block_en = models.TextField(blank=True,
                                          help_text='Signatures section intro (English). Leave blank for default.')
    signature_block_sw = models.TextField(blank=True,
                                          help_text='Signatures section intro (Swahili). Leave blank for default.')

    # ── E-SIGNATURE (mteja anasaini) ──
    signed_name = models.CharField(max_length=160, blank=True)      # jina alilloandika
    signed_email = models.EmailField(blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_ip = models.GenericIPAddressField(null=True, blank=True)
    signed_language = models.CharField(max_length=2, blank=True)    # 'en' au 'sw'
    signature_data = models.TextField(blank=True)                   # drawn signature (base64 PNG)
    agreed_to_terms = models.BooleanField(default=False)

    # Tracking
    viewed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} — {self.display_client} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    @property
    def display_client(self):
        """Jina la mteja — kutoka field au Client object."""
        if self.client_name:
            return self.client_name
        if self.client:
            return self.client.name
        return 'Client'

    @property
    def display_company(self):
        if self.client_company:
            return self.client_company
        if self.client:
            return self.client.company
        return ''

    @property
    def display_email(self):
        if self.client_email:
            return self.client_email
        if self.client:
            return self.client.email
        return ''

    @property
    def computed_total(self):
        """Jumla kutoka line items (kama zipo), vinginevyo total_amount."""
        if self.line_items:
            try:
                return sum(float(it.get('amount', 0) or 0) for it in self.line_items)
            except (ValueError, TypeError):
                pass
        return float(self.total_amount) if self.total_amount else 0

    @property
    def is_signed(self):
        return self.status == 'signed' and self.signed_at is not None

    @property
    def public_url(self):
        return f'/contract/{self.token}/'

    @property
    def provider_date(self):
        """Tarehe ya provider (sahihi yako) — default tarehe ya kuundwa."""
        return self.provider_signed_date or (self.created_at.date() if self.created_at else None)


# ============================================================
# PROPOSALS (mapendekezo ya kitaalamu — link + e-accept)
# ============================================================

class Proposal(models.Model):
    STATUS = [
        ('draft', 'Draft'),
        ('sent', 'Sent to client'),
        ('viewed', 'Viewed'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    token = models.CharField(max_length=48, unique=True, editable=False, db_index=True)

    # Client (hiari — kama contract)
    client = models.ForeignKey('Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='proposals')
    client_name = models.CharField(max_length=160, blank=True)
    client_email = models.EmailField(blank=True)
    client_company = models.CharField(max_length=160, blank=True)
    client_phone = models.CharField(max_length=40, blank=True)

    # Meta
    title = models.CharField(max_length=200, default='Project Proposal')
    project_name = models.CharField(max_length=200, blank=True)
    reference_number = models.CharField(max_length=40, blank=True,
                                        help_text='e.g. JT-2026-001 (auto if blank)')
    valid_until = models.DateField(null=True, blank=True,
                                   help_text='Proposal expiry date')

    # ── CONTENT SECTIONS (EN + SW) ──
    # Executive summary / intro
    summary_en = models.TextField(blank=True)
    summary_sw = models.TextField(blank=True)
    # Scope / approach
    scope_en = models.TextField(blank=True)
    scope_sw = models.TextField(blank=True)
    # Why us / about
    about_en = models.TextField(blank=True)
    about_sw = models.TextField(blank=True)
    # Extra custom sections: [{"id","heading_en","heading_sw","body_en","body_sw"}]
    sections = models.JSONField(default=list, blank=True)

    # ── DELIVERABLES / PRICING (line items) ──
    # [{"desc","qty","unit_price","amount"}]
    line_items = models.JSONField(default=list, blank=True)
    currency = models.CharField(max_length=8, default='TZS')
    # Discount / notes
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    pricing_note = models.CharField(max_length=300, blank=True,
                                    help_text='e.g. Prices valid for 30 days. VAT exclusive.')

    # Timeline: [{"phase","duration","detail"}]
    timeline_items = models.JSONField(default=list, blank=True)

    # Terms / payment
    payment_terms = models.CharField(max_length=300, blank=True)

    status = models.CharField(max_length=12, choices=STATUS, default='draft')

    # Branding
    accent_color = models.CharField(max_length=9, default='#00d4ff')
    logo_url = models.URLField(blank=True)
    provider_name = models.CharField(max_length=120, default='JamiiTek')
    provider_rep = models.CharField(max_length=120, default='W. Chipindi')

    # ── CLIENT RESPONSE ──
    accepted_name = models.CharField(max_length=160, blank=True)
    accepted_email = models.EmailField(blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_ip = models.GenericIPAddressField(null=True, blank=True)
    decline_reason = models.CharField(max_length=300, blank=True)

    viewed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} — {self.display_client} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)
        # Auto reference number baada ya kupata pk
        if not self.reference_number and self.pk:
            ref = f'JT-{self.created_at.year if self.created_at else 2026}-{self.pk:04d}'
            Proposal.objects.filter(pk=self.pk).update(reference_number=ref)
            self.reference_number = ref

    @property
    def display_client(self):
        if self.client_name:
            return self.client_name
        if self.client:
            return self.client.name
        return 'Client'

    @property
    def display_company(self):
        if self.client_company:
            return self.client_company
        if self.client:
            return self.client.company
        return ''

    @property
    def display_email(self):
        if self.client_email:
            return self.client_email
        if self.client:
            return self.client.email
        return ''

    @property
    def subtotal(self):
        if self.line_items:
            try:
                return sum(float(it.get('amount', 0) or 0) for it in self.line_items)
            except (ValueError, TypeError):
                pass
        return 0

    @property
    def grand_total(self):
        total = self.subtotal
        if self.discount_amount:
            total -= float(self.discount_amount)
        return max(0, total)

    @property
    def is_accepted(self):
        return self.status == 'accepted' and self.accepted_at is not None

    @property
    def public_url(self):
        return f'/proposal/{self.token}/'


# ============================================================
# COMPANY PROFILE (dynamic — link ya umma + PDF)
# ============================================================

class CompanyProfile(models.Model):
    """Company profile inayohaririwa — inaonekana kwenye link + PDF."""
    company_name = models.CharField(max_length=140, default='JamiiTek Digital Agency')
    short_name = models.CharField(max_length=60, default='JamiiTek')
    tagline_en = models.CharField(max_length=200, default="Building Tanzania's Digital Future")
    tagline_sw = models.CharField(max_length=200, default='Tunajenga Mustakabali wa Kidijitali wa Tanzania')
    subtitle_en = models.CharField(max_length=200, default='Your Trusted Digital Partner in Tanzania')
    subtitle_sw = models.CharField(max_length=200, default='Mshirika Wako wa Kidijitali Tanzania')
    period = models.CharField(max_length=40, blank=True, help_text='e.g. 2025 — 2026')

    # Sehemu kuu (EN + SW)
    about_en = models.TextField(blank=True)
    about_sw = models.TextField(blank=True)
    mission_en = models.TextField(blank=True)
    mission_sw = models.TextField(blank=True)
    vision_en = models.TextField(blank=True)
    vision_sw = models.TextField(blank=True)

    # Orodha za dynamic
    # services: [{"name_en","name_sw","desc_en","desc_sw"}]
    services = models.JSONField(default=list, blank=True)
    # why_us: [{"text_en","text_sw"}]
    why_us = models.JSONField(default=list, blank=True)
    # projects: [{"name","type","tech"}]
    projects = models.JSONField(default=list, blank=True)
    # facts: [{"label_en","label_sw","value"}]
    facts = models.JSONField(default=list, blank=True)
    # sections za ziada: [{"heading_en","heading_sw","body_en","body_sw"}]
    sections = models.JSONField(default=list, blank=True)

    pricing_note_en = models.TextField(blank=True)
    pricing_note_sw = models.TextField(blank=True)

    # Mawasiliano
    email = models.EmailField(default='info@jamiitek.com')
    phone = models.CharField(max_length=40, blank=True)
    website = models.CharField(max_length=120, default='www.jamiitek.com')
    address = models.CharField(max_length=200, default='Dar es Salaam, Tanzania')

    logo_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True,
                                    help_text='Only the active profile is shown publicly')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at']

    def __str__(self):
        return f'{self.company_name}{" (active)" if self.is_active else ""}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            CompanyProfile.objects.exclude(pk=self.pk).update(is_active=False)

    @property
    def public_url(self):
        return '/company-profile/'


# ============================================================
# INVOICES (dynamic — kila aina ya malipo)
# ============================================================

class Invoice(models.Model):
    TYPES = [
        ('standard', 'Standard Invoice'),
        ('proforma', 'Proforma Invoice'),
        ('deposit', 'Deposit / Advance'),
        ('balance', 'Balance / Final'),
        ('recurring', 'Recurring (hosting, retainer)'),
        ('credit', 'Credit Note'),
    ]
    STATUS = [
        ('draft', 'Draft'),
        ('sent', 'Sent to client'),
        ('viewed', 'Viewed'),
        ('partial', 'Partially paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_MODES = [
        ('manual', 'Default methods (M-Pesa / Bank)'),
        ('pesapal', 'Pesapal (card / mobile money online)'),
        ('both', 'Both'),
    ]
    # Njia za kawaida za kulipa kwa ankara zote
    DEFAULT_PAYMENT_METHODS = [
        {'method': 'M-Pesa', 'details': '0750910158 - WILLIAM CHIPINDI'},
        {'method': 'Bank Transfer', 'details': '0152566355900 - WILLIAM CHIPINDI'},
    ]

    token = models.CharField(max_length=48, unique=True, editable=False, db_index=True)
    invoice_number = models.CharField(max_length=40, blank=True,
                                      help_text='Auto: INV-YYYY-NNNN if blank')
    invoice_type = models.CharField(max_length=12, choices=TYPES, default='standard')

    # Client (hiari kama contract/proposal)
    client = models.ForeignKey('Client', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='invoices')
    client_name = models.CharField(max_length=160, blank=True)
    client_email = models.EmailField(blank=True)
    client_company = models.CharField(max_length=160, blank=True)
    client_phone = models.CharField(max_length=40, blank=True)
    client_address = models.CharField(max_length=240, blank=True)

    title = models.CharField(max_length=200, default='Invoice')
    project_name = models.CharField(max_length=200, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    # Line items: [{"desc","qty","unit_price","amount"}]
    line_items = models.JSONField(default=list, blank=True)
    currency = models.CharField(max_length=8, default='TZS')
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                      help_text='e.g. 18 for 18% VAT. Leave blank for none.')
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                      help_text='For partial payments')

    # Maelezo ya malipo: [{"method","details"}] mfano M-Pesa / Bank
    payment_methods = models.JSONField(default=list, blank=True)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default='manual',
                                    help_text='Mteja aone njia za kawaida, Pesapal, au zote')
    payment_terms = models.CharField(max_length=300, blank=True)
    notes_en = models.TextField(blank=True)
    notes_sw = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=STATUS, default='draft')

    # Branding
    logo_url = models.URLField(blank=True)
    provider_name = models.CharField(max_length=120, default='JamiiTek')
    provider_rep = models.CharField(max_length=120, default='W. Chipindi')

    paid_at = models.DateTimeField(null=True, blank=True)
    paid_reference = models.CharField(max_length=120, blank=True,
                                      help_text='M-Pesa / bank reference')
    # Historia ya malipo: [{"amount","method","reference","at","by","source"}].
    # amount_paid ni jumla yake (malipo ya zamani kabla ya historia hayamo).
    payments = models.JSONField(default=list, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.invoice_number or "Invoice"} — {self.display_client} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)
        if not self.invoice_number and self.pk:
            year = self.created_at.year if self.created_at else 2026
            num = f'INV-{year}-{self.pk:04d}'
            Invoice.objects.filter(pk=self.pk).update(invoice_number=num)
            self.invoice_number = num

    @property
    def display_client(self):
        if self.client_name:
            return self.client_name
        if self.client:
            return self.client.name
        return 'Client'

    @property
    def display_company(self):
        if self.client_company:
            return self.client_company
        if self.client:
            return self.client.company
        return ''

    @property
    def display_email(self):
        if self.client_email:
            return self.client_email
        if self.client:
            return self.client.email
        return ''

    @staticmethod
    def _num(value):
        try:
            return float(str(value).replace(',', '').strip() or 0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def items(self):
        """Vitu vya ankara kwa mpangilio mmoja: desc, qty, unit_price, amount.

        Data ya zamani/ya mifumo mingine inatumia 'description' badala ya
        'desc', au haina 'amount' — vyote vinasomeka hapa."""
        rows = []
        for it in self.line_items or []:
            if not isinstance(it, dict):
                continue
            desc = str(it.get('desc') or it.get('description') or '').strip()
            qty = self._num(it.get('qty')) if it.get('qty') not in (None, '') else 1.0
            price = self._num(it.get('unit_price'))
            amount = it.get('amount')
            amount = self._num(amount) if amount not in (None, '') else qty * price
            if not price and qty:
                price = amount / qty
            if not desc and not amount:
                continue
            rows.append({'desc': desc, 'qty': int(qty) if qty == int(qty) else qty,
                         'unit_price': price, 'amount': amount})
        return rows

    @property
    def subtotal(self):
        return sum(it['amount'] for it in self.items)

    @property
    def discounted_subtotal(self):
        total = self.subtotal
        if self.discount_amount:
            total -= float(self.discount_amount)
        return max(0, total)

    @property
    def tax_amount(self):
        if not self.tax_percent:
            return 0
        return self.discounted_subtotal * float(self.tax_percent) / 100

    @property
    def grand_total(self):
        return self.discounted_subtotal + self.tax_amount

    @property
    def paid_total(self):
        return float(self.amount_paid) if self.amount_paid else 0

    @property
    def balance_due(self):
        return max(0, round(self.grand_total - self.paid_total, 2))

    @property
    def paid_percent(self):
        if self.grand_total <= 0:
            return 100 if self.is_paid else 0
        return max(0, min(100, int(self.paid_total * 100 / self.grand_total)))

    @property
    def is_paid(self):
        return self.status == 'paid' or (self.grand_total > 0 and self.balance_due <= 0)

    @property
    def is_open(self):
        """Imetumwa kwa mteja na bado inadaiwa."""
        return self.status not in ('draft', 'cancelled') and not self.is_paid

    @property
    def days_to_due(self):
        """Siku zilizobaki hadi tarehe ya mwisho (hasi = imechelewa)."""
        if not self.due_date:
            return None
        return (self.due_date - timezone.localdate()).days

    @property
    def is_overdue(self):
        return self.is_open and self.days_to_due is not None and self.days_to_due < 0

    @property
    def days_overdue(self):
        return -self.days_to_due if self.is_overdue else 0

    @property
    def display_status(self):
        """Hali inayoonekana: 'overdue' inahesabiwa, haihifadhiwi."""
        if self.status in ('draft', 'cancelled'):
            return self.status
        if self.is_paid:
            return 'paid'
        if self.is_overdue:
            return 'overdue'
        if self.paid_total > 0:
            return 'partial'
        return 'viewed' if self.viewed_at else 'sent'

    @property
    def payment_history(self):
        from django.utils.dateparse import parse_datetime
        rows = []
        for p in self.payments or []:
            if isinstance(p, dict):
                at = p.get('at')
                rows.append({**p, 'amount': self._num(p.get('amount')),
                             'at': parse_datetime(at) if isinstance(at, str) else None})
        return rows

    @property
    def unlogged_paid(self):
        """Kiasi kilicholipwa kabla historia ya malipo haijaanza kuhifadhiwa."""
        return max(0, round(self.paid_total - sum(p['amount'] for p in self.payment_history), 2))

    def sync_payment_status(self):
        """Hali ya malipo inafuata kiasi kilicholipwa — si kinyume chake."""
        if self.status in ('draft', 'cancelled'):
            return
        total = self.grand_total
        if total > 0 and self.paid_total >= total - 0.005:
            self.status = 'paid'
            self.paid_at = self.paid_at or timezone.now()
        elif self.paid_total > 0:
            self.status = 'partial'
            self.paid_at = None
        elif self.status in ('paid', 'partial', 'overdue'):
            self.status = 'viewed' if self.viewed_at else 'sent'
            self.paid_at = None

    def record_payment(self, amount, method='', reference='', by='', source='manual'):
        """Ongeza malipo moja (hayafuti yaliyotangulia) na usasishe hali.

        Haihifadhi — anayeita anaita save()."""
        from decimal import Decimal, InvalidOperation
        try:
            amount = Decimal(str(amount).replace(',', '')).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            raise ValueError('Invalid amount')
        if amount <= 0:
            raise ValueError('Amount must be greater than zero')
        self.amount_paid = Decimal(str(self.amount_paid or 0)) + amount
        self.payments = list(self.payments or []) + [{
            'amount': float(amount), 'method': (method or '')[:60],
            'reference': (reference or '')[:120], 'by': (by or '')[:80],
            'source': source, 'at': timezone.now().isoformat(),
        }]
        if reference:
            self.paid_reference = reference[:120]
        if self.status == 'draft':
            self.status = 'sent'
            self.sent_at = self.sent_at or timezone.now()
        self.sync_payment_status()

    @property
    def shows_manual(self):
        return self.payment_mode in ('manual', 'both')

    @property
    def shows_pesapal(self):
        return self.payment_mode in ('pesapal', 'both')

    @property
    def public_url(self):
        return f'/invoice/{self.token}/'


# ── Integrations (Render / Cloudflare / RDAP) ──
from .integration_models import (  # noqa: E402,F401
    Integration,
    IntegrationSnapshot,
    IntegrationAuditLog,
)

# ══════════════════════════════════════════════════════════════════
#  KUMBUKUMBU YA BARUA PEPE
# ══════════════════════════════════════════════════════════════════
class EmailLog(models.Model):
    """Kila barua inayotoka kwenye mfumo, pamoja na hatima yake.

    KWA NINI

    Awali njia pekee ya kujua barua imetumwa ilikuwa logs za Render —
    ambazo zinafutwa, na huwezi kuzitafuta kwa jina la mteja. Na hata
    hizo zilikuambia tu kwamba Brevo ameipokea; si kwamba imemfikia
    mteja.

    Brevo anajua hatima halisi (delivered, bounced, spam) na anatuapa
    taarifa kwa webhook. `message_id` ndiyo inayounganisha barua
    tuliyoituma na tukio linalorudi.
    """

    STATUS = [
        ('sent',      'Imetumwa'),        # Brevo ameipokea
        ('delivered', 'Imefika'),         # imeingia kwenye inbox
        ('opened',    'Imefunguliwa'),
        ('clicked',   'Amebonyeza link'),
        ('deferred',  'Imecheleweshwa'),
        ('bounced',   'Imerudi'),         # anwani mbaya / imejaa
        ('spam',      'Spam'),
        ('blocked',   'Imezuiliwa'),
        ('error',     'Imeshindwa'),      # haikutoka kwetu kabisa
    ]

    # Hatua inayopanda: tukio la chini halishushi hali ya juu.
    # (Brevo inaweza kutuma "delivered" baada ya "opened".)
    RANK = {'error': 0, 'sent': 1, 'deferred': 2, 'delivered': 3,
            'opened': 4, 'clicked': 5, 'bounced': 6, 'spam': 7, 'blocked': 8}

    to_email   = models.EmailField(db_index=True)
    subject    = models.CharField(max_length=255)
    category   = models.CharField(max_length=40, blank=True, db_index=True,
                                  help_text='Aina ya barua, mfano suspension au expiry_warning')
    message_id = models.CharField(max_length=255, blank=True, db_index=True,
                                  help_text='messageId kutoka Brevo — inaunganisha na matukio')

    status     = models.CharField(max_length=12, choices=STATUS, default='sent', db_index=True)
    error      = models.TextField(blank=True)

    client  = models.ForeignKey('Client', null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='email_logs')
    website = models.ForeignKey('ManagedWebsite', null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='email_logs')

    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at    = models.DateTimeField(null=True, blank=True)
    failed_at    = models.DateTimeField(null=True, blank=True)

    # Ratiba kamili ya matukio: [{'event': 'delivered', 'at': '...', 'reason': ''}]
    events = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Email log'
        verbose_name_plural = 'Email logs'
        indexes = [models.Index(fields=['-created_at', 'status'])]

    def __str__(self):
        return f'{self.to_email} — {self.subject[:50]} [{self.status}]'

    @property
    def is_problem(self):
        return self.status in ('bounced', 'spam', 'blocked', 'error')

    @property
    def clean_subject(self):
        """Kichwa bila alama za WhatsApp (*bold*) zinazotoka kwenye alerts."""
        return (self.subject or '').replace('*', '').strip()

    @property
    def explanation(self):
        """Tatizo kwa lugha ya kawaida, pamoja na hatua ya kuchukua."""
        low = (self.error or '').lower()
        if self.status == 'blocked' and 'blacklist' in low:
            return ('Brevo ameweka anwani hii kwenye orodha ya kuzuiwa — kwa kawaida '
                    'kwa sababu barua za awali zilirudi (anwani haipo). Rekebisha '
                    'anwani, kisha iondoe Brevo → Contacts → Blocklist.')
        if self.status == 'blocked':
            return 'Brevo amezuia barua hii. Angalia sababu hapo juu.'
        if self.status == 'bounced':
            if 'mx' in low or 'domain' in low:
                return 'Domain ya anwani hii haipokei barua. Huenda imeandikwa vibaya.'
            return 'Anwani haipo au sanduku lake limejaa. Thibitisha na mteja.'
        if self.status == 'spam':
            return 'Mpokeaji aliiweka kama spam. Brevo huenda akazuia barua zijazo kwake.'
        if self.status == 'error':
            return 'Barua haikutoka kwetu kabisa. Kosa kamili liko hapo juu.'
        if self.status == 'deferred':
            return 'Server ya mpokeaji imeichelewesha. Brevo atajaribu tena mwenyewe.'
        return ''

    def apply_event(self, event, at=None, reason=''):
        """Weka tukio jipya. Salama kurudiwa — Brevo hurudia matukio."""
        from django.utils import timezone as tz
        at = at or tz.now()
        # Brevo anatumia snake_case kwenye payload ("hard_bounce") lakini
        # camelCase kwenye API ("hardBounce"). Kubali zote mbili.
        import re as _re
        event = _re.sub(r'(?<!^)(?=[A-Z])', '_', (event or '').strip())
        event = event.lower().replace(' ', '_')

        mapping = {
            'request': 'sent', 'sent': 'sent',
            'delivered': 'delivered',
            'opened': 'opened', 'unique_opened': 'opened', 'open': 'opened',
            # Apple Mail na baadhi ya huduma hufungua barua kupitia proxy
            'proxy_open': 'opened', 'unique_proxy_open': 'opened',
            'click': 'clicked', 'clicked': 'clicked',
            'deferred': 'deferred',
            'soft_bounce': 'deferred',      # Brevo inajaribu tena
            'hard_bounce': 'bounced', 'bounce': 'bounced', 'invalid_email': 'bounced',
            'spam': 'spam', 'complaint': 'spam', 'unsubscribed': 'spam',
            'blocked': 'blocked',
            'error': 'error',
        }
        new = mapping.get(event)
        if not new:
            return False

        # Ratiba inakua daima, hata kama hali haibadiliki
        stamp = at.isoformat() if hasattr(at, 'isoformat') else str(at)
        if not any(e.get('event') == event and e.get('at') == stamp for e in self.events):
            self.events = list(self.events) + [
                {'event': event, 'at': stamp, 'reason': reason or ''}]

        if new == 'delivered' and not self.delivered_at:
            self.delivered_at = at
        if new == 'opened' and not self.opened_at:
            self.opened_at = at
        if new in ('bounced', 'spam', 'blocked', 'error') and not self.failed_at:
            self.failed_at = at
        # Sababu ni ya MATATIZO pekee. Brevo anatuma `reason` hata kwa
        # tukio la kawaida ("sent"), na tulikuwa tukiionyesha kwa rangi
        # nyekundu chini ya kila barua kana kwamba ni kosa.
        if reason and new in ('bounced', 'spam', 'blocked', 'error', 'deferred'):
            self.error = reason[:2000]

        # Panda tu — "delivered" inayofika baada ya "opened" isishushe hali
        if self.RANK.get(new, 0) >= self.RANK.get(self.status, 0):
            self.status = new

        self.save(update_fields=['status', 'events', 'delivered_at',
                                 'opened_at', 'failed_at', 'error'])
        return True

