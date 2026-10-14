import socket
import json
import time
import threading
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import connection

from panel.models import UPSDevice, TelemetryLog, PowerEvent


# Constantes de conexión y latido (sincronizadas con el nuevo firmware del ESP32)
PING_INTERVAL = 15          # Segundos entre PING al ESP32
RESPONSE_TIMEOUT = 45       # Si el ESP32 no responde en este tiempo (ni PONG ni datos), reconectar
RECONNECT_DELAY = 3         # Segundos antes de reintentar conexión


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

        # Estados de la UPS
        self.battery_mode = False
        self.battery_start = None
        self.event_currentBattery = None
        self.readings = 0
        self.last_telemetry_save = 0  # Timestamp del último registro guardado en TelemetryLog
        self.last_state_update = 0    # Timestamp de última actualización en UPSDevice

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
        """Crea un nuevo registro en TelemetryLog."""
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
        except Exception as e:
            self.log(f"Error guardando telemetría: {e}")
        finally:
            connection.close()

    def chanceEnergy_PROCCESS(self, new_batteryMode):
        """Detecta cortes de luz y restauraciones creando registros en PowerEvent."""
        try:
            # Red fuera -> modo bateria
            if new_batteryMode and not self.battery_mode:
                self.battery_mode = True
                self.battery_start = timezone.now()
                self.log("⚠️ ¡CORTE DE LUZ! UPS pasó a modo BATERÍA. ⚠️")

                self.event_currentBattery = PowerEvent.objects.create(
                    device_id=self.device_id,
                    event_type='battery_mode',
                    severity='critical',
                    started_at=self.battery_start,
                    detail="Corte en la red eléctrica detectado."
                )

            # red volvió -> salió de modo batería
            elif not new_batteryMode and self.battery_mode:
                self.battery_mode = False
                end = timezone.now()
                self.log("✅ ¡ENERGÍA RESTAURADA! UPS volvió a red eléctrica.")

                if self.event_currentBattery:
                    self.event_currentBattery.ended_at = end
                    self.event_currentBattery.save()
                    self.event_currentBattery = None

                PowerEvent.objects.create(
                    device_id=self.device_id,
                    event_type='grid_restored',
                    severity='info',
                    started_at=end,
                    detail="Restauración de la red eléctrica"
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
                                continue
                            elif evento in ("ups_reconectada", "ups_reconnected"):
                                self.log("ESP reporta: UPS reconectada al puerto serial.")
                                self.stateDevice_UPDATE(status='online')
                                continue

                            # Procesar medición válida
                            self.readings += 1
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

                            # Porcentaje basado en 2.30V (100%) y corte en 1.75V (0%)
                            if 0 < v_bat <= 3.5:
                                bat_pct = int(min(100, max(0, round(((v_bat - 1.75) / (2.30 - 1.75)) * 100))))
                                bat_str = f"{v_bat:.2f}V ({bat_pct}%)"
                            else:
                                bat_str = f"{v_bat}V"

                            modo_str = "Batería" if self.battery_mode else "Red"
                            self.log(f"Telemetría #{self.readings} recibida: Vin={v_in}V, Vout={v_out}V, Bat={bat_str}, Modo={modo_str}")

                    except socket.timeout:
                        # Timeout normal de 1s para permitir evaluar el latido PING y stop_event
                        continue

            except Exception as e:
                self.log(f"Desconectado ({e}). Reintentando en {self.time_connection}s...")
                self.stateDevice_UPDATE(status='offline')
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
# 2. Comando de Django - Supervisor
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

        workers = {}

        try:
            while True:
                # Buscar qué UPS se encuentran activas en el sistema
                ups_actives = list(UPSDevice.objects.filter(is_active=True))
                ids_actives = {u.id for u in ups_actives}

                # Iniciar workers para UPS nuevas o cuyos datos cambiaron
                for ups in ups_actives:
                    needStart = False

                    if ups.id not in workers:
                        needStart = True
                    else:
                        current_worker, old_host, old_port = workers[ups.id]
                        # Si se cambia la IP o el puerto en la BD, reinicia ese worker
                        if old_host != ups.host or old_port != int(ups.port):
                            self.stdout.write(self.style.WARNING(f"Configuración cambiada para {ups.name}. Reiniciando worker..."))
                            current_worker.stop()
                            needStart = True
                        elif not current_worker.is_alive():
                            self.stdout.write(self.style.WARNING(f"Worker para {ups.name} se detuvo inesperadamente. Reiniciando..."))
                            needStart = True

                    if needStart:
                        self.stdout.write(self.style.MIGRATE_HEADING(f"Levantando worker para {ups.name} ({ups.host}:{ups.port})"))
                        w = UPSWorker(
                            device_id=ups.id,
                            name=ups.name,
                            host=ups.host,
                            port=ups.port,
                            log_interval=log_interval
                        )
                        w.start()
                        workers[ups.id] = (w, ups.host, int(ups.port))

                # Detener workers de UPS que fueron desactivadas o eliminadas de la base de datos
                ids_remove = [dev_id for dev_id in workers if dev_id not in ids_actives]

                for dev_id in ids_remove:
                    worker_delete, _, _ = workers.pop(dev_id)
                    self.stdout.write(self.style.WARNING(f"UPS #{dev_id} desactivada. Deteniendo worker..."))
                    worker_delete.stop()

                connection.close()
                time.sleep(15)

        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("\nDeteniendo todos los monitores..."))
            for dev_id, (w, _, _) in workers.items():
                w.stop()
            self.stdout.write(self.style.SUCCESS("Todos los workers han sido detenidos."))
