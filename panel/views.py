import json
from datetime import datetime, timedelta
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.utils import timezone
from django.db.models import Q
from .models import UPSDevice, TelemetryLog, PowerEvent, AlertConfig


@ensure_csrf_cookie
def dashboard(request):
    """
    Vista principal que renderiza el panel de monitoreo Centinela.
    """
    return render(request, 'panel/centinela.html')


@csrf_exempt
def api_login(request):
    """
    Endpoint para autenticación de usuarios (Admin o Supervisor).
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    try:
        # Permite recibir tanto JSON como form-data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
        else:
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '').strip()

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                return JsonResponse({'ok': False, 'error': 'El usuario está desactivado.'}, status=403)

            login(request, user)
            is_admin = bool(user.is_superuser or user.is_staff)

            return JsonResponse({
                'ok': True,
                'user': {
                    'username': user.username,
                    'name': user.first_name or user.username,
                    'role': 'Administrador' if is_admin else 'Supervisor',
                    'is_admin': is_admin,
                }
            })
        else:
            return JsonResponse({'ok': False, 'error': 'Usuario o contraseña incorrectos.'}, status=401)

    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'Error en el servidor: {str(e)}'}, status=500)


def api_logout(request):
    """
    Cierra la sesión del usuario actual.
    """
    logout(request)
    return JsonResponse({'ok': True})


def api_me(request):
    """
    Retorna la información del usuario autenticado actualmente.
    """
    if request.user.is_authenticated:
        is_admin = bool(request.user.is_superuser or request.user.is_staff)
        return JsonResponse({
            'authenticated': True,
            'user': {
                'username': request.user.username,
                'name': request.user.first_name or request.user.username,
                'role': 'Administrador' if is_admin else 'Supervisor',
                'is_admin': is_admin,
            }
        })
    return JsonResponse({'authenticated': False})


def calculate_battery_pct(battery_voltage, battery_nominal):
    """
    Estima el porcentaje de carga de la batería (0-100%).
    
    El protocolo Megatec Q1 envía la batería como 'Voltios por Celda' (ej. 2.28V - 2.31V/celda).
    Una celda de plomo-ácido tiene:
    - 2.27V a 2.30V/celda = 100% (voltaje de flotación conectada a la red)
    - 2.00V/celda = ~50% (voltaje nominal en reposo)
    - 1.75V/celda = 0% (voltaje de corte/descarga profunda)
    
    Esta función detecta automáticamente si el valor es por celda (<= 3.5V) o del banco total (> 3.5V)
    y calcula el porcentaje real sobre la curva de descarga física.
    """
    if not battery_voltage or not battery_nominal or battery_nominal <= 0:
        return None

    if battery_voltage <= 3.5:
        # Medición por celda (estándar protocolo Megatec Q1, 2.30V = 100%)
        v_min_cell = 1.75
        v_max_cell = 2.30
        pct = round(((battery_voltage - v_min_cell) / (v_max_cell - v_min_cell)) * 100)
    else:
        # Medición por banco total
        num_cells = max(1, round(battery_nominal / 2.0))
        v_min_pack = num_cells * 1.75
        v_max_pack = num_cells * 2.30
        pct = round(((battery_voltage - v_min_pack) / (v_max_pack - v_min_pack)) * 100)

    return int(min(100, max(0, pct)))


def decode_q1_status(status_q1: str) -> dict:
    """Decodifica los 8 bits del protocolo Megatec (Q1)."""
    q1 = (status_q1 or "").ljust(8, '0')[:8]
    return {
        'utility_fail': q1[0] == '1',
        'battery_low': q1[1] == '1',
        'bypass_boost': q1[2] == '1',
        'ups_failed': q1[3] == '1',
        'standby': q1[4] == '1',
        'test_in_progress': q1[5] == '1',
        'shutdown_active': q1[6] == '1',
        'beeper_on': q1[7] == '1',
    }


def api_flota(request):
    """
    [API REST 1] Retorna el inventario de UPS registradas en la base de datos
    con su estado actual, última lectura de carga y voltaje de batería.
    """
    devices = UPSDevice.objects.filter(is_active=True).order_by('id')
    data = []

    now = timezone.now()
    for d in devices:
        last_log = TelemetryLog.objects.filter(device=d).order_by('-timestamp').first()
        is_off = (d.status == 'offline')

        battery_pct = (calculate_battery_pct(d.battery_voltage, d.battery_nominal) or 0) if not is_off else 0
        load_pct = (round(last_log.load_pct) if last_log and last_log.load_pct is not None else 0) if not is_off else 0
        bat_volts = d.battery_voltage if not is_off else 0.0

        status_since = d.status_changed_at or d.last_seen or d.created_at or now
        status_dur_secs = int(max(0, (now - status_since).total_seconds()))

        data.append({
            'id': d.id,
            'name': d.name,
            'loc': d.location,
            'host': d.host,
            'port': d.port,
            'status': d.status,
            'status_changed_at': timezone.localtime(status_since).isoformat() if status_since else None,
            'status_duration_seconds': status_dur_secs,
            'battery': battery_pct,
            'battery_voltage': bat_volts,
            'load': load_pct,
            'last_seen': timezone.localtime(d.last_seen).isoformat() if d.last_seen else None,
            'alert': d.status == 'offline' or (battery_pct is not None and battery_pct < 20) or d.status == 'battery',
            'is_active': d.is_active,
        })

    return JsonResponse({
        'ok': True,
        'count': len(data),
        'devices': data
    })


def api_TelemetryDevice(request, device_id=None):
    """
    [API REST 2] Retorna el estado en vivo y la última telemetría detallada
    de un dispositivo UPS específico (o del primero activo si no se indica ID).
    Permite alimentar directamente los tacómetros, estados y protocolo Megatec (Q1).
    """
    if device_id is None:
        raw_id = request.GET.get('device_id')
        if raw_id:
            try:
                device_id = int(raw_id)
            except ValueError:
                return JsonResponse({'ok': False, 'error': 'El parámetro device_id debe ser un entero.'}, status=400)

    if device_id:
        device = UPSDevice.objects.filter(id=device_id).first()
    else:
        device = UPSDevice.objects.filter(is_active=True).first()

    if not device:
        return JsonResponse({'ok': False, 'error': 'Dispositivo no encontrado.'}, status=404)

    last_log = TelemetryLog.objects.filter(device=device).order_by('-timestamp').first()

    effective_voltage = last_log.battery_voltage if last_log and last_log.battery_voltage else device.battery_voltage
    battery_pct = calculate_battery_pct(effective_voltage, device.battery_nominal)

    now = timezone.now()
    status_since = device.status_changed_at or device.last_seen or device.created_at or now
    status_dur_secs = int(max(0, (now - status_since).total_seconds()))

    telemetry_data = None
    if device.status == 'offline':
        # Si la UPS está desconectada/sin comunicación con el ESP32, todas las mediciones en vivo pasan a 0
        telemetry_data = {
            'timestamp': timezone.localtime(now).isoformat(),
            'vin': 0.0,
            'vin_fault': 0.0,
            'vout': 0.0,
            'hz': 0.0,
            'load': 0.0,
            'battery_voltage': 0.0,
            'battery_pct': 0,
            'temp': 0.0,
            'mode': 'offline',
            'on_battery': False,
            'status': 'offline',
            'status_changed_at': timezone.localtime(status_since).isoformat() if status_since else None,
            'status_duration_seconds': status_dur_secs,
            'status_q1': '00000000',
            'q1_bits': decode_q1_status('00000000'),
        }
    elif last_log:
        on_battery = (last_log.mode == 'battery') or (device.status == 'battery')
        telemetry_data = {
            'timestamp': timezone.localtime(last_log.timestamp).isoformat() if last_log and last_log.timestamp else timezone.localtime(now).isoformat(),
            'vin': round(last_log.vin, 1),
            'vin_fault': round(last_log.vin_fault, 1),
            'vout': round(last_log.vout, 1),
            'hz': round(last_log.frequency, 1),
            'load': round(last_log.load_pct, 1),
            'battery_voltage': round(effective_voltage, 2) if effective_voltage else None,
            'battery_pct': battery_pct,
            'temp': round(last_log.temperature, 1),
            'mode': last_log.mode,
            'on_battery': on_battery,
            'status': device.status,
            'status_changed_at': timezone.localtime(status_since).isoformat() if status_since else None,
            'status_duration_seconds': status_dur_secs,
            'status_q1': last_log.status_q1,
            'q1_bits': decode_q1_status(last_log.status_q1),
        }
    else:
        # Aunque aún no haya logs históricos, enviar datos mínimos en cero
        telemetry_data = {
            'timestamp': timezone.localtime(now).isoformat(),
            'vin': 0.0,
            'vin_fault': 0.0,
            'vout': 0.0,
            'hz': 0.0,
            'load': 0.0,
            'battery_voltage': 0.0,
            'battery_pct': 0,
            'temp': 0.0,
            'mode': 'grid' if device.status == 'online' else ('battery' if device.status == 'battery' else 'offline'),
            'on_battery': device.status == 'battery',
            'status': device.status,
            'status_changed_at': timezone.localtime(status_since).isoformat() if status_since else None,
            'status_duration_seconds': status_dur_secs,
            'status_q1': '00000000',
            'q1_bits': decode_q1_status('00000000'),
        }

    return JsonResponse({
        'ok': True,
        'device': {
            'id': device.id,
            'name': device.name,
            'location': device.location,
            'host': device.host,
            'port': device.port,
            'status': device.status,
            'status_changed_at': timezone.localtime(status_since).isoformat() if status_since else None,
            'status_duration_seconds': status_dur_secs,
            'is_active': device.is_active,
            'battery_nominal': device.battery_nominal,
            'battery_voltage': device.battery_voltage,
            'battery_pct': battery_pct,
            'last_seen': timezone.localtime(device.last_seen).isoformat() if device.last_seen else None,
            'created_at': timezone.localtime(device.created_at).isoformat() if device.created_at else None,
        },
        'telemetry': telemetry_data
    })


def api_Historico(request, device_id=None):
    """
    [API REST 3] Retorna series temporales históricas agregadas y estadísticas
    para alimentar las 4 gráficas de Chart.js (Voltaje, Carga, Temperatura, Batería).
    Soporta rangos: '1h', '24h', '7d', '30d'.
    Aplica submuestreo homogéneo (downsampling) para optimizar el rendimiento del navegador.
    """
    if device_id is None:
        raw_id = request.GET.get('device_id')
        if raw_id:
            try:
                device_id = int(raw_id)
            except ValueError:
                return JsonResponse({'ok': False, 'error': 'El parámetro device_id debe ser un entero.'}, status=400)

    if device_id:
        device = UPSDevice.objects.filter(id=device_id).first()
    else:
        device = UPSDevice.objects.filter(is_active=True).first()

    if not device:
        return JsonResponse({'ok': False, 'error': 'Dispositivo no encontrado.'}, status=404)

    range_code = request.GET.get('range', '1h').lower().strip()
    range_deltas = {
        '1h': timedelta(hours=1),
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30),
    }
    target_points_map = {
        '1h': 30,
        '24h': 24,
        '7d': 14,
        '30d': 30,
    }

    delta = range_deltas.get(range_code, timedelta(hours=1))
    target_points = target_points_map.get(range_code, 30)

    # Punto de referencia temporal
    last_log = TelemetryLog.objects.filter(device=device).order_by('-timestamp').first()
    if not last_log:
        return JsonResponse({
            'ok': True,
            'device_id': device.id,
            'range': range_code,
            'count': 0,
            'data': {'labels': [], 'vin': [], 'vout': [], 'load': [], 'temp': [], 'battery': []},
            'stats': {
                'voltage': {'min': 0, 'avg': 0, 'max': 0},
                'load': {'min': 0, 'avg': 0, 'max': 0},
                'temp': {'min': 0, 'avg': 0, 'max': 0},
                'battery': {'min': 0, 'avg': 0, 'max': 0},
            }
        })

    now = timezone.now()
    # Si la ventana absoluta reciente tiene pocos datos (ej. equipo inactivo o reconectando),
    # anclar la ventana temporal al último registro real para mostrar la curva histórica completa
    recent_count = TelemetryLog.objects.filter(device=device, timestamp__gte=now - delta).count()
    if recent_count < 5:
        ref_time = last_log.timestamp
    else:
        ref_time = now

    start_time = ref_time - delta

    logs_qs = (
        TelemetryLog.objects.filter(
            device=device,
            timestamp__gte=start_time,
            timestamp__lte=ref_time
        )
        .order_by('timestamp')
        .values('timestamp', 'vin', 'vout', 'load_pct', 'temperature', 'battery_voltage')
    )

    total_records = logs_qs.count()
    if total_records == 0:
        # Fallback a los últimos registros disponibles
        logs_qs = (
            TelemetryLog.objects.filter(device=device)
            .order_by('-timestamp')[:target_points]
            .values('timestamp', 'vin', 'vout', 'load_pct', 'temperature', 'battery_voltage')
        )
        logs = list(reversed(list(logs_qs)))
    else:
        logs = list(logs_qs)

    n = len(logs)

    # Submuestreo por cubetas (Bucketing / Averaging)
    labels = []
    vin_series = []
    vout_series = []
    load_series = []
    temp_series = []
    battery_series = []

    if n <= target_points:
        buckets = [[p] for p in logs]
    else:
        step = n / target_points
        buckets = []
        for i in range(target_points):
            start_idx = int(i * step)
            end_idx = int((i + 1) * step) if i < target_points - 1 else n
            if start_idx < end_idx:
                buckets.append(logs[start_idx:end_idx])

    for bucket in buckets:
        if not bucket:
            continue
        mid_point = bucket[len(bucket) // 2]
        ts = mid_point['timestamp']
        ts_local = timezone.localtime(ts) if timezone.is_aware(ts) else ts

        # Formato de etiqueta según el rango en hora local de Colombia
        if range_code == '1h':
            label = ts_local.strftime('%H:%M')
        elif range_code == '24h':
            label = ts_local.strftime('%H:%M')
        elif range_code == '7d':
            label = ts_local.strftime('%a %H:%M')
        else:
            label = ts_local.strftime('%d/%m')

        v_in = round(sum(p['vin'] for p in bucket) / len(bucket), 1)
        v_out = round(sum(p['vout'] for p in bucket) / len(bucket), 1)
        load = round(sum(p['load_pct'] for p in bucket) / len(bucket), 1)
        temp = round(sum(p['temperature'] for p in bucket) / len(bucket), 1)
        v_bat = sum(p['battery_voltage'] for p in bucket) / len(bucket)
        bat_pct = calculate_battery_pct(v_bat, device.battery_nominal) or round(v_bat, 1)

        labels.append(label)
        vin_series.append(v_in)
        vout_series.append(v_out)
        load_series.append(load)
        temp_series.append(temp)
        battery_series.append(bat_pct)

    # Cálculo de estadísticas globales consolidadas
    voltages = vin_series + vout_series
    stats = {
        'voltage': {
            'min': round(min(voltages), 1) if voltages else 0,
            'avg': round(sum(voltages) / len(voltages), 1) if voltages else 0,
            'max': round(max(voltages), 1) if voltages else 0,
        },
        'load': {
            'min': round(min(load_series), 1) if load_series else 0,
            'avg': round(sum(load_series) / len(load_series), 1) if load_series else 0,
            'max': round(max(load_series), 1) if load_series else 0,
        },
        'temp': {
            'min': round(min(temp_series), 1) if temp_series else 0,
            'avg': round(sum(temp_series) / len(temp_series), 1) if temp_series else 0,
            'max': round(max(temp_series), 1) if temp_series else 0,
        },
        'battery': {
            'min': round(min(battery_series), 1) if battery_series else 0,
            'avg': round(sum(battery_series) / len(battery_series), 1) if battery_series else 0,
            'max': round(max(battery_series), 1) if battery_series else 0,
        }
    }

    return JsonResponse({
        'ok': True,
        'device_id': device.id,
        'range': range_code,
        'count': len(labels),
        'total_records': n,
        'data': {
            'labels': labels,
            'vin': vin_series,
            'vout': vout_series,
            'load': load_series,
            'temp': temp_series,
            'battery': battery_series
        },
        'stats': stats
    })


def format_event_duration(seconds):
    """Retorna una cadena legible para la duración del evento (ej. '14m 20s' o 'En curso')."""
    if seconds is None:
        return 'En curso'
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    rem_seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {rem_seconds}s" if rem_seconds > 0 else f"{minutes}m"
    hours = minutes // 60
    rem_minutes = minutes % 60
    return f"{hours}h {rem_minutes}m"


def map_event_category(event_type, severity):
    """Mapea el tipo de evento a la clase CSS utilizada por el frontend ('battery', 'comm', 'info')."""
    if event_type in ('battery_mode', 'battery_low') or severity in ('critical', 'emergency'):
        return 'battery'
    elif event_type in ('esp_disconnect', 'esp_reconnect'):
        return 'comm'
    else:
        return 'info'


@csrf_exempt
def api_Eventos(request, device_id=None):
    """
    [API REST 4] Retorna y gestiona el registro de auditoría de eventos de energía (PowerEvent).
    Soporta:
    - GET: Listar eventos filtrados por dispositivo, categoría ('todos', 'battery', 'comm', 'info') y límite.
    - POST: Registrar manualmente o mediante simulación un nuevo incidente eléctrico.
    """
    if request.method == 'POST':
        try:
            if request.content_type == 'application/json':
                body = json.loads(request.body)
            else:
                body = request.POST

            target_dev_id = body.get('device_id') or device_id
            if target_dev_id:
                dev = UPSDevice.objects.filter(id=target_dev_id).first()
            else:
                dev = UPSDevice.objects.filter(is_active=True).first()

            if not dev:
                return JsonResponse({'ok': False, 'error': 'Dispositivo no encontrado.'}, status=404)

            event_type = body.get('event_type', 'battery_mode')
            severity = body.get('severity', 'critical' if event_type == 'battery_mode' else 'info')
            detail = body.get('detail', 'Evento registrado desde el panel de control')

            started_at = body.get('started_at')
            ended_at = body.get('ended_at')

            ev = PowerEvent(
                device=dev,
                event_type=event_type,
                severity=severity,
                detail=detail
            )
            if started_at:
                ev.started_at = datetime.fromisoformat(started_at)
            if ended_at:
                ev.ended_at = datetime.fromisoformat(ended_at)
                ev.duration_seconds = int((ev.ended_at - ev.started_at).total_seconds())

            ev.save()

            return JsonResponse({
                'ok': True,
                'event': {
                    'id': ev.id,
                    'device_id': dev.id,
                    'device_name': dev.name,
                    'event_type': ev.event_type,
                    'label': ev.get_event_type_display(),
                    'severity': ev.severity,
                    'tipo': map_event_category(ev.event_type, ev.severity),
                    'inicio': ev.started_at.isoformat(),
                    'fin': ev.ended_at.isoformat() if ev.ended_at else None,
                    'dur': format_event_duration(ev.duration_seconds),
                    'duration_seconds': ev.duration_seconds,
                    'detalle': ev.detail
                }
            }, status=201)
        except Exception as e:
            return JsonResponse({'ok': False, 'error': f'Error creando evento: {str(e)}'}, status=400)

    # Método GET: Listado
    if device_id is None:
        raw_id = request.GET.get('device_id')
        if raw_id:
            try:
                device_id = int(raw_id)
            except ValueError:
                return JsonResponse({'ok': False, 'error': 'El parámetro device_id debe ser un entero.'}, status=400)

    events_qs = PowerEvent.objects.select_related('device').all()
    if device_id:
        events_qs = events_qs.filter(device_id=device_id)

    filter_type = request.GET.get('tipo', request.GET.get('filter', 'todos')).lower().strip()
    if filter_type == 'battery':
        events_qs = events_qs.filter(Q(event_type__in=['battery_mode', 'battery_low']) | Q(severity__in=['critical', 'emergency']))
    elif filter_type == 'comm':
        events_qs = events_qs.filter(event_type__in=['esp_disconnect', 'esp_reconnect'])
    elif filter_type == 'info':
        events_qs = events_qs.filter(Q(event_type__in=['grid_restored', 'overload']) | Q(severity='info'))

    try:
        limit = int(request.GET.get('limit', 50))
    except ValueError:
        limit = 50

    total_count = events_qs.count()
    events_list = events_qs.order_by('-started_at')[:limit]

    data = []
    for e in events_list:
        data.append({
            'id': e.id,
            'device_id': e.device_id,
            'device_name': e.device.name,
            'event_type': e.event_type,
            'label': e.get_event_type_display(),
            'tipo': map_event_category(e.event_type, e.severity),
            'severity': e.severity,
            'inicio': timezone.localtime(e.started_at).isoformat() if e.started_at else None,
            'fin': timezone.localtime(e.ended_at).isoformat() if e.ended_at else None,
            'dur': format_event_duration(e.duration_seconds),
            'duration_seconds': e.duration_seconds,
            'detalle': e.detail,
            'notified': e.notified,
        })

    return JsonResponse({
        'ok': True,
        'count': len(data),
        'total': total_count,
        'filter': filter_type,
        'events': data
    })


def serialize_alert_config(config):
    """Serializa la configuración de alertas en un diccionario JSON."""
    if not config:
        return None
    return {
        'id': config.id,
        'device_id': config.device_id,
        'device_name': config.device.name if config.device else 'Global',
        'telegram_bot_token': config.telegram_bot_token,
        'telegram_chat_id': config.telegram_chat_id,
        'notify_on_battery': config.notify_on_battery,
        'notify_on_restore': config.notify_on_restore,
        'notify_on_offline': config.notify_on_offline,
        'voltage_min_alert': config.voltage_min_alert,
        'voltage_max_alert': config.voltage_max_alert,
        'load_max_alert': config.load_max_alert,
    }


def serialize_device(device, include_config=True):
    """Serializa un modelo UPSDevice para respuestas JSON del catálogo."""
    alert_cfg = None
    if include_config:
        try:
            alert_cfg = serialize_alert_config(getattr(device, 'alert_config', None))
        except Exception:
            alert_cfg = None

    return {
        'id': device.id,
        'name': device.name,
        'location': device.location,
        'loc': device.location,
        'host': device.host,
        'port': str(device.port),
        'status': device.status,
        'is_active': device.is_active,
        'battery_nominal': device.battery_nominal,
        'battery_voltage': device.battery_voltage,
        'battery_pct': calculate_battery_pct(device.battery_voltage, device.battery_nominal),
        'last_seen': timezone.localtime(device.last_seen).isoformat() if device.last_seen else None,
        'created_at': timezone.localtime(device.created_at).isoformat() if device.created_at else None,
        'alert_config': alert_cfg
    }


@csrf_exempt
def api_Dispositivos(request, device_id=None):
    """
    [API REST 5] Gestión completa de dispositivos UPS (CRUD).
    - GET /api/dispositivos/ : Listar todos los dispositivos registrados.
    - GET /api/dispositivos/<id>/ : Consultar detalle y umbrales de un dispositivo.
    - POST /api/dispositivos/ : Registrar una nueva UPS en la base de datos.
    - PUT/PATCH /api/dispositivos/<id>/ : Actualizar parámetros (nombre, IP, puerto, umbrales).
    - DELETE /api/dispositivos/<id>/ : Eliminar o desactivar una UPS.
    """
    if device_id is None:
        raw_id = request.GET.get('device_id')
        if raw_id:
            try:
                device_id = int(raw_id)
            except ValueError:
                return JsonResponse({'ok': False, 'error': 'El parámetro device_id debe ser un entero.'}, status=400)

    # 1. GET: Consulta individual o listado
    if request.method == 'GET':
        if device_id is not None:
            dev = UPSDevice.objects.filter(id=device_id).first()
            if not dev:
                return JsonResponse({'ok': False, 'error': f'Dispositivo con ID {device_id} no encontrado.'}, status=404)
            return JsonResponse({'ok': True, 'device': serialize_device(dev)})

        active_only = request.GET.get('active_only', '').lower() in ('1', 'true', 'yes')
        qs = UPSDevice.objects.all()
        if active_only:
            qs = qs.filter(is_active=True)

        devices_list = [serialize_device(d) for d in qs.order_by('id')]
        return JsonResponse({
            'ok': True,
            'count': len(devices_list),
            'devices': devices_list
        })

    # 2. POST: Creación de nueva UPS
    elif request.method == 'POST':
        try:
            if request.content_type == 'application/json':
                body = json.loads(request.body)
            else:
                body = request.POST

            name = str(body.get('name', '')).strip()
            location = str(body.get('location', body.get('loc', ''))).strip()
            host = str(body.get('host', body.get('ip', ''))).strip()
            port = str(body.get('port', '7660')).strip()

            if not name:
                return JsonResponse({'ok': False, 'error': 'El nombre del equipo es obligatorio.'}, status=400)
            if not host:
                return JsonResponse({'ok': False, 'error': 'La dirección IP o host es obligatoria.'}, status=400)
            if not port.isdigit() or not (1 <= int(port) <= 65535):
                return JsonResponse({'ok': False, 'error': 'El puerto TCP debe ser un número entre 1 y 65535.'}, status=400)

            battery_nominal = float(body.get('battery_nominal', 12.0))
            is_active = bool(body.get('is_active', True))
            status = str(body.get('status', 'offline')).strip()

            dev = UPSDevice.objects.create(
                name=name,
                location=location,
                host=host,
                port=port,
                battery_nominal=battery_nominal,
                battery_voltage=battery_nominal,
                status=status,
                is_active=is_active
            )

            # Crear configuración de alertas vinculada por defecto o con valores provistos
            alert_cfg, _ = AlertConfig.objects.get_or_create(device=dev)
            vmin = body.get('vmin', body.get('voltage_min_alert'))
            vmax = body.get('vmax', body.get('voltage_max_alert'))
            load_max = body.get('load_max_alert')
            if vmin is not None:
                alert_cfg.voltage_min_alert = float(vmin)
            if vmax is not None:
                alert_cfg.voltage_max_alert = float(vmax)
            if load_max is not None:
                alert_cfg.load_max_alert = float(load_max)
            alert_cfg.save()

            return JsonResponse({
                'ok': True,
                'message': f"Dispositivo '{dev.name}' registrado exitosamente.",
                'device': serialize_device(dev)
            }, status=201)
        except Exception as e:
            return JsonResponse({'ok': False, 'error': f'Error al crear el dispositivo: {str(e)}'}, status=400)

    # 3. PUT / PATCH: Modificación de parámetros
    elif request.method in ('PUT', 'PATCH'):
        if device_id is None:
            return JsonResponse({'ok': False, 'error': 'Se requiere el ID del dispositivo a modificar.'}, status=400)

        dev = UPSDevice.objects.filter(id=device_id).first()
        if not dev:
            return JsonResponse({'ok': False, 'error': f'Dispositivo con ID {device_id} no encontrado.'}, status=404)

        try:
            if request.content_type == 'application/json':
                body = json.loads(request.body)
            else:
                body = request.POST

            if 'name' in body:
                dev.name = str(body['name']).strip()
            if 'location' in body or 'loc' in body:
                dev.location = str(body.get('location', body.get('loc'))).strip()
            if 'host' in body or 'ip' in body:
                dev.host = str(body.get('host', body.get('ip'))).strip()
            if 'port' in body:
                port_str = str(body['port']).strip()
                if port_str.isdigit() and 1 <= int(port_str) <= 65535:
                    dev.port = port_str
                else:
                    return JsonResponse({'ok': False, 'error': 'Puerto TCP no válido.'}, status=400)
            if 'battery_nominal' in body:
                dev.battery_nominal = float(body['battery_nominal'])
            if 'battery_voltage' in body:
                dev.battery_voltage = float(body['battery_voltage'])
            if 'status' in body:
                dev.status = str(body['status']).strip()
            if 'is_active' in body:
                dev.is_active = bool(body['is_active'])

            dev.save()

            # Umbrales de alerta y configuración en caso de ser enviados en la misma petición
            alert_cfg, _ = AlertConfig.objects.get_or_create(device=dev)
            updated_alert = False

            vmin = body.get('vmin', body.get('voltage_min_alert'))
            vmax = body.get('vmax', body.get('voltage_max_alert'))
            load_max = body.get('load_max_alert')
            if vmin is not None:
                alert_cfg.voltage_min_alert = float(vmin)
                updated_alert = True
            if vmax is not None:
                alert_cfg.voltage_max_alert = float(vmax)
                updated_alert = True
            if load_max is not None:
                alert_cfg.load_max_alert = float(load_max)
                updated_alert = True
            if 'telegram_bot_token' in body:
                alert_cfg.telegram_bot_token = str(body['telegram_bot_token']).strip()
                updated_alert = True
            if 'telegram_chat_id' in body:
                alert_cfg.telegram_chat_id = str(body['telegram_chat_id']).strip()
                updated_alert = True
            if 'notify_on_battery' in body:
                alert_cfg.notify_on_battery = bool(body['notify_on_battery'])
                updated_alert = True
            if 'notify_on_restore' in body:
                alert_cfg.notify_on_restore = bool(body['notify_on_restore'])
                updated_alert = True
            if 'notify_on_offline' in body:
                alert_cfg.notify_on_offline = bool(body['notify_on_offline'])
                updated_alert = True

            if updated_alert:
                alert_cfg.save()

            return JsonResponse({
                'ok': True,
                'message': f"Dispositivo '{dev.name}' actualizado exitosamente.",
                'device': serialize_device(dev)
            })
        except Exception as e:
            return JsonResponse({'ok': False, 'error': f'Error al actualizar el dispositivo: {str(e)}'}, status=400)

    # 4. DELETE: Eliminación física o lógica
    elif request.method == 'DELETE':
        if device_id is None:
            return JsonResponse({'ok': False, 'error': 'Se requiere el ID del dispositivo a eliminar.'}, status=400)

        dev = UPSDevice.objects.filter(id=device_id).first()
        if not dev:
            return JsonResponse({'ok': False, 'error': f'Dispositivo con ID {device_id} no encontrado.'}, status=404)

        soft = request.GET.get('soft', '').lower() in ('1', 'true', 'yes')
        if soft:
            dev.is_active = False
            dev.save()
            return JsonResponse({'ok': True, 'message': f"Dispositivo '{dev.name}' desactivado exitosamente."})
        else:
            name = dev.name
            dev.delete()
            return JsonResponse({'ok': True, 'message': f"Dispositivo '{name}' eliminado exitosamente."})

    return JsonResponse({'ok': False, 'error': f'Método {request.method} no permitido.'}, status=405)


@csrf_exempt
def api_AlertConfig(request, device_id=None):
    """
    [API REST 6] Consulta y configuración de alertas y credenciales (Telegram, umbrales).
    - GET /api/alertas/config/ : Obtener configuración global o por ?device_id=
    - GET /api/dispositivos/<id>/alertas/ : Obtener configuración de una UPS específica.
    - POST / PUT / PATCH /api/alertas/config/ : Guardar cambios en configuración de alertas.
    """
    if device_id is None:
        raw_id = request.GET.get('device_id')
        if raw_id:
            try:
                device_id = int(raw_id)
            except ValueError:
                return JsonResponse({'ok': False, 'error': 'El parámetro device_id debe ser un entero.'}, status=400)

    if request.method == 'GET':
        if device_id is not None:
            dev = UPSDevice.objects.filter(id=device_id).first()
            if not dev:
                return JsonResponse({'ok': False, 'error': f'Dispositivo con ID {device_id} no encontrado.'}, status=404)
            config, _ = AlertConfig.objects.get_or_create(device=dev)
        else:
            config, _ = AlertConfig.objects.get_or_create(device=None)

        return JsonResponse({
            'ok': True,
            'config': serialize_alert_config(config)
        })

    elif request.method in ('POST', 'PUT', 'PATCH'):
        try:
            if request.content_type == 'application/json':
                body = json.loads(request.body)
            else:
                body = request.POST

            target_dev_id = body.get('device_id') or device_id
            if target_dev_id:
                dev = UPSDevice.objects.filter(id=target_dev_id).first()
                if not dev:
                    return JsonResponse({'ok': False, 'error': 'Dispositivo no encontrado.'}, status=404)
                config, _ = AlertConfig.objects.get_or_create(device=dev)
            else:
                config, _ = AlertConfig.objects.get_or_create(device=None)

            if 'telegram_bot_token' in body:
                config.telegram_bot_token = str(body['telegram_bot_token']).strip()
            if 'telegram_chat_id' in body:
                config.telegram_chat_id = str(body['telegram_chat_id']).strip()
            if 'notify_on_battery' in body:
                config.notify_on_battery = bool(body['notify_on_battery'])
            if 'notify_on_restore' in body:
                config.notify_on_restore = bool(body['notify_on_restore'])
            if 'notify_on_offline' in body:
                config.notify_on_offline = bool(body['notify_on_offline'])

            vmin = body.get('voltage_min_alert', body.get('vmin'))
            vmax = body.get('voltage_max_alert', body.get('vmax'))
            load_max = body.get('load_max_alert')

            if vmin is not None:
                config.voltage_min_alert = float(vmin)
            if vmax is not None:
                config.voltage_max_alert = float(vmax)
            if load_max is not None:
                config.load_max_alert = float(load_max)

            config.save()

            return JsonResponse({
                'ok': True,
                'message': 'Configuración de alertas guardada exitosamente.',
                'config': serialize_alert_config(config)
            })
        except Exception as e:
            return JsonResponse({'ok': False, 'error': f'Error guardando configuración de alertas: {str(e)}'}, status=400)

    return JsonResponse({'ok': False, 'error': f'Método {request.method} no permitido.'}, status=405)




