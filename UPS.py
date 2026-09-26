import socket
import json
import time
from datetime import datetime

# ============================================================
# CONFIGURACION
# ============================================================

HOST = "177.93.52.198"
PORT = 7660

TIEMPO_RECONEXION = 5

# ============================================================
# ESTADISTICAS
# ============================================================

lecturas = 0

desconexiones = 0
reconexiones = 0

modo_bateria = False

inicio_bateria = None
duracion_bateria_actual = 0

ultima_falla = None
duracion_ultima_falla = 0

# Acumulados de tiempo en bateria
tiempo_total_bateria = 0
eventos_bateria = 0

# Valores minimos
min_entrada = None
min_salida = None
min_frecuencia = None
min_bateria = None
min_temperatura = None
min_carga = None

# Valores maximos
max_entrada = None
max_salida = None
max_frecuencia = None
max_bateria = None
max_temperatura = None
max_carga = None

# Acumulados para promedio
sum_entrada = 0
sum_salida = 0
sum_frecuencia = 0
sum_bateria = 0
sum_temperatura = 0
sum_carga = 0

# Ultimos valores
ultima_entrada = None
ultima_salida = None
ultima_frecuencia = None
ultima_bateria = None
ultima_temperatura = None
ultima_carga = None
ultimo_estado = None

# ============================================================
# FUNCIONES
# ============================================================

def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def actualizar_min_max(valor, minimo, maximo):

    if valor is None:
        return minimo, maximo

    if minimo is None or valor < minimo:
        minimo = valor

    if maximo is None or valor > maximo:
        maximo = valor

    return minimo, maximo


def tiempo_formateado(segundos):

    segundos = int(max(0, segundos))

    dias = segundos // 86400
    segundos %= 86400

    horas = segundos // 3600
    segundos %= 3600

    minutos = segundos // 60
    segundos %= 60

    if dias > 0:
        return f"{dias}d {horas:02d}h {minutos:02d}m {segundos:02d}s"

    return f"{horas:02d}h {minutos:02d}m {segundos:02d}s"


def interpretar_estado(estado):

    if not estado:
        return []

    estado = str(estado).strip()

    if len(estado) != 8:
        return ["ESTADO NO VALIDO"]

    mensajes = []

    # Bit 7
    if estado[0] == "1":
        mensajes.append("RED ELECTRICA AUSENTE / UPS EN BATERIA")
    else:
        mensajes.append("RED ELECTRICA NORMAL")

    # Bit 6
    if estado[1] == "1":
        mensajes.append("BATERIA BAJA")
    else:
        mensajes.append("BATERIA NO INDICA NIVEL BAJO")

    # Bit 5
    if estado[2] == "1":
        mensajes.append("BYPASS / BOOST / BUCK ACTIVO")
    else:
        mensajes.append("SIN BYPASS / BOOST / BUCK")

    # Bit 4
    if estado[3] == "1":
        mensajes.append("FALLA DE UPS")
    else:
        mensajes.append("UPS SIN FALLA")

    # Bit 3
    if estado[4] == "1":
        mensajes.append("UPS TIPO STANDBY")
    else:
        mensajes.append("UPS TIPO ONLINE")

    # Bit 2
    if estado[5] == "1":
        mensajes.append("PRUEBA DE UPS ACTIVA")
    else:
        mensajes.append("SIN PRUEBA ACTIVA")

    # Bit 1
    if estado[6] == "1":
        mensajes.append("APAGADO DE UPS ACTIVO")
    else:
        mensajes.append("SIN APAGADO PROGRAMADO")

    # Bit 0
    if estado[7] == "1":
        mensajes.append("BEEPER ACTIVO")
    else:
        mensajes.append("BEEPER APAGADO")

    return mensajes


def detectar_modo_bateria(data):

    estado = str(data.get("estado", "00000000"))

    entrada = float(data.get("entrada", 0))
    frecuencia = float(data.get("frecuencia", 0))

    # Bit 7 del protocolo Megatec
    if len(estado) == 8 and estado[0] == "1":
        return True

    # Respaldo adicional
    if entrada <= 1 and frecuencia <= 1:
        return True

    return False


def imprimir_separador():
    print("=" * 78)


