from django.urls import path
from adminapi import views

urlpatterns = [
    path('assets/<path:path>', views.frontend_asset),
    path('static/<path:path>', views.legacy_asset),
    path('api/auth/', views.auth_state),
    path('api/login/request-code/', views.request_login_code),
    path('api/login/verify-code/', views.verify_login_code),
    path('api/logout/', views.logout),
    path('api/dashboard/', views.dashboard),
    path('api/support/', views.support_inbox),
    path('api/support/<int:conversation_id>/', views.support_conversation),
    path('api/support/<int:conversation_id>/reply/', views.reply_support),
    path('api/users/<int:user_id>/', views.user_detail),
    path('api/users/<int:user_id>/credits/', views.update_credits),
    path('api/users/<int:user_id>/streak/', views.update_streak),
    path('api/users/<int:user_id>/premium/', views.update_premium),
    path('api/users/<int:user_id>/logout/', views.force_logout),
    path('api/users/<int:user_id>/delete/', views.delete_user),
    path('<path:path>', views.frontend),
    path('', views.frontend),
]
