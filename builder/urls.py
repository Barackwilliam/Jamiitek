"""URLs za dashboard (zinaingia kwenye jamiitek/urls.py kama /builder/)."""
from django.urls import path
from . import views, ai, studio

app_name = 'builder'

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('login/', views.builder_login, name='login'),
    path('logout/', views.builder_logout, name='logout'),
    # Templates Marketplace → Builder (builder/template_bridge.py)
    path('templates/<int:pk>/use/', views.from_template, name='from_template'),
    path('', views.my_sites, name='my_sites'),
    path('new/', views.create_site, name='create_site'),
    path('tutorial/', views.tutorial, name='tutorial'),

    # One-Shot AI generator
    path('ai/', views.ai_generator, name='ai_generator'),
    path('ai/ticker/', views.ai_ticker, name='ai_ticker'),
    path('ai/generate/', views.ai_generate_website, name='ai_generate'),
    path('ai/apply/', views.ai_apply, name='ai_apply'),
    path('ai/field/', views.ai_field, name='ai_field'),
    path('ai/status/', views.ai_status, name='ai_status'),
    path('site/<int:site_id>/global-css/save/', views.save_global_css, name='save_global_css'),
    path('site/<int:site_id>/global-css/', views.get_global_css, name='get_global_css'),
    path('site/<int:site_id>/ai-theme/', views.ai_theme, name='ai_theme'),
    path('site/<int:site_id>/nav/', views.nav_editor, name='nav_editor'),
    path('site/<int:site_id>/nav/save/', views.nav_save, name='nav_save'),
    path('site/<int:site_id>/nav/ai/', views.ai_nav_generate, name='ai_nav_generate'),
    path('site/<int:site_id>/footer/save/', views.footer_save, name='footer_save'),

    # Super-admin (staff only)
    path('superadmin/', views.superadmin, name='superadmin'),
    path('superadmin/db-check/', views.superadmin_db_check, name='superadmin_db_check'),
    path('superadmin/<int:site_id>/action/', views.superadmin_action, name='superadmin_action'),
    path('site/<int:site_id>/collections/<int:collection_id>/ai-suggest/',
         views.ai_suggest_items, name='ai_suggest_items'),

    path('site/<int:site_id>/', views.site_dashboard, name='site_dashboard'),
    path('site/<int:site_id>/settings/', views.site_settings_save, name='site_settings_save'),
    path('site/<int:site_id>/publish/', views.toggle_publish, name='toggle_publish'),
    path('site/<int:site_id>/pay/<slug:kind>/', views.checkout, name='checkout'),
    # Kiungo cha "Stop these reminders" kwenye email za builder_unpaid (hakihitaji login)
    path('reminders/stop/<str:token>/', views.unpaid_stop, name='unpaid_stop'),
    path('site/<int:site_id>/template/', views.change_template, name='change_template'),

    # Website Studio — hatua kwa hatua (builder/studio.py)
    path('site/<int:site_id>/studio/', studio.studio, name='studio'),
    path('site/<int:site_id>/studio/preview/', studio.studio_preview, name='studio_preview'),
    path('site/<int:site_id>/studio/<slug:step>/', studio.studio, name='studio_step'),
    path('site/<int:site_id>/import/', views.site_import, name='site_import'),
    path('site/<int:site_id>/import/confirm/', views.site_import_confirm, name='site_import_confirm'),
    path('site/<int:site_id>/pages/new/', views.page_create, name='page_create'),
    path('site/<int:site_id>/pages/<int:page_id>/edit/', views.page_editor, name='page_editor'),
    path('site/<int:site_id>/pages/<int:page_id>/delete/', views.page_delete, name='page_delete'),
    path('site/<int:site_id>/pages/<int:page_id>/load/', views.page_load, name='page_load'),
    path('site/<int:site_id>/pages/<int:page_id>/save/', views.page_save, name='page_save'),

    path('site/<int:site_id>/collections/<int:collection_id>/', views.collection_items, name='collection_items'),
    path('site/<int:site_id>/collections/<int:collection_id>/new/', views.item_form, name='item_new'),
    path('site/<int:site_id>/collections/<int:collection_id>/<int:item_id>/', views.item_form, name='item_edit'),
    path('site/<int:site_id>/collections/<int:collection_id>/<int:item_id>/delete/', views.item_delete, name='item_delete'),

    path('site/<int:site_id>/inquiries/', views.inquiries_list, name='inquiries_list'),
    path('site/<int:site_id>/inquiries/<int:inquiry_id>/status/', views.inquiry_status, name='inquiry_status'),
    path('site/<int:site_id>/asset/upload/', views.asset_upload, name='asset_upload'),
    path('site/<int:site_id>/assets/', views.asset_list, name='asset_list'),

    path('ai/assist/', ai.ai_assist, name='ai_assist'),
]
