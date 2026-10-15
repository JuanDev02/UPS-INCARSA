import socket
import json
import time
import threading
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import connection

from panel.models import UPSDevice, TelemetryLog, PowerEvent


# Constantes de conexión y latido (sincronizadas con el nuevo firmware del ESP32)
PING_INTERVAL = 15          # Segundos entre PING al ESP32
RESPONSE_TIMEOUT = 45       # Si el ESP32 no responde en este tiempo (ni PONG ni datos), reconectar
RECONNECT_DELAY = 3         # Segundos antes de reintentar conexión


def purge_old_telemetry(hours=24):
    """
    Elimina registros de TelemetryLog con antigüedad mayor a 24 horas.
    Garantiza que la base de datos solo conserve las lecturas del día actual (últimas 24h).
    """
    try:
        cutoff = timezone.now() - timedelta(hours=hours)
        deleted, _ = TelemetryLog.objects.filter(timestamp__lt=cutoff).delete()
        return deleted
    except Exception as e:
        print(f"[PURGE ERROR] No se pudo purgar telemetría antigua: {e}")
        return 0
    finally:
        connection.close()


# ==============================================================================
# 1. Clase Trabajadora (Worker por dispositivo)
# ==============================================================================

class UPSWorker(threading.Thread):
    """
    Hilo encargado de conectarse por TCP a un solo ESP32/UPS,
    leer su telemetría y guardar los datos en la base de datos de Django.
    """
    def __init__(self, device_id, name, host, port, time_connection=RECONNECT_DELAY, log_interval=60):
        super().__init__(daemon=True)
        self.device_id = device_id
        self.name = name
        self.host = host
        self.port = int(port)
        self.time_connection = time_connection
        self.log_interval = log_interval  # Guardar en TelemetryLog cada 60s por defecto

        self.stop_event = threading.Event()  # Indicador para pedir al hilo detenerse

        # Estados de la UPS y eventos
        self.battery_mode = False
        self.battery_start = None
        self.event_currentBattery = None
        self.event_currentDisconnect = None
        self.readings = 0
        self.last_telemetry_save = 0  # Timestamp del último registro guardado en TelemetryLog
        self.last_state_update = 0    # Timestamp de última actualización en UPSDevice
        self.last_cleanup = 0         # Timestamp de última purga de telemetría > 24h

    def log(self, message):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] [{self.name} @ {self.host}] {message}")

    def batteryMode_DETECTED(self, data):
        """Revisa si el bit 7 del protocolo Megatec está en 1 o si el voltaje cayó."""
        state = str(data.get("estado") or data.get("state", "00000000"))
        enter = float(data.get("entrada") or data.get("enter", 0))
        frequency = float(data.get("frecuencia") or data.get("frequency", 0))

        if len(state) == 8 and state[0] == "1":
            return True
        if enter <= 1 and frequency <= 1:
            return True
        return False

    def stateDevice_UPDATE(self, status, battery_voltage=None):
        try:
            device = UPSDevice.objects.filter(id=self.device_id).first()
            if device:
                update_fields = ["last_seen"]
                device.last_seen = timezone.now()
                if device.status != status:
                    device.status = status
                    device.status_changed_at = timezone.now()
                    update_fields.extend(["status", "status_changed_at"])
                elif not device.status_changed_at:
                    device.status_changed_at = timezone.now()
                    update_fields.append("status_changed_at")

                if battery_voltage is not None:
                    device.battery_voltage = battery_voltage
                    update_fields.append("battery_voltage")

                device.save(update_fields=list(set(update_fields)))
        except Exception as e:
            self.log(f"Error actualizando UPSDevice: {e}")
        finally:
            connection.close()

    def telemetry_SAVE(self, data):
        """Crea un nuevo registro en TelemetryLog y purga datos de más de 24 horas."""
        try:
            enter = float(data.get("entrada") or data.get("enter", 0))
            enter_fault = float(data.get("entrada_falla") or data.get("enter_fault", 0))
            exit_v = float(data.get("salida") or data.get("exit", 0))
            charge = float(data.get("campo4") or data.get("carga") or data.get("charge", 0))  # Carga en %
            frequency = float(data.get("frecuencia") or data.get("frequency", 0))
            battery = float(data.get("bateria") or data.get("battery", 0))
            temperature = float(data.get("temperatura") or data.get("temperature", 0))
            state_q1 = str(data.get("estado") or data.get("state", "00000000"))

            mode = 'battery' if self.battery_mode else 'grid'

            TelemetryLog.objects.create(
                device_id=self.device_id,
                vin=enter,
                vin_fault=enter_fault,
                vout=exit_v,
                load_pct=charge,
                frequency=frequency,
                battery_voltage=battery,
                temperature=temperature,
                status_q1=state_q1,
                mode=mode
            )

            self.stateDevice_UPDATE(
                status='battery' if self.battery_mode else 'online',
                battery_voltage=battery
            )

            # Purgar telemetrías con más de 24 horas (máxima retención de 1 día)
            now_ts = time.time()
            if now_ts - self.last_cleanup >= 300:  # Cada 5 minutos
                self.last_cleanup = now_ts
                purge_old_telemetry(hours=24)

        except Exception as e:
            self.log(f"Error guardando telemetría: {e}")
        finally:
            connection.close()

    def disconnectEvent_START(self, reason="Pérdida de enlace con el equipo"):
        """Registra el inicio de un evento de desconexión (esp_disconnect) con su marca de tiempo."""
        try:
            if not self.event_currentDisconnect:
                # Verificar si ya había un evento abierto en base de datos
                open_ev = PowerEvent.objects.filter(
                    device_id=self.device_id,
                    event_type='esp_disconnect',
                    ended_at__isnull=True
                ).order_by('-started_at').first()

                if open_ev:
                    self.event_currentDisconnect = open_ev
                else:
                    now = timezone.now()
                    self.event_currentDisconnect = PowerEvent.objects.create(
                        device_id=self.device_id,
                        event_type='esp_disconnect',
                        severity='warning',
                        started_at=now,
                        detail=f"Pérdida de conexión con {self.name} ({reason})."
                    )
                    self.log(f"[ALERTA] Evento registrado: Pérdida de conexión ({reason})")
        except Exception as e:
            self.log(f"Error registrando evento de desconexión: {e}")
        finally:
            connection.close()

    def disconnectEvent_END(self):
        """Cierra el evento de desconexión abierto calculando la duración exacta que estuvo desconectado."""
        try:
            ev = self.event_currentDisconnect
            if not ev:
                ev = PowerEvent.objects.filter(
                    device_id=self.device_id,
                    event_type='esp_disconnect',
                    ended_at__isnull=True
                ).order_by('-started_at').first()

            if ev:
                now = timezone.now()
                ev.ended_at = now
                if ev.started_at:
                    ev.duration_seconds = max(0, int((now - ev.started_at).total_seconds()))
                ev.save()
                self.log(f"[OK] Conexión restablecida. La desconexión duró {ev.duration_seconds}s.")
            self.event_currentDisconnect = None
        except Exception as e:
            self.log(f"Error finalizando evento de desconexión: {e}")
        finally:
            connection.close()

    def chanceEnergy_PROCCESS(self, new_batteryMode):
        """Detecta cortes de luz (modo batería) y restauraciones (red eléctrica) con sus tiempos correspondientes."""
        try:
            # 1. Red fuera -> entra en modo batería
            if new_batteryMode and not self.battery_mode:
                self.battery_mode = True
                self.battery_start = timezone.now()
                self.log("[ALERTA] ¡CORTE DE LUZ! UPS pasó a modo BATERÍA.")

                self.event_currentBattery = PowerEvent.objects.create(
                    device_id=self.device_id,
                    event_type='battery_mode',
                    severity='critical',
                    started_at=self.battery_start,
                    detail="Corte en la red eléctrica detectado. La UPS entró en modo batería."
                )

            # 2. Red volvió -> salió de modo batería (restauración)
            elif not new_batteryMode and self.battery_mode:
                self.battery_mode = False
                end = timezone.now()
                self.log("[OK] ¡ENERGÍA RESTAURADA! UPS volvió a red eléctrica.")

                dur_secs = 0
                if not self.event_currentBattery:
                    self.event_currentBattery = PowerEvent.objects.filter(
                        device_id=self.device_id,
                        event_type='battery_mode',
                        ended_at__isnull=True
                    ).order_by('-started_at').first()

                if self.event_currentBattery:
                    self.event_currentBattery.ended_at = end
                    if self.event_currentBattery.started_at:
                        dur_secs = max(0, int((end - self.event_currentBattery.started_at).total_seconds()))
                        self.event_currentBattery.duration_seconds = dur_secs
                    self.event_currentBattery.save()
                    self.event_currentBattery = None

                PowerEvent.objects.create(
                    device_id=self.device_id,
                    event_type='grid_restored',
                    severity='info',
                    started_at=end,
                    ended_at=end,
                    duration_seconds=0,
                    detail=f"Restauración de la red eléctrica. Estuvo {dur_secs}s en modo batería."
                )
        except Exception as e:
            self.log(f"Error gestionando el evento energético: {e}")
        finally:
            connection.close()

    def run(self):
        """Bucle principal del hilo: conecta, lee socket y reintenta ante fallos."""
        self.log(f"Iniciando monitoreo de {self.host}:{self.port}...")

        while not self.stop_event.is_set():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10.0)

                # Keepalive del sistema operativo para detectar enlaces caídos
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "TCP_KEEPIDLE"):
                    try:
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 20)
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                    except Exception:
                        pass

                self.log(f"Conectando a {self.host}:{self.port}...")
                sock.connect((self.host, self.port))
                self.log("CONEXIÓN TCP EXITOSA. Esperando telemetría inicial...")
                try:
                    device = UPSDevice.objects.filter(id=self.device_id).first()
                    if device:
                        device.last_seen = timezone.now()
                        device.save(update_fields=["last_seen"])
                except Exception:
                    pass

                # Saludo inicial al ESP32
                try:
                    sock.sendall(b"HELLO\n")
                    self.log("HELLO enviado al ESP32. Esperando telemetría (llega cada ~60s)...")
                except Exception as e:
                    self.log(f"Aviso enviando HELLO: {e}")

                # Timeout corto de lectura (1s) para poder emitir PING cada 15s sin quedar bloqueados
                sock.settimeout(1.0)

                ultimo_rx = time.time()
                ultimo_ping = time.time()
                buffer = ""

                # Bucle de recepción y latido continuo
                while not self.stop_event.is_set():
                    ahora = time.time()

                    # 1. Enviar latido PING hacia el ESP32 cada 15s
                    if ahora - ultimo_ping >= PING_INTERVAL:
                        try:
                            sock.sendall(b"PING\n")
                            ultimo_ping = ahora
                        except Exception as e:
                            raise ConnectionError(f"Fallo enviando PING al ESP32: {e}")

                    # 2. Si el ESP32 no responde nada (ni PONG ni datos) en 45s -> conexión muerta
                    if ahora - ultimo_rx > RESPONSE_TIMEOUT:
                        raise TimeoutError(f"Sin respuesta del ESP32 en {RESPONSE_TIMEOUT}s. Reconectando...")

                    # 3. Leer datos del socket con timeout de 1s
                    try:
                        datos = sock.recv(4096)
                        if not datos:
                            raise ConnectionError("El ESP32 cerró la conexión TCP.")

                        ultimo_rx = time.time()
                        buffer += datos.decode("utf-8", errors="ignore")

                        while "\n" in buffer:
                            linea, buffer = buffer.split("\n", 1)
                            linea = linea.strip()

                            if not linea:
                                continue

                            # Respuesta al latido (PONG): conexión activa y saludable
                            if linea == "PONG":
                                continue

                            # Mensajes de saludo/control del ESP32
                            if linea in ("ESP32_READY", "TCP_READY"):
                                continue

                            try:
                                dataS = json.loads(linea)
                            except json.JSONDecodeError:
                                self.log(f"Mensaje ignorado (no JSON): {linea}")
                                continue

                            # Detectar eventos de desconexión / reconexión de la UPS con el ESP32
                            evento = dataS.get("evento") or dataS.get("event")
                            if evento in ("ups_desconectada", "ups_disconnected"):
                                self.log("ESP reporta: UPS desconectada del puerto serial.")
                                self.stateDevice_UPDATE(status='offline')
                                self.disconnectEvent_START("UPS desconectada del puerto serial del ESP32")
                                continue
                            elif evento in ("ups_reconectada", "ups_reconnected"):
                                self.log("ESP reporta: UPS reconectada al puerto serial.")
                                self.stateDevice_UPDATE(status='battery' if self.battery_mode else 'online')
                                self.disconnectEvent_END()
                                continue

                            # Procesar medición válida
                            self.readings += 1
                            self.disconnectEvent_END()  # Si había desconexión previa, se da por finalizada
                            new_mode = self.batteryMode_DETECTED(dataS)
                            mode_changed = (new_mode != self.battery_mode)
                            self.chanceEnergy_PROCCESS(new_mode)

                            now_ts = time.time()
                            # Guardar en TelemetryLog cada log_interval (o inmediato si cambió el modo)
                            if mode_changed or (now_ts - self.last_telemetry_save >= self.log_interval):
                                self.telemetry_SAVE(dataS)
                                self.last_telemetry_save = now_ts
                                self.last_state_update = now_ts
                            elif now_ts - self.last_state_update >= 5:
                                # Mantiene viva la última lectura y estado en UPSDevice sin saturar el historial
                                battery = float(dataS.get("bateria") or dataS.get("battery", 0))
                                self.stateDevice_UPDATE(
                                    status='battery' if self.battery_mode else 'online',
                                    battery_voltage=battery
                                )
                                self.last_state_update = now_ts

                            v_in = dataS.get('entrada') or dataS.get('enter')
                            v_out = dataS.get('salida') or dataS.get('exit')
                            try:
                                v_bat = float(dataS.get('bateria') or dataS.get('battery') or 0)
                            except (ValueError, TypeError):
                                v_bat = 0.0

                            # Porcentaje proporcional basado en 2.30V como el 100% (2.30 / 100 = 0.023V por %)
                            if 0 < v_bat <= 3.5:
                                bat_pct = int(min(100, max(0, round((v_bat / 2.30) * 100))))
                                bat_str = f"{v_bat:.2f}V ({bat_pct}%)"
                            elif v_bat > 3.5:
                                bat_pct = int(min(100, max(0, round((v_bat / 13.80) * 100))))
                                bat_str = f"{v_bat:.2f}V ({bat_pct}%)"
                            else:
                                bat_str = "0V (0%)"

                            modo_str = "Batería" if self.battery_mode else "Red"
                            self.log(f"Telemetría #{self.readings} recibida: Vin={v_in}V, Vout={v_out}V, Bat={bat_str}, Modo={modo_str}")

                    except socket.timeout:
                        # Timeout normal de 1s para permitir evaluar el latido PING y stop_event
                        continue

            except socket.gaierror as e:
                self.log(f"Host o dirección IP inválida/inalcanzable '{self.host}' ({e}). Revisa la configuración del equipo.")
                self.stateDevice_UPDATE(status='offline')
                self.disconnectEvent_START(f"Host o dirección IP no resuelta ({e})")
                for _ in range(10):
                    if self.stop_event.is_set():
                        break
                    time.sleep(1)
                continue
            except Exception as e:
                self.log(f"Desconectado ({e}). Reintentando en {self.time_connection}s...")
                self.stateDevice_UPDATE(status='offline')
                self.disconnectEvent_START(str(e))
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            for _ in range(self.time_connection):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        self.log("Hilo detenido limpiamente.")

    def stop(self):
        """Para indicar al worker que debe terminar su ejecución."""
        self.stop_event.set()


