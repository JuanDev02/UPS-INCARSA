from django.urls import path
from . import views

app_name = 'panel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/login/', views.api_login, name='api_login'),
    path('api/logout/', views.api_logout, name='api_logout'),
    
    path('api/me/', views.api_me, name='api_me'),
    path('api/usuarios/', views.api_usuarios, name='api_usuarios'),
    path('api/flota/', views.api_flota, name='api_flota'),
    path('api/dispositivos/', views.api_Dispositivos, name='api_dispositivos'),
    path('api/dispositivos/<int:device_id>/', views.api_Dispositivos, name='api_dispositivo_detail'),

    path('api/dispositivos/<int:device_id>/telemetria/', views.api_TelemetryDevice, name='api_TelemetryDevice'),
    path('api/telemetria/live/', views.api_TelemetryDevice, name='api_telemetria_live'),

    path('api/historico/', views.api_Historico, name='api_Historico'),
    path('api/dispositivos/<int:device_id>/historico/', views.api_Historico, name='api_device_historico'),

    path('api/eventos/', views.api_Eventos, name='api_Eventos'),
    path('api/dispositivos/<int:device_id>/eventos/', views.api_Eventos, name='api_device_eventos'),

    path('api/alertas/config/', views.api_AlertConfig, name='api_alert_config'),
    path('api/dispositivos/<int:device_id>/alertas/', views.api_AlertConfig, name='api_device_alert_config'),
]