def imprimir_lectura(data):

    global lecturas
    global min_entrada, max_entrada
    global min_salida, max_salida
    global min_frecuencia, max_frecuencia
    global min_bateria, max_bateria
    global min_temperatura, max_temperatura
    global min_carga, max_carga

    global sum_entrada, sum_salida
    global sum_frecuencia, sum_bateria
    global sum_temperatura, sum_carga

    global ultima_entrada, ultima_salida
    global ultima_frecuencia, ultima_bateria
    global ultima_temperatura, ultima_carga
    global ultimo_estado

    lecturas += 1

    entrada = float(data.get("entrada", 0))
    entrada_falla = float(data.get("entrada_falla", 0))
    salida = float(data.get("salida", 0))
    carga = float(data.get("campo4", 0))
    frecuencia = float(data.get("frecuencia", 0))
    bateria = float(data.get("bateria", 0))
    temperatura = float(data.get("temperatura", 0))

    estado = str(data.get("estado", "00000000"))
    conectada = data.get("ups_conectada", False)

    # --------------------------------------------------------
    # ESTADISTICAS
    # --------------------------------------------------------

    min_entrada, max_entrada = actualizar_min_max(
        entrada, min_entrada, max_entrada
    )

    min_salida, max_salida = actualizar_min_max(
        salida, min_salida, max_salida
    )

    min_frecuencia, max_frecuencia = actualizar_min_max(
        frecuencia, min_frecuencia, max_frecuencia
    )

    min_bateria, max_bateria = actualizar_min_max(
        bateria, min_bateria, max_bateria
    )

    min_temperatura, max_temperatura = actualizar_min_max(
        temperatura, min_temperatura, max_temperatura
    )

    min_carga, max_carga = actualizar_min_max(
        carga, min_carga, max_carga
    )

    sum_entrada += entrada
    sum_salida += salida
    sum_frecuencia += frecuencia
    sum_bateria += bateria
    sum_temperatura += temperatura
    sum_carga += carga

    # --------------------------------------------------------
    # CAMBIOS
    # --------------------------------------------------------

    cambio_entrada = ""
    cambio_salida = ""
    cambio_bateria = ""
    cambio_temperatura = ""

    if ultima_entrada is not None:
        delta = entrada - ultima_entrada

        if abs(delta) >= 5:
            cambio_entrada = f" CAMBIO: {delta:+.2f} V"

    if ultima_salida is not None:
        delta = salida - ultima_salida

        if abs(delta) >= 5:
            cambio_salida = f" CAMBIO: {delta:+.2f} V"

    if ultima_bateria is not None:
        delta = bateria - ultima_bateria

        if abs(delta) >= 0.10:
            cambio_bateria = f" CAMBIO: {delta:+.2f} V"

    if ultima_temperatura is not None:
        delta = temperatura - ultima_temperatura

        if abs(delta) >= 2:
            cambio_temperatura = f" CAMBIO: {delta:+.2f} °C"

    ultima_entrada = entrada
    ultima_salida = salida
    ultima_frecuencia = frecuencia
    ultima_bateria = bateria
    ultima_temperatura = temperatura
    ultima_carga = carga
    ultimo_estado = estado

    # --------------------------------------------------------
    # MODO
    # --------------------------------------------------------

    bateria_activa = detectar_modo_bateria(data)

    if bateria_activa:
        modo = "🔋 FUNCIONANDO CON BATERIA"
    else:
        modo = "⚡ FUNCIONANDO CON RED"

    # --------------------------------------------------------
    # MOSTRAR
    # --------------------------------------------------------

    print()
    imprimir_separador()

    print(f"  LECTURA #{lecturas}")
    print(f"  FECHA/HORA: {ahora()}")

    imprimir_separador()

    print("  ESTADO GENERAL")
    print(f"  Comunicacion UPS : {'OK' if conectada else 'ERROR'}")
    print(f"  Modo             : {modo}")
    print(f"  Estado Q1        : {estado}")

    imprimir_separador()

    print("  DATOS ELECTRICOS")

    print(
        f"  Entrada          : {entrada:8.2f} V"
        f"{cambio_entrada}"
    )

    print(
        f"  Entrada falla    : {entrada_falla:8.2f} V"
    )

    print(
        f"  Salida           : {salida:8.2f} V"
        f"{cambio_salida}"
    )

    print(
        f"  Carga            : {carga:8.2f} %"
    )

    print(
        f"  Frecuencia       : {frecuencia:8.2f} Hz"
    )

    print(
        f"  Bateria          : {bateria:8.2f} V/celda"
        f"{cambio_bateria}"
    )

    print(
        f"  Temperatura      : {temperatura:8.2f} °C"
        f"{cambio_temperatura}"
    )

    imprimir_separador()

    print("  INTERPRETACION DEL ESTADO")

    mensajes = interpretar_estado(estado)

    for mensaje in mensajes:
        print(f"  - {mensaje}")

    imprimir_separador()

    if lecturas > 0:

        print("  ESTADISTICAS ACUMULADAS")

        print(
            f"  Entrada   -> "
            f"MIN {min_entrada:.2f} V | "
            f"MAX {max_entrada:.2f} V | "
            f"PROM {sum_entrada / lecturas:.2f} V"
        )

        print(
            f"  Salida    -> "
            f"MIN {min_salida:.2f} V | "
            f"MAX {max_salida:.2f} V | "
            f"PROM {sum_salida / lecturas:.2f} V"
        )

        print(
            f"  Frecuencia-> "
            f"MIN {min_frecuencia:.2f} Hz | "
            f"MAX {max_frecuencia:.2f} Hz | "
            f"PROM {sum_frecuencia / lecturas:.2f} Hz"
        )

        print(
            f"  Bateria   -> "
            f"MIN {min_bateria:.2f} V | "
            f"MAX {max_bateria:.2f} V | "
            f"PROM {sum_bateria / lecturas:.2f} V/celda"
        )

        print(
            f"  Temperatura-> "
            f"MIN {min_temperatura:.2f} °C | "
            f"MAX {max_temperatura:.2f} °C | "
            f"PROM {sum_temperatura / lecturas:.2f} °C"
        )

        print(
            f"  Carga     -> "
            f"MIN {min_carga:.2f} % | "
            f"MAX {max_carga:.2f} % | "
            f"PROM {sum_carga / lecturas:.2f} %"
        )

    # --------------------------------------------------------
    # TIEMPO EN BATERIA
    # --------------------------------------------------------

    if modo_bateria_global:
        if inicio_bateria is not None:
            duracion = time.time() - inicio_bateria
            print()
            print(
                f"  🔋 TIEMPO ACTUAL EN BATERIA: "
                f"{tiempo_formateado(duracion)}"
            )

    imprimir_separador()