# ==============================================================================
# 2. Funciones de Supervisión y Bucle Principal
# ==============================================================================

_supervisor_thread = None
_supervisor_stop_event = None
_supervisor_lock = threading.Lock()


def run_supervisor_loop(log_interval=60, stop_event=None):
    """
    Bucle continuo que inspecciona periódicamente la base de datos,
    inicia workers para nuevas UPS y detiene workers de UPS eliminadas.
    """
    workers = {}
    last_global_cleanup = 0
    try:
        while not (stop_event and stop_event.is_set()):
            ups_actives = list(UPSDevice.objects.filter(is_active=True))
            ids_actives = {u.id for u in ups_actives}

            for ups in ups_actives:
                needStart = False
                if ups.id not in workers:
                    needStart = True
                else:
                    current_worker, old_host, old_port = workers[ups.id]
                    if old_host != ups.host or old_port != int(ups.port):
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SUPERVISOR] Configuración cambiada para {ups.name}. Reiniciando worker...")
                        current_worker.stop()
                        needStart = True
                    elif not current_worker.is_alive():
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SUPERVISOR] Worker para {ups.name} detenido. Reiniciando...")
                        needStart = True

                if needStart:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SUPERVISOR] Levantando worker para {ups.name} ({ups.host}:{ups.port})")
                    w = UPSWorker(
                        device_id=ups.id,
                        name=ups.name,
                        host=ups.host,
                        port=ups.port,
                        log_interval=log_interval
                    )
                    w.start()
                    workers[ups.id] = (w, ups.host, int(ups.port))

            ids_remove = [dev_id for dev_id in workers if dev_id not in ids_actives]
            for dev_id in ids_remove:
                worker_delete, _, _ = workers.pop(dev_id)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SUPERVISOR] UPS #{dev_id} desactivada. Deteniendo worker...")
                worker_delete.stop()

            # Purgar periódicamente telemetrías con más de 24 horas de antigüedad
            now_loop = time.time()
            if now_loop - last_global_cleanup >= 300:
                last_global_cleanup = now_loop
                purge_old_telemetry(hours=24)

            connection.close()

            for _ in range(15):
                if stop_event and stop_event.is_set():
                    break
                time.sleep(1)

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SUPERVISOR] Error en bucle supervisor: {e}")
    finally:
        for dev_id, (w, _, _) in workers.items():
            w.stop()


