from django.urls import path
from . import views
from . import webchat

urlpatterns = [
    # ── Auth ──
    path('register/',  views.chatbot_register, name='chatbot_register'),
    path('login/',     views.chatbot_login,    name='chatbot_login'),
    path('logout/',    views.chatbot_logout,   name='chatbot_logout'),

    # ── Setup Wizard ──
    path('setup/', views.chatbot_setup_wizard, name='chatbot_setup_wizard'),

    # ── Portal ──
    path('dashboard/',                          views.chatbot_dashboard,           name='chatbot_dashboard'),
    path('config/',                             views.chatbot_config,              name='chatbot_config'),
    path('pause/',                              views.chatbot_pause,               name='chatbot_pause'),

    # ── Maarifa ya bot ──
    path('knowledge/',                   views.chatbot_knowledge,        name='chatbot_knowledge'),
    path('knowledge/<int:gap_id>/',      views.chatbot_knowledge_action, name='chatbot_knowledge_action'),

    # ── Mteja anajiunganisha mwenyewe ──
    path('connect/',        views.chatbot_connect,        name='chatbot_connect'),
    path('connect/qr/',     views.chatbot_connect_qr,     name='chatbot_connect_qr'),
    path('connect/action/', views.chatbot_connect_action, name='chatbot_connect_action'),

    # ── Weka bot kwenye tovuti ya mteja (maelekezo + link) ──
    path('website/',        views.chatbot_website,        name='chatbot_website'),

    # ── Demo seed (jaza demo data kwa mbonyezo mmoja) ──
    path('seed-demo/',      views.chatbot_seed_demo,      name='chatbot_seed_demo'),
    path('conversations/',                      views.chatbot_conversations,       name='chatbot_conversations'),
    # Conversation.id ni UUID, si int. Ikiwa <int:>, ukurasa wa dashboard
    # unaanguka kwa NoReverseMatch mara tu bot inapopata mazungumzo ya
    # kwanza — yaani kwa kila mteja halisi.
    path('conversations/<uuid:conv_id>/',       views.chatbot_conversation_detail, name='chatbot_conversation_detail'),
    path('conversations/<uuid:conv_id>/resume/', views.chatbot_resume,          name='chatbot_resume'),
    path('billing/',                            views.chatbot_billing,             name='chatbot_billing'),

    # ── Chat ya website (embeddable widget) ──
    # <script src="/chatbot/widget/<BOT_ID>.js"> -> kitufe kinachoelea
    path('widget/<uuid:bot_id>.js', webchat.web_widget_js, name='web_widget_js'),
    path('web/<uuid:bot_id>/',      webchat.web_chat,      name='web_chat'),

    # ── Baileys bridge ──
    path('webhook/baileys/', views.baileys_webhook, name='baileys_webhook'),
    path('bridge/sessions/', views.bridge_session_list, name='bridge_session_list'),

    # ── Webhook ya Meta (legacy — haitumiki tena) ──
    path('webhook/', views.whatsapp_webhook_global, name='whatsapp_webhook_global'),

    # ── Legacy per-bot webhook ──
    path('webhook/<uuid:bot_id>/', views.whatsapp_webhook, name='whatsapp_webhook'),

    # ── Simulate / Test (staff only) ──
    path('simulate/<uuid:bot_id>/', views.simulate_message, name='chatbot_simulate'),
]

# ── Legal ──
from django.urls import path as _p
urlpatterns += [
    _p('privacy-policy/', views.privacy_policy, name='privacy_policy'),
]