def imprimir_resumen_final():

    print()
    print()
    print("#" * 78)
    print("                 RESUMEN DEL MONITOREO")
    print("#" * 78)

    print(f"Lecturas recibidas       : {lecturas}")
    print(f"Desconexiones            : {desconexiones}")
    print(f"Reconexiones             : {reconexiones}")
    print(f"Eventos en bateria       : {eventos_bateria}")

    print(
        f"Tiempo total en bateria  : "
        f"{tiempo_formateado(tiempo_total_bateria)}"
    )

    print()

    if lecturas > 0:

        print("VALORES MINIMOS / MAXIMOS")
        print("-" * 78)

        print(
            f"Entrada      : {min_entrada:.2f} V "
            f"--> {max_entrada:.2f} V"
        )

        print(
            f"Salida       : {min_salida:.2f} V "
            f"--> {max_salida:.2f} V"
        )

        print(
            f"Frecuencia   : {min_frecuencia:.2f} Hz "
            f"--> {max_frecuencia:.2f} Hz"
        )

        print(
            f"Bateria      : {min_bateria:.2f} V "
            f"--> {max_bateria:.2f} V/celda"
        )

        print(
            f"Temperatura  : {min_temperatura:.2f} °C "
            f"--> {max_temperatura:.2f} °C"
        )

        print(
            f"Carga        : {min_carga:.2f} % "
            f"--> {max_carga:.2f} %"
        )

    print("#" * 78)


# ============================================================
# VARIABLES DE ESTADO
# ============================================================

modo_bateria_global = False
ups_conectada_global = False

# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

print()
print("=" * 78)
print("             MONITOR REMOTO UPS - DIAGNOSTICO")
print("=" * 78)
print()
print(f"Servidor : {HOST}")
print(f"Puerto   : {PORT}")
print()
print("El monitor analizara continuamente los datos Q1.")
print("Presiona CTRL + C para terminar.")
print()