def start_monitor_in_background(log_interval=60):
    """
    Inicia el bucle supervisor multi-UPS en un hilo demonio en segundo plano.
    Evita arrancar duplicados si ya está corriendo en este proceso.
    """
    global _supervisor_thread, _supervisor_stop_event
    with _supervisor_lock:
        if _supervisor_thread is not None and _supervisor_thread.is_alive():
            return _supervisor_thread

        _supervisor_stop_event = threading.Event()
        _supervisor_thread = threading.Thread(
            target=run_supervisor_loop,
            kwargs={'log_interval': log_interval, 'stop_event': _supervisor_stop_event},
            name="UPSSupervisorThread",
            daemon=True
        )
        _supervisor_thread.start()
        print("\n" + "="*65)
        print("  [+] [CENTINELA] Monitor Multi-UPS iniciado en segundo plano")
        print("  [*] Enlace continuo con ESP32 activo")
        print("="*65 + "\n")
        return _supervisor_thread


def stop_monitor_background():
    """Detiene el supervisor en segundo plano si está activo."""
    global _supervisor_stop_event
    if _supervisor_stop_event:
        _supervisor_stop_event.set()


# ==============================================================================
# 3. Comando de Django - Supervisor Standalone
# ==============================================================================

class Command(BaseCommand):
    help = "Monitorea continuamente en paralelo todas las UPS activas en la BD"

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Intervalo en segundos para guardar registros en TelemetryLog (por defecto: 60s)'
        )

    def handle(self, *args, **options):
        log_interval = options.get('interval', 60)
        self.stdout.write(self.style.SUCCESS(f"=== INICIANDO SERVICIO MULTI-UPS (Guardado en BD cada {log_interval}s) ==="))
        stop_event = threading.Event()
        try:
            run_supervisor_loop(log_interval=log_interval, stop_event=stop_event)
        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("\nDeteniendo todos los monitores..."))
            stop_event.set()
            self.stdout.write(self.style.SUCCESS("Todos los workers han sido detenidos."))
