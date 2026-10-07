from django.urls import path
from . import views

app_name = 'monitoreo'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/login/', views.api_login, name='api_login'),
    path('api/logout/', views.api_logout, name='api_logout'),
    path('api/me/', views.api_me, name='api_me'),
]