while True:

    sock = None

    try:

        print()
        print("-" * 78)
        print(f"[{ahora()}] Intentando conectar...")
        print(f"Destino TCP: {HOST}:{PORT}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        sock.settimeout(15)

        sock.connect((HOST, PORT))

        print(f"[{ahora()}] CONEXION TCP ESTABLECIDA")

        # ----------------------------------------------------
        # HELLO
        # ----------------------------------------------------

        try:
            sock.sendall(b"HELLO\n")
        except:
            pass

        ups_conectada_global = True

        if desconexiones > 0:
            reconexiones += 1

            print()
            print("***********************************************")
            print("        UPS / ESP32 RECONEXION DETECTADA")
            print("***********************************************")
            print()

        buffer = b""

        # ----------------------------------------------------
        # RECEPCION
        # ----------------------------------------------------

        while True:

            try:

                datos = sock.recv(4096)

                if not datos:

                    raise ConnectionError(
                        "El ESP32 cerro la conexion."
                    )

                buffer += datos

                while b"\n" in buffer:

                    linea, buffer = buffer.split(b"\n", 1)

                    linea = linea.decode(
                        "utf-8",
                        errors="ignore"
                    ).strip()

                    if not linea:
                        continue

                    # ----------------------------------------
                    # MENSAJES DEL ESP32
                    # ----------------------------------------

                    if linea == "ESP32_READY":

                        print(
                            f"[{ahora()}] ESP32 listo."
                        )

                        continue

                    if linea == "TCP_READY":

                        print(
                            f"[{ahora()}] Canal TCP listo."
                        )

                        continue

                    # ----------------------------------------
                    # JSON
                    # ----------------------------------------

                    try:

                        data = json.loads(linea)

                    except json.JSONDecodeError:

                        print()
                        print(
                            f"[{ahora()}] DATO NO JSON:"
                        )
                        print(linea)

                        continue

                    # ----------------------------------------
                    # EVENTO UPS DESCONECTADA
                    # ----------------------------------------

                    if data.get("evento") == "ups_desconectada":

                        desconexiones += 1

                        ups_conectada_global = False

                        print()
                        print("!")
                        print("!" * 70)
                        print(
                            f"  [{ahora()}] UPS DESCONECTADA"
                        )
                        print(
                            "  El ESP32 no recibio respuestas Q1."
                        )
                        print("!" * 70)
                        print()

                        continue

                    # ----------------------------------------
                    # EVENTO UPS RECONECTADA
                    # ----------------------------------------

                    if data.get("evento") == "ups_reconectada":

                        reconexiones += 1

                        ups_conectada_global = True

                        print()
                        print("!")
                        print("!" * 70)
                        print(
                            f"  [{ahora()}] UPS RECONECTADA"
                        )
                        print("!" * 70)
                        print()

                        continue

                    # ----------------------------------------
                    # DATOS NORMALES
                    # ----------------------------------------

                    ups_conectada_global = data.get(
                        "ups_conectada",
                        True
                    )

                    nuevo_modo_bateria = detectar_modo_bateria(data)

                    # ----------------------------------------
                    # CAMBIO RED -> BATERIA
                    # ----------------------------------------

                    if (
                        nuevo_modo_bateria
                        and not modo_bateria_global
                    ):

                        modo_bateria_global = True

                        inicio_bateria = time.time()

                        eventos_bateria += 1

                        print()
                        print("!")
                        print("!" * 70)
                        print(
                            f"  [{ahora()}] ⚠️  FALLA DE RED DETECTADA"
                        )
                        print(
                            "  LA UPS ENTRO EN MODO BATERIA"
                        )
                        print(
                            f"  Evento de bateria #{eventos_bateria}"
                        )
                        print("!" * 70)
                        print()

                    # ----------------------------------------
                    # CAMBIO BATERIA -> RED
                    # ----------------------------------------

                    if (
                        not nuevo_modo_bateria
                        and modo_bateria_global
                    ):

                        modo_bateria_global = False

                        if inicio_bateria is not None:

                            duracion_bateria_actual = (
                                time.time() - inicio_bateria
                            )

                            tiempo_total_bateria += (
                                duracion_bateria_actual
                            )

                            duracion_ultima_falla = (
                                duracion_bateria_actual
                            )

                            ultima_falla = time.time()

                            print()
                            print("!")
                            print("!" * 70)
                            print(
                                f"  [{ahora()}] ✅ RED ELECTRICA RESTAURADA"
                            )
                            print(
                                "  LA UPS SALIO DEL MODO BATERIA"
                            )
                            print(
                                f"  DURACION DEL EVENTO: "
                                f"{tiempo_formateado(duracion_bateria_actual)}"
                            )
                            print(
                                f"  TIEMPO TOTAL EN BATERIA: "
                                f"{tiempo_formateado(tiempo_total_bateria)}"
                            )
                            print("!" * 70)
                            print()

                            inicio_bateria = None

                    # ----------------------------------------
                    # IMPRIMIR INFORMACION
                    # ----------------------------------------

                    imprimir_lectura(data)

            except socket.timeout:

                print(
                    f"[{ahora()}] Esperando datos..."
                )

    except KeyboardInterrupt:

        print()
        print()
        print("Finalizando monitor...")

        if modo_bateria_global and inicio_bateria is not None:

            tiempo_actual = time.time() - inicio_bateria

            tiempo_total_bateria += tiempo_actual

        imprimir_resumen_final()

        break

    except Exception as e:

        ups_conectada_global = False

        print()
        print("!" * 78)
        print(
            f"[{ahora()}] ERROR DE COMUNICACION"
        )
        print(
            f"Detalle: {e}"
        )
        print("!" * 78)

        print()
        print(
            f"Intentando nuevamente en "
            f"{TIEMPO_RECONEXION} segundos..."
        )

        time.sleep(TIEMPO_RECONEXION)

    finally:

        if sock is not None:

            try:
                sock.close()
            except:
                pass