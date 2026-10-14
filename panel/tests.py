from datetime import timedelta
from django.utils import timezone
from django.test import TestCase, Client
from .models import UPSDevice, TelemetryLog, PowerEvent, AlertConfig

class ApiFlotaTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.device = UPSDevice.objects.create(
            name="UPS-Test-01",
            location="Sede Central",
            host="192.168.1.50",
            port="4196",
            status="online",
            battery_nominal=12.0,
            battery_voltage=13.2
        )
        TelemetryLog.objects.create(
            device=self.device,
            vin=120.5,
            vout=120.0,
            load_pct=42.0,
            frequency=60.0,
            battery_voltage=13.2,
            temperature=28.0,
            status_q1="00000000",
            mode="grid"
        )

    def test_api_flota_returns_devices(self):
        response = self.client.get('/api/flota/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['count'], 1)
        device_data = data['devices'][0]
        self.assertEqual(device_data['name'], 'UPS-Test-01')
        self.assertEqual(device_data['status'], 'online')
        self.assertEqual(device_data['load'], 42)
        print("\n[TEST OK] /api/flota/ response:", data)


class ApiTelemetriaLiveTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.device = UPSDevice.objects.create(
            name="UPS-Servidores-01",
            location="Sala de Servidores",
            host="192.168.1.50",
            port="4196",
            status="online",
            battery_nominal=12.0,
            battery_voltage=13.5
        )
        self.log = TelemetryLog.objects.create(
            device=self.device,
            vin=121.2,
            vout=120.0,
            load_pct=45.5,
            frequency=60.1,
            battery_voltage=13.5,
            temperature=29.2,
            status_q1="10000000",  # Bit 0 activo: utility_fail
            mode="battery"
        )

    def test_telemetria_by_device_id(self):
        response = self.client.get(f'/api/dispositivos/{self.device.id}/telemetria/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device']['name'], "UPS-Servidores-01")
        self.assertIsNotNone(data['telemetry'])
        self.assertEqual(data['telemetry']['vin'], 121.2)
        self.assertEqual(data['telemetry']['vout'], 120.0)
        self.assertEqual(data['telemetry']['load'], 45.5)
        self.assertTrue(data['telemetry']['on_battery'])
        self.assertTrue(data['telemetry']['q1_bits']['utility_fail'])
        self.assertFalse(data['telemetry']['q1_bits']['battery_low'])
        print("\n[TEST OK] /api/dispositivos/<id>/telemetria/ response:", data)

    def test_telemetria_live_default(self):
        response = self.client.get('/api/telemetria/live/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device']['id'], self.device.id)

    def test_telemetria_live_query_param(self):
        response = self.client.get(f'/api/telemetria/live/?device_id={self.device.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device']['id'], self.device.id)

    def test_telemetria_device_not_found(self):
        response = self.client.get('/api/dispositivos/9999/telemetria/')
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertIn("no encontrado", data['error'])


class ApiHistoricoTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.device = UPSDevice.objects.create(
            name="UPS-Hist-01",
            location="Planta Principal",
            host="192.168.1.52",
            port="4196",
            status="online",
            battery_nominal=12.0,
            battery_voltage=13.0
        )
        now = timezone.now()
        # Generar 5 registros espaciados
        for i in range(5):
            TelemetryLog.objects.create(
                device=self.device,
                timestamp=now - timedelta(minutes=i * 10),
                vin=120.0 + i,
                vout=120.0,
                load_pct=30.0 + i * 2,
                frequency=60.0,
                battery_voltage=13.0,
                temperature=25.0 + i,
                status_q1="00000000",
                mode="grid"
            )

    def test_historico_returns_series_and_stats(self):
        response = self.client.get(f'/api/dispositivos/{self.device.id}/historico/?range=1h')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['range'], '1h')
        self.assertGreater(data['count'], 0)
        self.assertIn('labels', data['data'])
        self.assertIn('vin', data['data'])
        self.assertIn('vout', data['data'])
        self.assertIn('load', data['data'])
        self.assertIn('temp', data['data'])
        self.assertIn('battery', data['data'])
        self.assertIn('stats', data)
        self.assertIn('voltage', data['stats'])
        self.assertIn('load', data['stats'])
        print("\n[TEST OK] /api/historico/ response:", data)

    def test_historico_default_device(self):
        response = self.client.get('/api/historico/?range=24h')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device_id'], self.device.id)

    def test_historico_not_found(self):
        response = self.client.get('/api/dispositivos/9999/historico/')
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['ok'])


class ApiEventosTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.device = UPSDevice.objects.create(
            name="UPS-Event-01",
            location="Sala de Control",
            host="192.168.1.60",
            port="4196",
            status="online"
        )
        now = timezone.now()
        # Evento 1: Modo batería
        self.ev1 = PowerEvent.objects.create(
            device=self.device,
            event_type='battery_mode',
            severity='critical',
            started_at=now - timedelta(hours=1),
            ended_at=now - timedelta(minutes=45),
            duration_seconds=900,
            detail="Corte en la red eléctrica"
        )
        # Evento 2: Desconexión ESP32
        self.ev2 = PowerEvent.objects.create(
            device=self.device,
            event_type='esp_disconnect',
            severity='warning',
            started_at=now - timedelta(minutes=20),
            ended_at=now - timedelta(minutes=18),
            duration_seconds=120,
            detail="Pérdida de comunicación serial"
        )

    def test_get_eventos_list(self):
        response = self.client.get('/api/eventos/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['total'], 2)
        self.assertEqual(len(data['events']), 2)
        print("\n[TEST OK] /api/eventos/ response:", data)

    def test_filter_by_category_battery(self):
        response = self.client.get('/api/eventos/?tipo=battery')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['events'][0]['event_type'], 'battery_mode')
        self.assertEqual(data['events'][0]['tipo'], 'battery')

    def test_filter_by_category_comm(self):
        response = self.client.get('/api/eventos/?tipo=comm')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['events'][0]['event_type'], 'esp_disconnect')
        self.assertEqual(data['events'][0]['tipo'], 'comm')

    def test_post_crear_evento(self):
        now_str = timezone.now().isoformat()
        payload = {
            'device_id': self.device.id,
            'event_type': 'battery_mode',
            'severity': 'critical',
            'started_at': now_str,
            'detail': 'Corte simulado desde prueba automatizada'
        }
        response = self.client.post('/api/eventos/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['event']['device_id'], self.device.id)
        self.assertEqual(data['event']['detalle'], 'Corte simulado desde prueba automatizada')
        # Verificar persistencia en base de datos
        self.assertEqual(PowerEvent.objects.count(), 3)


class ApiDispositivosTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.device = UPSDevice.objects.create(
            name="UPS-Planta-01",
            location="Planta Principal",
            host="192.168.10.100",
            port="7660",
            status="online",
            battery_nominal=12.0,
            battery_voltage=12.6,
            is_active=True
        )

    def test_get_dispositivos_list(self):
        response = self.client.get('/api/dispositivos/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['devices'][0]['name'], "UPS-Planta-01")
        self.assertEqual(data['devices'][0]['host'], "192.168.10.100")

    def test_get_dispositivo_detail(self):
        response = self.client.get(f'/api/dispositivos/{self.device.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device']['name'], "UPS-Planta-01")
        self.assertIn('alert_config', data['device'])

    def test_get_dispositivo_not_found(self):
        response = self.client.get('/api/dispositivos/9999/')
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['ok'])

    def test_post_create_dispositivo_success(self):
        payload = {
            'name': 'UPS-Subestacion-Norte',
            'location': 'Subestación Norte',
            'host': '192.168.10.101',
            'port': '7660',
            'battery_nominal': 24.0,
            'vmin': 105.0,
            'vmax': 130.0
        }
        response = self.client.post('/api/dispositivos/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device']['name'], 'UPS-Subestacion-Norte')
        self.assertEqual(data['device']['battery_nominal'], 24.0)

        # Verificar creación en DB y su AlertConfig
        created = UPSDevice.objects.filter(name='UPS-Subestacion-Norte').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.alert_config.voltage_min_alert, 105.0)
        self.assertEqual(created.alert_config.voltage_max_alert, 130.0)

    def test_post_create_dispositivo_validation_error(self):
        # Falta host
        payload = {
            'name': 'UPS-Incompleta',
            'location': 'Sin IP'
        }
        response = self.client.post('/api/dispositivos/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['ok'])

    def test_patch_update_dispositivo(self):
        payload = {
            'name': 'UPS-Planta-Modificada',
            'location': 'Nuevo Taller',
            'port': '8000',
            'vmin': 102.0,
            'vmax': 132.0
        }
        response = self.client.patch(f'/api/dispositivos/{self.device.id}/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['device']['name'], 'UPS-Planta-Modificada')
        self.assertEqual(data['device']['location'], 'Nuevo Taller')
        self.assertEqual(data['device']['port'], '8000')

        # Verificar persistencia en DB
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, 'UPS-Planta-Modificada')
        self.assertEqual(self.device.port, '8000')
        self.assertEqual(self.device.alert_config.voltage_min_alert, 102.0)

    def test_delete_dispositivo_permanent(self):
        response = self.client.delete(f'/api/dispositivos/{self.device.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(UPSDevice.objects.filter(id=self.device.id).count(), 0)

    def test_delete_dispositivo_soft(self):
        response = self.client.delete(f'/api/dispositivos/{self.device.id}/?soft=true')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_active)


class ApiAlertConfigTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.device = UPSDevice.objects.create(
            name="UPS-Alert-01",
            location="Centro de Datos",
            host="192.168.20.10",
            port="7660",
            status="online"
        )

    def test_get_global_alert_config(self):
        response = self.client.get('/api/alertas/config/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIsNone(data['config']['device_id'])
        self.assertEqual(data['config']['device_name'], 'Global')

    def test_get_device_alert_config(self):
        response = self.client.get(f'/api/dispositivos/{self.device.id}/alertas/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['config']['device_id'], self.device.id)

    def test_post_update_global_alert_config(self):
        payload = {
            'telegram_bot_token': '123456789:ABCdefGHI',
            'telegram_chat_id': '-100987654321',
            'notify_on_battery': True,
            'notify_on_restore': True,
            'voltage_min_alert': 108.0,
            'voltage_max_alert': 128.0,
            'load_max_alert': 75.0
        }
        response = self.client.post('/api/alertas/config/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['config']['telegram_bot_token'], '123456789:ABCdefGHI')
        self.assertEqual(data['config']['voltage_min_alert'], 108.0)

        # Verificar en base de datos
        global_cfg = AlertConfig.objects.filter(device=None).first()
        self.assertIsNotNone(global_cfg)
        self.assertEqual(global_cfg.telegram_chat_id, '-100987654321')
        self.assertEqual(global_cfg.load_max_alert, 75.0)

    def test_post_update_device_alert_config(self):
        payload = {
            'voltage_min_alert': 110.0,
            'voltage_max_alert': 125.0,
            'notify_on_offline': True
        }
        response = self.client.post(f'/api/dispositivos/{self.device.id}/alertas/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['config']['voltage_min_alert'], 110.0)

        # Verificar en base de datos
        dev_cfg = AlertConfig.objects.filter(device=self.device).first()
        self.assertIsNotNone(dev_cfg)
        self.assertEqual(dev_cfg.voltage_max_alert, 125.0)



