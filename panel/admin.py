from django.contrib import admin
from .models import UPSDevice, TelemetryLog, PowerEvent, AlertConfig

@admin.register(UPSDevice)
class UPSDeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'host', 'port', 'is_active', 'status']
    list_filter = ['is_active', 'status']
    search_fields = ['name', 'location', 'host']

@admin.register(TelemetryLog)
class TelemetryLogAdmin(admin.ModelAdmin):
    list_display = ['device', 'timestamp', 'vin', 'vout', 'load_pct', 'mode']
    list_filter = ['device', 'mode']
    search_fields = ['device__name']
    date_hierarchy = 'timestamp'

@admin.register(PowerEvent)
class PowerEventAdmin(admin.ModelAdmin):
    list_display = ['device', 'event_type', 'started_at', 'ended_at', 'duration_seconds', 'severity']
    list_filter = ['device', 'event_type', 'severity']
    search_fields = ['device__name']
    date_hierarchy = 'started_at'

@admin.register(AlertConfig)
class AlertConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'notify_on_battery', 'notify_on_restore', 'notify_on_offline')

# Register your models here.
