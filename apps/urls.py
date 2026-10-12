# apps/urls.py

from django.urls import path
from . import views
from . import blog_views
from . import email_webhook
from . import email_log_views
from builder import domain_views as site_domain_views
from . import contract_views
from . import proposal_views
from . import docs_views
from .views import select_website_type, dynamic_form, proposal_preview, generate_pdf
from .views import templates_marketplace, template_preview, template_preview_raw, template_detail
from . import management_views
from . import infra_views
from . import client_portal_views as portal
from builder import views as builder_views
from . import domain_views
from . import receipt_views
from . import bulk_actions
from django.views.generic import TemplateView
from . import sw_views
from . import pesapal_views
from apps.seo.feeds import BlogFeed
from . import password_reset
from . import two_factor

urlpatterns = [
    # ── Usalama wa akaunti: Forgot password (wote) + 2FA (staff) ──
    path('account/password-reset/', password_reset.RequestView.as_view(), name='password_reset'),
    path('account/password-reset/sent/', password_reset.DoneView.as_view(), name='password_reset_done'),
    path('account/password-reset/<uidb64>/<token>/', password_reset.ConfirmView.as_view(),
         name='password_reset_confirm'),
    path('account/password-reset/complete/', password_reset.CompleteView.as_view(),
         name='password_reset_complete'),
    path('account/2fa/', two_factor.verify, name='two_factor_verify'),
    path('account/2fa/setup/', two_factor.setup, name='two_factor_setup'),
    path('account/2fa/recovery-codes/', two_factor.recovery_codes, name='two_factor_recovery_codes'),
    path('account/sign-out/', two_factor.sign_out, name='account_sign_out'),
    path('account/help/', password_reset.help_center, name='account_help'),

    # ── PESAPAL PAYMENTS (mfumo mzima) ──────────────────────
    path('pay/subscription/', pesapal_views.pay_subscription, name='pesapal_pay_subscription'),
    path('pay/hosting/<int:website_pk>/', pesapal_views.pay_hosting, name='pesapal_pay_hosting'),
    path('pay/invoice/<str:token>/', pesapal_views.pay_invoice, name='pesapal_pay_invoice'),
    path('pay/callback/', pesapal_views.pesapal_callback, name='pesapal_callback'),
    path('pay/ipn/', pesapal_views.pesapal_ipn, name='pesapal_ipn'),



    path('offline.html', TemplateView.as_view(template_name='offline.html'), name='offline'),
    path('sw.js', sw_views.service_worker, name='sw'),


    # ── COMPANY PROFILE ─────────────────────────────────────
    path('company-profile/', docs_views.company_profile_view, name='company_profile_view'),
    path('company-profile/pdf/', docs_views.company_profile_pdf, name='company_profile_pdf'),

    # ── Kupakia image (Supabase) ──
    path('manage/upload/', management_views.upload_file, name='upload_file'),
    path('manage/storage/health/', management_views.storage_health, name='storage_health'),
    path('manage/profile/', docs_views.profile_builder, name='profile_builder'),
    path('manage/profile/ai-full/', docs_views.profile_ai_full, name='profile_ai_full'),
    path('manage/profile/ai-assist/', docs_views.profile_ai_assist, name='profile_ai_assist'),

    # ── INVOICES ────────────────────────────────────────────
    path('manage/invoices/', docs_views.invoice_list, name='invoice_list'),
    path('manage/invoices/new/', docs_views.invoice_new, name='invoice_new'),
    path('manage/invoices/<int:pk>/edit/', docs_views.invoice_edit, name='invoice_edit'),
    path('manage/invoices/<int:pk>/mark-paid/', docs_views.invoice_mark_paid, name='invoice_mark_paid'),
    path('manage/invoices/<int:pk>/payments/<int:index>/remove/', docs_views.invoice_remove_payment, name='invoice_remove_payment'),
    path('manage/invoices/<int:pk>/payments/earlier/remove/', docs_views.invoice_clear_earlier_payment, name='invoice_clear_earlier_payment'),
    path('manage/invoices/<int:pk>/send/', docs_views.invoice_send, name='invoice_send'),
    path('manage/invoices/<int:pk>/duplicate/', docs_views.invoice_duplicate, name='invoice_duplicate'),
    path('manage/invoices/ai-assist/', docs_views.invoice_ai_assist, name='invoice_ai_assist'),
    path('invoice/<str:token>/', docs_views.invoice_view, name='invoice_view'),
    path('invoice/<str:token>/pdf/', docs_views.invoice_pdf, name='invoice_pdf'),


    path('manage/receipts/', receipt_views.receipt_list, name='receipt_list'),
    path('manage/receipts/new/', receipt_views.receipt_new, name='receipt_new'),
    path('manage/receipts/new/<int:website_pk>/', receipt_views.receipt_new, name='receipt_new_for_website'),
    path('manage/receipts/<int:pk>/edit/', receipt_views.receipt_edit, name='receipt_edit'),
    path('manage/receipts/<int:pk>/delete/', receipt_views.receipt_delete, name='receipt_delete'),
    path('manage/receipts/<int:pk>/pdf/', receipt_views.receipt_pdf_staff, name='receipt_pdf_staff'),

    path('portal/receipts/', receipt_views.portal_receipt_list, name='portal_receipt_list'),
    path('portal/receipts/<int:pk>/download/', receipt_views.portal_receipt_pdf, name='portal_receipt_pdf'),
    path('portal/receipts/<int:pk>/sign/', receipt_views.portal_receipt_sign, name='portal_receipt_sign'),

    path('receipt/verify/<str:token>/', receipt_views.receipt_verify, name='receipt_verify'),
    path('receipt/<str:token>/', receipt_views.receipt_public, name='receipt_public'),

    # ── PROPOSAL BUILDER (ndani ya /manage/, staff-only) ────
    path('manage/proposals/', proposal_views.proposal_builder_list, name='proposal_builder_list'),
    path('manage/proposals/new/', proposal_views.proposal_builder_new, name='proposal_builder_new'),
    path('manage/proposals/<int:pk>/edit/', proposal_views.proposal_builder_edit, name='proposal_builder_edit'),
    path('manage/proposals/<int:pk>/ai-full/', proposal_views.proposal_ai_full, name='proposal_ai_full'),
    path('manage/proposals/ai-assist/', proposal_views.proposal_ai_assist, name='proposal_ai_assist'),
    path('manage/proposals/from-lead/<int:lead_id>/', proposal_views.proposal_from_lead, name='proposal_from_lead'),
    path('manage/leads/', proposal_views.lead_list, name='lead_list'),
    # Proposal (mteja anafikia kwa link)
    path('proposal/<str:token>/', proposal_views.proposal_view, name='proposal_view'),
    path('proposal/<str:token>/accept/', proposal_views.proposal_accept, name='proposal_accept'),
    path('proposal/<str:token>/decline/', proposal_views.proposal_decline, name='proposal_decline'),
    path('proposal/<str:token>/pdf/', proposal_views.proposal_pdf, name='proposal_pdf'),

    # ── CONTRACT BUILDER (ndani ya /manage/, staff-only) ────
    path('manage/contracts/', contract_views.contract_builder_list, name='contract_builder_list'),
    path('manage/contracts/new/', contract_views.contract_builder_new, name='contract_builder_new'),
    path('manage/contracts/<int:pk>/edit/', contract_views.contract_builder_edit, name='contract_builder_edit'),
    path('manage/contracts/<int:pk>/ai-full/', contract_views.contract_builder_ai_full, name='contract_builder_ai_full'),
    path('manage/contracts/ai-assist/', contract_views.contract_builder_ai_assist, name='contract_builder_ai_assist'),

    # ── CONTRACTS (mteja anafikia kwa link) ───────────────
    path('contract/<str:token>/', contract_views.contract_view, name='contract_view'),
    path('contract/<str:token>/sign/', contract_views.contract_sign, name='contract_sign'),
    path('contract/<str:token>/decline/', contract_views.contract_decline, name='contract_decline'),
    path('contract/<str:token>/pdf/', contract_views.contract_pdf, name='contract_pdf'),

    # ── BLOG ──────────────────────────────────────────────
    path('blog/', blog_views.blog_list, name='blog_list'),
    path('blog/feed/', BlogFeed(), name='blog_feed'),
    path('blog/editorial-policy/', blog_views.editorial_policy, name='blog_editorial'),
    path('blog/author/<slug:slug>/', blog_views.blog_author, name='blog_author'),
    path('blog/<slug:slug>/', blog_views.blog_detail, name='blog_detail'),
    path('blog/<slug:slug>/comment/', blog_views.blog_comment, name='blog_comment'),

    # ── PUBLIC SITE ───────────────────────────────────────
    path('', views.home, name='home'),
    path('service/', views.service, name='service'),
    path('About/', views.About, name='About'),
    path('contact/', views.contact, name='contact'),
    path('newsletter/subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),
    path('domain-check/', domain_views.domain_check, name='domain_check'),

    # ── TEMPLATES MARKETPLACE ─────────────────────────────
    path('templates/', templates_marketplace, name='templates_marketplace'),
    path('templates/preview/<int:pk>/', template_preview, name='template_preview'),
    path('templates/preview/<int:pk>/raw/', template_preview_raw, name='template_preview_raw'),
    # SEO: jamii (/templates/c/restaurant/) na ukurasa wa kila template (/templates/<slug>/)
    path('templates/c/<slug:cat_slug>/', templates_marketplace, name='templates_category'),
    path('templates/<slug:slug>/', template_detail, name='template_detail'),

    # Proposal System
    path('proposals/', select_website_type, name='select_website'),
    path('proposals/form/<int:website_type_id>/', dynamic_form, name='dynamic_form'),
    path('proposals/preview/<int:proposal_id>/', proposal_preview, name='proposal_preview'),
    path('proposals/download/<int:proposal_id>/', generate_pdf, name='generate_pdf'),

    # ── MANAGEMENT PANEL ──────────────────────────────────
    path('manage/login/', management_views.management_login, name='management_login'),
    path('manage/logout/', management_views.management_logout, name='management_logout'),
    path('manage/', management_views.management_dashboard, name='management_dashboard'),
    path('manage/builder/', builder_views.superadmin, name='manage_builder'),
    path('manage/websites/', management_views.website_list, name='website_list'),
    path('manage/websites/auto-suspend/', management_views.run_auto_suspend_view, name='run_auto_suspend'),
    path('tasks/daily/', management_views.daily_tasks_endpoint, name='daily_tasks_endpoint'),
    # Brevo inatuambia hatima ya kila barua (delivered, bounced, opened)
    # Kufuatilia barua: imetumwa? imefika? imefunguliwa?
    path('manage/emails/', email_log_views.email_log_list, name='email_log_list'),
    path('manage/emails/test/', email_log_views.email_send_test, name='email_send_test'),
    # Domain za WEBSITE za wateja wa builder (tofauti na /manage/domains/,
    # ambayo ni domain unazosajili na kuuza kwa wateja)
    path('manage/site-domains/', site_domain_views.domain_list, name='site_domain_list'),
    path('manage/site-domains/connect/', site_domain_views.domain_connect, name='site_domain_connect'),
    path('manage/site-domains/<int:pk>/check/', site_domain_views.domain_check, name='site_domain_check'),
    path('manage/site-domains/<int:pk>/register/', site_domain_views.domain_reregister, name='site_domain_reregister'),
    path('manage/site-domains/<int:pk>/disconnect/', site_domain_views.domain_disconnect, name='site_domain_disconnect'),

    path('webhooks/brevo/', email_webhook.brevo_webhook, name='brevo_webhook'),

    path('tasks/news/', management_views.news_blog_endpoint, name='news_blog_endpoint'),
    path('manage/websites/add/', management_views.website_add, name='website_add'),
    path('manage/websites/<int:pk>/', management_views.website_detail, name='website_detail'),
    path('manage/websites/<int:pk>/edit/', management_views.website_edit, name='website_edit'),
    path('manage/websites/<int:pk>/suspend/', management_views.suspend_website, name='suspend_website'),
    path('manage/websites/<int:pk>/restore/', management_views.restore_website, name='restore_website'),
    path('manage/websites/<int:pk>/maintenance/', management_views.set_maintenance, name='set_maintenance'),
    path('manage/websites/<int:pk>/features/<int:feature_pk>/toggle/', management_views.toggle_feature, name='toggle_feature'),
    path('manage/websites/<int:pk>/features/add/', management_views.add_feature, name='add_feature'),
    path('manage/websites/<int:pk>/payments/add/', management_views.add_payment, name='add_payment'),
    path('manage/websites/<int:pk>/notify/', management_views.send_notification, name='send_notification'),
    path('manage/websites/<int:pk>/schedule/', management_views.schedule_action, name='schedule_action'),
    path('manage/websites/<int:pk>/api-key/regenerate/', management_views.regenerate_api_key, name='regenerate_api_key'),
    path('manage/actions/<int:action_pk>/cancel/', management_views.cancel_scheduled_action, name='cancel_scheduled_action'),
    path('manage/clients/', management_views.client_list, name='client_list'),
    path('manage/clients/<int:pk>/', management_views.client_detail_admin, name='client_detail_admin'),

    # ── DOMAIN MANAGEMENT ─────────────────────────────────
    path('manage/domains/', management_views.domain_list, name='domain_list'),
    path('manage/domains/add/', management_views.domain_add, name='domain_add'),
    path('manage/domains/<int:pk>/', management_views.domain_detail, name='domain_detail'),
    path('manage/domains/<int:pk>/renew/', management_views.domain_renew, name='domain_renew'),
    path('manage/domains/<int:pk>/status/', management_views.domain_update_status, name='domain_update_status'),

    # ── EMAIL HOSTING MANAGEMENT ──────────────────────────
    path('manage/email/', management_views.email_hosting_list, name='email_hosting_list'),
    path('manage/email/add/', management_views.email_hosting_add, name='email_hosting_add'),
    path('manage/email/<int:pk>/', management_views.email_hosting_detail, name='email_hosting_detail'),
    path('manage/email/<int:pk>/payment/', management_views.email_hosting_payment, name='email_hosting_payment'),
    path('manage/email/<int:pk>/suspend/', management_views.email_hosting_suspend, name='email_hosting_suspend'),
    path('manage/email/<int:pk>/restore/', management_views.email_hosting_restore, name='email_hosting_restore'),

    # ── CLIENT PORTAL ─────────────────────────────────────
    path('portal/', portal.portal_dashboard, name='portal_dashboard'),
    path('portal/login/', portal.portal_login, name='portal_login'),
    path('portal/logout/', portal.portal_logout, name='portal_logout'),
    path('portal/register/', portal.portal_register, name='portal_register'),
    path('portal/websites/', portal.portal_website_list, name='portal_website_list'),
    path('portal/websites/<int:pk>/', portal.portal_website_detail, name='portal_website_detail'),
    path('portal/billing/', portal.portal_billing, name='portal_billing'),
    path('portal/billing/submit/', portal.portal_submit_payment, name='portal_submit_payment'),
    path('portal/billing/invoice/', portal.portal_request_invoice, name='portal_request_invoice'),
    path('portal/notifications/', portal.portal_notifications, name='portal_notifications'),
    path('portal/profile/', portal.portal_profile, name='portal_profile'),
    path('portal/support/', portal.portal_support, name='portal_support'),
    path('portal/domains/', portal.portal_domains, name='portal_domains'),
    path('portal/email/', portal.portal_email_hosting, name='portal_email_hosting'),
    path('portal/hosting/<int:pk>/', portal.portal_hosting_config, name='portal_hosting_config'),
    path('portal/dns/<int:pk>/', portal.portal_dns_manager, name='portal_dns_manager'),


    path('manage/websites/bulk/', bulk_actions.bulk_website_action, name='bulk_website_action'),
    path('manage/clients/<int:pk>/suspend-all/', bulk_actions.suspend_client_websites, name='suspend_client_websites'),
    path('manage/clients/<int:pk>/activate-all/', bulk_actions.activate_client_websites, name='activate_client_websites'),

    # ── PUBLIC API ─────────────────────────────────────────
    path('api/site-status/<str:api_key>/', management_views.site_status_api, name='site_status_api'),
    path('api/js/<str:api_key>/', management_views.get_js_snippet, name='get_js_snippet'),

    # ── INFRASTRUCTURE (staff-only) ──
    path('manage/infra/', infra_views.infra_overview, name='infra_overview'),
    path('manage/infra/audit/', infra_views.infra_audit, name='infra_audit'),
    path('manage/infra/fields/', infra_views.infra_credential_fields, name='infra_credential_fields'),
    path('manage/infra/<int:pk>/', infra_views.infra_detail, name='infra_detail'),
    path('manage/infra/<int:pk>/sync/', infra_views.infra_sync, name='infra_sync'),
    path('manage/infra/<int:pk>/discover/', infra_views.infra_discover, name='infra_discover'),
    path('manage/infra/<int:pk>/attach/', infra_views.infra_attach, name='infra_attach'),
    path('manage/infra/action/<int:integration_id>/', infra_views.infra_action, name='infra_action'),
    path('manage/infra/job/<int:integration_id>/<str:job_id>/', infra_views.infra_job_status, name='infra_job_status'),
    path('manage/infra/sections/<int:integration_id>/', infra_views.infra_sections, name='infra_sections'),
    path('manage/infra/disconnect/<int:integration_id>/', infra_views.infra_disconnect, name='infra_disconnect'),
    path('manage/infra/<int:pk>/report/', infra_views.infra_report, name='infra_report'),
    path('portal/website/<int:pk>/report/', portal.portal_monthly_report, name='portal_monthly_report'),
    path('cron/sync/', infra_views.cron_sync, name='cron_sync'),
]