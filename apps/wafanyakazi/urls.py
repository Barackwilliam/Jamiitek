from django.urls import path

from . import views

urlpatterns = [
    path('manage/wafanyakazi/', views.dashboard, name='wafanyakazi_dashboard'),
    path('manage/wafanyakazi/endesha/', views.run_now, name='wafanyakazi_run'),
    path('manage/wafanyakazi/mtihani/', views.exam, name='wafanyakazi_exam'),
    path('manage/seo/', views.seo_report, name='wafanyakazi_seo'),
    path('manage/wafanyakazi/kazi/<int:pk>/<str:action>/', views.task_action, name='wafanyakazi_action'),
    path('tasks/wafanyakazi/', views.cron, name='wafanyakazi_cron'),
    path('wafanyakazi/api/hali/', views.api_status, name='wafanyakazi_api_status'),
    path('wafanyakazi/api/kazi/<int:pk>/idhinisha/', views.api_approve, name='wafanyakazi_api_approve'),
    path('wafanyakazi/api/kazi/<int:pk>/kataa/', views.api_reject, name='wafanyakazi_api_reject'),
    path('wafanyakazi/api/endesha/', views.api_run, name='wafanyakazi_api_run'),
]
