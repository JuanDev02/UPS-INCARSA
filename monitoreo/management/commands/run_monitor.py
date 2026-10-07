import socket
import json
import time
import threading
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import connection

from monitoreo.models import UPSDevice, TelemetryLog, PowerEvent


# ==============================================================================
# 1. Clase Trabajadora (Worker por dispositivo)
# ==============================================================================

class UPSWorker(threading.Thread):
    """
    Hilo encargado de conectarse por TCP a un solo ESP32/UPS,
    leer su telemetría y guardar los datos en la base de datos de Django.
    """
    def __init__(self, device_id, name, host, port, time_connection=5):
        super().__init__(daemon=True)
        self.device_id = device_id
        self.name = name
        self.host = host
        self.port = int(port)
        self.time_connection = time_connection

        self.stop_event = threading.Event()  # Indicador para pedir al hilo detenerse

        # Estados de la UPS
        self.battery_mode = False
        self.battery_start = None
        self.event_currentBattery = None
        self.readings = 0

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
                device.status = status
                device.last_seen = timezone.now()
                if battery_voltage is not None:
                    device.battery_voltage = battery_voltage
                device.save(
                    update_fields=["status", "last_seen", "battery_voltage"]
                    if battery_voltage is not None else ["status", "last_seen"]
                )
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
                sock.connect((self.host, self.port))
                self.log("Conectado exitosamente con ESP32.")
                self.stateDevice_UPDATE(status='online')

                # Saludo inicial al ESP32
                try:
                    sock.sendall(b"HELLO\n")
                except Exception:
                    pass

                buffer = b""

                # Bucle de lectura de datos
                while not self.stop_event.is_set():
                    try:
                        data = sock.recv(4096)
                        if not data:
                            raise ConnectionError("El ESP32 cerró la conexión TCP.")

                        buffer += data

                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line = line_bytes.decode("utf-8", errors="ignore").strip()

                            if not line or line in ("ESP32_READY", "TCP_READY"):
                                continue

                            try:
                                dataS = json.loads(line)
                            except json.JSONDecodeError:
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
                            self.chanceEnergy_PROCCESS(new_mode)
                            self.telemetry_SAVE(dataS)

                            if self.readings % 20 == 0:
                                v_in = dataS.get('entrada') or dataS.get('enter')
                                v_out = dataS.get('salida') or dataS.get('exit')
                                v_bat = dataS.get('bateria') or dataS.get('battery')
                                self.log(f"Telemetría activa ({self.readings} lecturas). Vin={v_in}V, Vout={v_out}V, Bat={v_bat}V")
                    except socket.timeout:
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

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== INICIANDO SERVICIO MULTI-UPS ==="))

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

                    if needStart:
                        self.stdout.write(self.style.MIGRATE_HEADING(f"Levantando worker para {ups.name} ({ups.host}:{ups.port})"))
                        w = UPSWorker(
                            device_id=ups.id,
                            name=ups.name,
                            host=ups.host,
                            port=ups.port
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
