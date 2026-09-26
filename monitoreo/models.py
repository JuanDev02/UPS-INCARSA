from django.db import models
from django.utils import timezone
# Create yo
# ur models here.

class UPSDevice(models.Model):

    """
    Catálogo de UPS registradas.
    Permite tener múltiples equipos con sus respectivas IPs y puertos dinámicos.
    """

    STATUS_CHOICES = (
        ('online', 'En línea'),
        ('battery', 'Modo batería'),
        ('offline', 'Desconectado'),
    )

    name = models.CharField(
        max_length = 100,
        verbose_name = "Nombre del equipo",
        help_text = "Ej: UPS 1"
        )
    
    location = models.CharField(
        max_length = 150,
        verbose_name= "Ubicación",
        help_text = "Ej: Zona reservorios - mina raquira"        
    )

    host = models.CharField(
        max_length = 15,
        verbose_name = "IP del equipo",
        help_text = "Ej: 000.000.0.0"
    )

    port = models.CharField(
        max_length = 5,
        default = "7660",
        verbose_name = "Puerto TCP",
    )

    is_active = models.BooleanField(
        default = True,
        verbose_name = "Activo",
        help_text = "Marcar actividad"
    )

    status = models.CharField(
        max_length = 25,
        verbose_name = "Estado actual",
        default = 'offline',
        choices=STATUS_CHOICES,
    )

    battery_nominal = models.FloatField(
        default = 12.0,
        verbose_name = "Voltaje nominal (V)",
        help_text = "Voltaje nominal de baterias"
    )

    last_seen = models.DateTimeField(
        null = True,
        blank = True,
        verbose_name = "Última lectura",
        help_text = "Fecha y hora de la última lectura"
    )

    battery_voltage = models.FloatField(
        default = 12.0,
        verbose_name = "Voltaje actual (V)",
        help_text = "Voltaje actual del banco de baterias"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name = "Fecha de creación",
        help_text = "Fecha de creación del registro"
    )

    class Meta:
        verbose_name = "Dispositivo UPS"
        verbose_name_plural = "Dispositivos UPS"

    def __str__(self):
        return f"{self.name} - {self.location}"

class TelemetryLog(models.Model):

    """
    Histórico de mediciones eléctricas para gráficas y análisis.
    """

    MODE_CHOICES = [
        ('grid', 'Red eléctrica'),
        ('battery', 'Batería'),
    ]

    device = models.ForeignKey(UPSDevice, on_delete=models.CASCADE)

    timestamp = models.DateTimeField(
        default = timezone.now, 
        db_index = True,
        verbose_name = " DD/MM/YYYY HH:MM",
    )

    vin = models.FloatField(
        verbose_name = "Voltaje entrada (V)",
        help_text = "Voltaje de entrada del UPS",
    )
    
    vin_fault = models.FloatField(
        default = 0.0,
        verbose_name = "Indicador de falla de entrada",
        help_text = "1 = Falla, 0 = Sin falla" 
    )

    vout = models.FloatField(
        verbose_name = "Voltaje de salida (V)",
    )

    load_pct = models.FloatField(
        verbose_name = "Carga (%)"
    )

    frequency = models.FloatField(
        verbose_name = "Frecuencia (Hz)"
    )

    battery_voltage = models.FloatField(
        verbose_name = "Voltaje batería (V)"
    )

    temperature = models.FloatField(
        default = 0.0,
        verbose_name = "Temperatura (°C)"
    )

    status_q1 = models.CharField(
        max_length = 8,
        default = "00000000",
        verbose_name = "Estado Q1"
    )

    mode = models.CharField(
        max_length = 25,
        choices = MODE_CHOICES,
        default = 'grid',
        verbose_name = "Modo de operación",
    )

    class Meta: 
        verbose_name = "Lectura de telemetría"
        verbose_name_plural = "Historial de telemetría"
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {self.device.name} - In: {self.vin}V | Out: {self.vout}V | Load {self.load_pct}% | Mode: {self.mode}"

class PowerEvent(models.Model):

    """
    Auditoría de eventos críticos (cortes de luz, restauraciones, desconexiones).
    """


    EVENT_TYPE_CHOICES = [
        ('battery_mode', 'Corte de luz'),
        ('grid_restored', 'Red eléctrica restaurada'),
        ('esp_disconnect', 'Pérdida de comunicacion con ESP32'),
        ('esp_reconnect', 'Reconexión con ESP32'),
        ('battery_low', 'Batería baja'),
        ('overload', 'Sobrecarga')
    ]

    SEVERITY_CHOICES = [
        ('info', 'Informativo'),
        ('warning', 'Advertencia'),
        ('critical', 'Crítico'),
        ('emergency', 'Emergencia')
    ]

    device = models.ForeignKey(
        UPSDevice, 
        on_delete=models.CASCADE, 
        related_name='events', 
        verbose_name="UPS"
    )

    event_type = models.CharField(
        max_length=50, 
        choices=EVENT_TYPE_CHOICES, 
        verbose_name="Tipo de evento"
    )
    
    severity = models.CharField(
        max_length=20, 
        choices=SEVERITY_CHOICES, 
        default='info', 
        verbose_name="Severidad"
    )
    
    started_at = models.DateTimeField(
        default=timezone.now, 
        verbose_name="Inicio"
    )

    ended_at = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fin / Restauración"
    )

    duration_seconds = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name="Duración (segundos)"
    )
    
    detail = models.TextField(
        verbose_name="Detalle del evento"
    )
    
    notified = models.BooleanField(
        default=False, 
        verbose_name="Notificación enviada"
    )

    class Meta: 
        verbose_name = "Evento eléctrico"
        verbose_name_plural = "Eventos de energía"
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.device.name} - {self.get_event_type_display()} ({self.started_at.strftime('%d/%m %H:%M')})"

    def save(self, *args, **kwargs):
        if self.started_at and self.ended_at:
            self.duration_seconds = int((self.ended_at - self.started_at).total_seconds())
        super().save(*args, **kwargs)

class AlertConfig(models.Model):
    """
    Configuración de alertas y credenciales (ej. Telegram).
    """
    device = models.OneToOneField(UPSDevice, on_delete=models.CASCADE, null=True, blank=True, related_name='alert_config', verbose_name="UPS (Vacío = Configuración Global)")
    
    telegram_bot_token = models.CharField(
        max_length=150, 
        blank=True, 
        verbose_name="Telegram Bot Token"
    )

    telegram_chat_id = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name="Telegram Chat ID"
    )
    
    notify_on_battery = models.BooleanField(
        default=True, 
        verbose_name="Alertar en corte de luz"
    )

    notify_on_restore = models.BooleanField(
        default=True, 
        verbose_name="Alertar en restauración de red"
    )

    notify_on_offline = models.BooleanField(
        default=True, 
        verbose_name="Alerta de desconexión de ESP32"
        )
    
    voltage_min_alert = models.FloatField(
        default=100.0, 
        verbose_name="Voltaje Mínimo Alerta (V)"
    )

    voltage_max_alert = models.FloatField(
        default=135.0, 
        verbose_name="Voltaje Máximo Alerta (V)"
    )

    load_max_alert = models.FloatField(
        default=85.0, 
        verbose_name="Carga Máxima Alerta (%)"
    )

    class Meta:
        verbose_name = "Configuración de Alertas"
        verbose_name_plural = "Configuraciones de Alertas"

    def __str__(self):
        return f"Alertas {'Globales' if not self.device else f'para {self.device.name}'}"
