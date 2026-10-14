#include <SPI.h>
#include <usbhub.h>
#include <EthernetENC.h>

// ============================================================
// ESP32 + MAX3421E + CH340 + UPS POWEST
// + ENC28J60 ETHERNET
// ============================================================
//
// ESP32 NORMAL
//
// MAX3421E:
// SCK  = GPIO 18
// MISO = GPIO 19
// MOSI = GPIO 23
// CS   = GPIO 5
// INT  = GPIO 17
//
// ENC28J60:
// SCK  = GPIO 18
// MISO = GPIO 19
// MOSI = GPIO 23
// CS   = GPIO 4
//
// RED:
// IP      = 192.168.1.60
// MASK    = 255.255.255.0
// GATEWAY = 192.168.1.1
// DNS     = 8.8.8.8
// TCP     = 7660
// ============================================================


// ============================================================
// PINES SPI
// ============================================================

#define PIN_SCK      18
#define PIN_MISO     19
#define PIN_MOSI     23

#define PIN_CS_USB   5
#define PIN_CS_ETH   4


// ============================================================
// ETHERNET
// ============================================================

byte mac[] = {
  0x02,
  0x60,
  0xA4,
  0x12,
  0x34,
  0x60
};

IPAddress ipUPS(
  192, 168, 1, 60
);

IPAddress dnsServerIP(
  8, 8, 8, 8
);

IPAddress gatewayIP(
  192, 168, 1, 1
);

IPAddress subnetIP(
  255, 255, 255, 0
);

#define PUERTO_TCP 7660

EthernetServer servidorEthernet(
  PUERTO_TCP
);

EthernetClient clienteEthernet;

bool ethernetInicializado = false;


// ============================================================
// IP DEL PC ESPERADO
// ============================================================

IPAddress ipPC(
  192, 168, 1, 50
);


// ============================================================
// CONTROL CLIENTE TCP
// ============================================================

bool clienteTCPActivo = false;

unsigned long ultimoHandshake = 0;

const unsigned long TIMEOUT_HANDSHAKE = 10000;


// ============================================================
// USB HOST
// ============================================================

USB Usb;


// ============================================================
// CH340
// ============================================================

#define CH34X_VENDOR_ID   0x1A86

#define CH340_PRODUCT_ID  0x7523
#define CH341_PRODUCT_ID  0x5523


// ============================================================
// COMANDOS VENDOR CH340
// ============================================================

#define VENDOR_READ        0x95
#define VENDOR_WRITE       0x9A
#define VENDOR_SERIAL_INIT 0xA1
#define VENDOR_MODEM_OUT   0xA4
#define VENDOR_VERSION     0x5F

#define BMREQ_CH34X_OUT    0x40
#define BMREQ_CH34X_IN     0xC0


// ============================================================
// ENDPOINTS
// ============================================================

#define EP_DATA_IN   1
#define EP_DATA_OUT  2
#define EP_INT_IN    3

#define MAX_EP 4


// ============================================================
// CLASE ASINCRONA
// ============================================================

class CH340;

class CH340Async {

public:

  uint8_t OnInit(CH340 *dev) {
    return 0;
  }

  uint8_t OnRelease(CH340 *dev) {
    return 0;
  }
};


// ============================================================
// DRIVER CH340
// ============================================================

class CH340 :
  public USBDeviceConfig,
  public UsbConfigXtracter {

private:

  USB *pUsb;
  CH340Async *pAsync;

  uint8_t bAddress;
  uint8_t bConfNum;
  uint8_t bNumEP;

  bool ready;

  EpInfo epInfo[MAX_EP];


public:

  CH340(
    USB *pusb,
    CH340Async *pasync
  );

  uint8_t Init(
    uint8_t parent,
    uint8_t port,
    bool lowspeed
  );

  uint8_t Release();

  uint8_t Poll();

  virtual uint8_t GetAddress() {
    return bAddress;
  }

  virtual bool isReady() {
    return ready;
  }

  void EndpointXtract(
    uint8_t conf,
    uint8_t iface,
    uint8_t alt,
    uint8_t proto,
    const USB_ENDPOINT_DESCRIPTOR *ep
  );

  virtual bool VIDPIDOK(
    uint16_t vid,
    uint16_t pid
  ) {

    return (
      vid == CH34X_VENDOR_ID &&
      (
        pid == CH340_PRODUCT_ID ||
        pid == CH341_PRODUCT_ID
      )
    );
  }

  int VendorRead(
    uint8_t request,
    uint16_t value,
    uint16_t index,
    uint8_t *buf,
    uint16_t len
  );

  int VendorWrite(
    uint8_t request,
    uint16_t value,
    uint16_t index,
    uint8_t *buf,
    uint16_t len
  );

  uint8_t Set2400();

  uint8_t Send(
    uint16_t len,
    uint8_t *data
  );

  uint8_t Receive(
    uint16_t *len,
    uint8_t *data
  );
};


// ============================================================
// CONSTRUCTOR
// ============================================================

CH340::CH340(
  USB *pusb,
  CH340Async *pasync
) {

  pUsb = pusb;
  pAsync = pasync;

  bAddress = 0;
  bConfNum = 0;
  bNumEP = 1;

  ready = false;


  for (
    uint8_t i = 0;
    i < MAX_EP;
    i++
  ) {

    epInfo[i].epAddr = 0;

    epInfo[i].maxPktSize =
      (i == 0) ? 8 : 0;

    epInfo[i].bmSndToggle = 0;
    epInfo[i].bmRcvToggle = 0;

    epInfo[i].bmNakPower =
      USB_NAK_DEFAULT;
  }


  if (pUsb) {

    pUsb->RegisterDeviceClass(
      this
    );
  }
}


// ============================================================
// INIT CH340
// ============================================================

uint8_t CH340::Init(
  uint8_t parent,
  uint8_t port,
  bool lowspeed
) {

  const uint8_t constBufSize =
    sizeof(USB_DEVICE_DESCRIPTOR);

  uint8_t buf[
    constBufSize
  ];

  USB_DEVICE_DESCRIPTOR *udd =
    reinterpret_cast<
      USB_DEVICE_DESCRIPTOR *
    >(buf);

  uint8_t rcode;

  UsbDevice *p = NULL;

  EpInfo *oldep_ptr = NULL;


  AddressPool &addrPool =
    pUsb->GetAddressPool();


  if (bAddress) {

    return
      USB_ERROR_CLASS_INSTANCE_ALREADY_IN_USE;
  }


  p =
    addrPool.GetUsbDevicePtr(0);


  if (!p) {

    return
      USB_ERROR_ADDRESS_NOT_FOUND_IN_POOL;
  }


  if (!p->epinfo) {

    return
      USB_ERROR_EPINFO_IS_NULL;
  }


  oldep_ptr = p->epinfo;

  p->epinfo = epInfo;

  p->lowspeed = lowspeed;


  rcode =
    pUsb->getDevDescr(
      0,
      0,
      sizeof(
        USB_DEVICE_DESCRIPTOR
      ),
      buf
    );


  p->epinfo = oldep_ptr;


  if (rcode) {

    return rcode;
  }


  if (
    !VIDPIDOK(
      udd->idVendor,
      udd->idProduct
    )
  ) {

    return
      USB_DEV_CONFIG_ERROR_DEVICE_NOT_SUPPORTED;
  }


  bAddress =
    addrPool.AllocAddress(
      parent,
      false,
      port
    );


  if (!bAddress) {

    return
      USB_ERROR_OUT_OF_ADDRESS_SPACE_IN_POOL;
  }


  epInfo[0].maxPktSize =
    udd->bMaxPacketSize0;


  rcode =
    pUsb->setAddr(
      0,
      0,
      bAddress
    );


  if (rcode) {

    addrPool.FreeAddress(
      bAddress
    );

    bAddress = 0;

    return rcode;
  }


  delay(100);


  p =
    addrPool.GetUsbDevicePtr(
      bAddress
    );


  if (!p) {

    return
      USB_ERROR_ADDRESS_NOT_FOUND_IN_POOL;
  }


  p->lowspeed = lowspeed;


  rcode =
    pUsb->setEpInfoEntry(
      bAddress,
      1,
      epInfo
    );


  if (rcode) {

    return rcode;
  }


  // ==========================================================
  // EXTRAER ENDPOINTS
  // ==========================================================

  ConfigDescParser<
    0xFF,
    0x01,
    0x02,
    CP_MASK_COMPARE_ALL
  > confDescrParser(this);


  rcode =
    pUsb->getConfDescr(
      bAddress,
      0,
      0,
      &confDescrParser
    );


  if (rcode) {

    return rcode;
  }


  if (bNumEP < 2) {

    return
      USB_DEV_CONFIG_ERROR_DEVICE_NOT_SUPPORTED;
  }


  rcode =
    pUsb->setEpInfoEntry(
      bAddress,
      bNumEP,
      epInfo
    );


  if (rcode) {

    return rcode;
  }


  // ==========================================================
  // CONFIGURAR CH340
  // ==========================================================

  rcode =
    pUsb->setConf(
      bAddress,
      0,
      bConfNum
    );


  if (rcode) {

    return rcode;
  }


  // ==========================================================
  // INICIALIZACION CH340
  // ==========================================================

  uint8_t temp[2];


  VendorRead(
    VENDOR_VERSION,
    0,
    0,
    temp,
    2
  );


  VendorWrite(
    VENDOR_SERIAL_INIT,
    0,
    0,
    NULL,
    0
  );


  VendorWrite(
    VENDOR_WRITE,
    0x1312,
    0xD982,
    NULL,
    0
  );


  VendorWrite(
    VENDOR_WRITE,
    0x0F2C,
    0x0004,
    NULL,
    0
  );


  VendorRead(
    VENDOR_READ,
    0x2518,
    0,
    temp,
    2
  );


  VendorWrite(
    VENDOR_WRITE,
    0x2727,
    0,
    NULL,
    0
  );


  VendorWrite(
    VENDOR_MODEM_OUT,
    0x009F,
    0,
    NULL,
    0
  );


  pAsync->OnInit(
    this
  );


  ready = true;


  return 0;
}


// ============================================================
// EXTRAER ENDPOINTS
// ============================================================

void CH340::EndpointXtract(
  uint8_t conf,
  uint8_t iface,
  uint8_t alt,
  uint8_t proto,
  const USB_ENDPOINT_DESCRIPTOR *ep
) {

  bConfNum = conf;

  uint8_t index = 0;


  if (
    (ep->bmAttributes & 0x03) == 2
  ) {

    if (
      ep->bEndpointAddress & 0x80
    ) {

      index =
        EP_DATA_IN;

    } else {

      index =
        EP_DATA_OUT;
    }
  }

  else if (
    (ep->bmAttributes & 0x03) == 3 &&
    (ep->bEndpointAddress & 0x80)
  ) {

    index =
      EP_INT_IN;

  } else {

    return;
  }


  epInfo[index].epAddr =
    ep->bEndpointAddress & 0x0F;

  epInfo[index].maxPktSize =
    ep->wMaxPacketSize;

  epInfo[index].bmSndToggle =
    0;

  epInfo[index].bmRcvToggle =
    0;


  if (
    index >= bNumEP
  ) {

    bNumEP =
      index + 1;
  }
}


// ============================================================
// VENDOR READ
// ============================================================

int CH340::VendorRead(
  uint8_t request,
  uint16_t value,
  uint16_t index,
  uint8_t *buf,
  uint16_t len
) {

  return
    pUsb->ctrlReq(
      bAddress,
      0,
      BMREQ_CH34X_IN,
      request,
      value & 0xFF,
      value >> 8,
      index,
      len,
      len,
      buf,
      NULL
    );
}


// ============================================================
// VENDOR WRITE
// ============================================================

int CH340::VendorWrite(
  uint8_t request,
  uint16_t value,
  uint16_t index,
  uint8_t *buf,
  uint16_t len
) {

  return
    pUsb->ctrlReq(
      bAddress,
      0,
      BMREQ_CH34X_OUT,
      request,
      value & 0xFF,
      value >> 8,
      index,
      len,
      len,
      buf,
      NULL
    );
}


// ============================================================
// CONFIGURAR 2400 8N1
// ============================================================

uint8_t CH340::Set2400() {

  uint8_t rcode;


  // 2400 baud

  rcode =
    VendorWrite(
      VENDOR_WRITE,
      0x1312,
      0xD981,
      NULL,
      0
    );


  if (rcode) {

    return rcode;
  }


  // Offset 2400

  rcode =
    VendorWrite(
      VENDOR_WRITE,
      0x0F2C,
      0x001E,
      NULL,
      0
    );


  if (rcode) {

    return rcode;
  }


  // 8N1 + RX/TX

  rcode =
    VendorWrite(
      VENDOR_WRITE,
      0x2518,
      0x00C3,
      NULL,
      0
    );


  return rcode;
}


// ============================================================
// SEND CH340
// ============================================================

uint8_t CH340::Send(
  uint16_t len,
  uint8_t *data
) {

  if (!ready) {

    return 0xFF;
  }


  return
    pUsb->outTransfer(
      bAddress,
      epInfo[
        EP_DATA_OUT
      ].epAddr,
      len,
      data
    );
}


// ============================================================
// RECEIVE CH340
// ============================================================

uint8_t CH340::Receive(
  uint16_t *len,
  uint8_t *data
) {

  if (!ready) {

    return 0xFF;
  }


  return
    pUsb->inTransfer(
      bAddress,
      epInfo[
        EP_DATA_IN
      ].epAddr,
      len,
      data
    );
}


// ============================================================
// RELEASE
// ============================================================

uint8_t CH340::Release() {

  if (bAddress) {

    pUsb
      ->GetAddressPool()
      .FreeAddress(
        bAddress
      );
  }


  bAddress = 0;
  bNumEP = 1;
  ready = false;


  return
    pAsync->OnRelease(
      this
    );
}


// ============================================================
// POLL
// ============================================================

uint8_t CH340::Poll() {

  return 0;
}


// ============================================================
// OBJETO CH340
// ============================================================

CH340Async ch340Async;

CH340 ch340(
  &Usb,
  &ch340Async
);


// ============================================================
// CONTROL UPS
// ============================================================

bool configurando = false;

// true cuando el CH340 ya fue configurado (una vez por conexion USB)
bool ch340Configurado = false;

bool upsConectada = false;

bool datosValidos = false;

unsigned long ultimoQ1 = 0;

const unsigned long INTERVALO_Q1 =
  60000;


// ============================================================
// CONTROL DE FALLAS
// ============================================================

uint8_t q1FallosConsecutivos = 0;

const uint8_t MAX_FALLOS_Q1 = 3;


// ============================================================
// DATOS UPS
// ============================================================

float voltEntrada = 0;

float voltEntradaFalla = 0;

float voltSalida = 0;

float voltBateria = 0;

float frecuencia = 0;

float temperatura = 0;

int campo4 = 0;

String estadoBits =
  "00000000";


// ============================================================
// ESTADISTICAS
// ============================================================

float entradaMin = 9999;
float entradaMax = -9999;

float entradaFallaMin = 9999;
float entradaFallaMax = -9999;

float salidaMin = 9999;
float salidaMax = -9999;

float bateriaMin = 9999;
float bateriaMax = -9999;

float temperaturaMin = 9999;
float temperaturaMax = -9999;

unsigned long muestras = 0;


// ============================================================
// PARSEAR Q1
// ============================================================

bool parsearQ1(
  uint8_t *rx,
  uint16_t len
) {

  char texto[100];

  uint16_t n = len;


  if (n > 98) {

    n = 98;
  }


  memcpy(
    texto,
    rx,
    n
  );

  texto[n] = '\0';


  Serial.print(
    "Q1 ASCII: "
  );

  Serial.println(
    texto
  );


  int cantidad =
    sscanf(
      texto,
      "(%f %f %f %d %f %f %f",
      &voltEntrada,
      &voltEntradaFalla,
      &voltSalida,
      &campo4,
      &frecuencia,
      &voltBateria,
      &temperatura
    );


  if (
    cantidad < 7
  ) {

    Serial.println(
      "ERROR: Q1 no pudo ser interpretado"
    );

    return false;
  }


  char *ultimo =
    strrchr(
      texto,
      ' '
    );


  if (!ultimo) {

    return false;
  }


  ultimo++;


  char estadoTemp[9] =
    "00000000";

  uint8_t j = 0;


  while (
    *ultimo &&
    *ultimo != ')' &&
    *ultimo != '\r' &&
    *ultimo != '\n' &&
    j < 8
  ) {

    if (
      *ultimo == '0' ||
      *ultimo == '1'
    ) {

      estadoTemp[j++] =
        *ultimo;
    }

    ultimo++;
  }


  if (
    j != 8
  ) {

    Serial.println(
      "ERROR: codigo de estado invalido"
    );

    return false;
  }


  estadoTemp[8] =
    '\0';


  estadoBits =
    String(
      estadoTemp
    );


  // ==========================================================
  // ESTADISTICAS
  // ==========================================================

  if (
    voltEntrada < entradaMin
  )
    entradaMin =
      voltEntrada;

  if (
    voltEntrada > entradaMax
  )
    entradaMax =
      voltEntrada;


  if (
    voltEntradaFalla <
    entradaFallaMin
  )
    entradaFallaMin =
      voltEntradaFalla;

  if (
    voltEntradaFalla >
    entradaFallaMax
  )
    entradaFallaMax =
      voltEntradaFalla;


  if (
    voltSalida < salidaMin
  )
    salidaMin =
      voltSalida;

  if (
    voltSalida > salidaMax
  )
    salidaMax =
      voltSalida;


  if (
    voltBateria < bateriaMin
  )
    bateriaMin =
      voltBateria;

  if (
    voltBateria > bateriaMax
  )
    bateriaMax =
      voltBateria;


  if (
    temperatura < temperaturaMin
  )
    temperaturaMin =
      temperatura;

  if (
    temperatura > temperaturaMax
  )
    temperaturaMax =
      temperatura;


  muestras++;

  datosValidos = true;


  return true;
}


// ============================================================
// MOSTRAR ESTADO UPS
// ============================================================

void mostrarEstadoUPS() {

  Serial.println();

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "             DATOS UPS POWEST"
  );

  Serial.println(
    "=========================================="
  );


  Serial.printf(
    " Entrada          : %.1f V\n",
    voltEntrada
  );

  Serial.printf(
    " Entrada falla    : %.1f V\n",
    voltEntradaFalla
  );

  Serial.printf(
    " Salida           : %.1f V\n",
    voltSalida
  );

  Serial.printf(
    " Campo 4          : %d\n",
    campo4
  );

  Serial.printf(
    " Frecuencia       : %.1f Hz\n",
    frecuencia
  );

  Serial.printf(
    " Bateria          : %.2f V\n",
    voltBateria
  );

  Serial.printf(
    " Temperatura      : %.1f C\n",
    temperatura
  );

  Serial.print(
    " Estado           : "
  );

  Serial.println(
    estadoBits
  );


  bool fallaRed =
    estadoBits.charAt(0) == '1';

  bool bateriaBaja =
    estadoBits.charAt(1) == '1';

  bool avrActivo =
    estadoBits.charAt(2) == '1';

  bool fallaUPS =
    estadoBits.charAt(3) == '1';

  bool standby =
    estadoBits.charAt(4) == '1';

  bool prueba =
    estadoBits.charAt(5) == '1';

  bool apagado =
    estadoBits.charAt(6) == '1';

  bool alarma =
    estadoBits.charAt(7) == '1';


  Serial.println(
    "------------------------------------------"
  );


  if (fallaUPS) {

    Serial.println(
      " ESTADO: FALLA DE UPS"
    );

  }

  else if (fallaRed) {

    Serial.println(
      " ESTADO: FALLA DE RED"
    );

  }

  else if (bateriaBaja) {

    Serial.println(
      " ESTADO: BATERIA BAJA"
    );

  }

  else if (standby) {

    Serial.println(
      " ESTADO: STANDBY"
    );

  }

  else if (prueba) {

    Serial.println(
      " ESTADO: PRUEBA"
    );

  }

  else if (apagado) {

    Serial.println(
      " ESTADO: APAGADO ACTIVO"
    );

  }

  else {

    Serial.println(
      " ESTADO: NORMAL / ONLINE"
    );
  }


  if (avrActivo) {

    Serial.println(
      " [ACTIVO] AVR"
    );
  }


  if (alarma) {

    Serial.println(
      " [ACTIVO] ALARMA"
    );
  }


  Serial.println(
    "=========================================="
  );
}


// ============================================================
// CREAR JSON
// ============================================================

String crearJSON() {

  String json = "{";


  json +=
    "\"entrada\":";

  json +=
    String(
      voltEntrada,
      1
    );


  json +=
    ",\"entrada_falla\":";

  json +=
    String(
      voltEntradaFalla,
      1
    );


  json +=
    ",\"salida\":";

  json +=
    String(
      voltSalida,
      1
    );


  json +=
    ",\"campo4\":";

  json +=
    String(
      campo4
    );


  json +=
    ",\"frecuencia\":";

  json +=
    String(
      frecuencia,
      1
    );


  json +=
    ",\"bateria\":";

  json +=
    String(
      voltBateria,
      2
    );


  json +=
    ",\"temperatura\":";

  json +=
    String(
      temperatura,
      1
    );


  json +=
    ",\"estado\":\"";

  json +=
    estadoBits;


  json +=
    "\",\"ups_conectada\":";

  json +=
    upsConectada
      ? "true"
      : "false";


  json += "}";


  return json;
}


// ============================================================
// DIAGNOSTICO SOCKET
// ============================================================

void diagnosticoSocket() {

  Serial.println();

  Serial.println(
    "========== SOCKET TCP =========="
  );


  Serial.print(
    "Cliente valido : "
  );

  Serial.println(
    clienteEthernet
      ? "SI"
      : "NO"
  );


  Serial.print(
    "Conectado      : "
  );

  Serial.println(
    clienteEthernet.connected()
      ? "SI"
      : "NO"
  );


  Serial.print(
    "Status         : 0x"
  );

  Serial.println(
    clienteEthernet.status(),
    HEX
  );


  Serial.print(
    "IP remota      : "
  );

  Serial.println(
    clienteEthernet.remoteIP()
  );


  Serial.print(
    "Puerto remoto  : "
  );

  Serial.println(
    clienteEthernet.remotePort()
  );


  Serial.print(
    "TX disponible  : "
  );

  Serial.println(
    clienteEthernet.availableForWrite()
  );


  Serial.println(
    "================================"
  );
}


// ============================================================
// ENVIAR TEXTO TCP
// ============================================================

bool enviarTextoTCP(
  const char *texto
) {

  if (
    !clienteTCPActivo ||
    !clienteEthernet
  ) {

    Serial.println(
      "TCP: no hay cliente activo"
    );

    return false;
  }


  if (
    !clienteEthernet.connected()
  ) {

    Serial.println(
      "TCP: cliente desconectado"
    );

    clienteEthernet.stop();

    clienteTCPActivo = false;

    return false;
  }


  size_t longitud =
    strlen(texto);


  size_t bytes =
    clienteEthernet.write(
      (
        const uint8_t *
      )texto,
      longitud
    );


  size_t crlf =
    clienteEthernet.write(
      (
        const uint8_t *
      )"\r\n",
      2
    );


  clienteEthernet.flush();


  Serial.print(
    "TX: "
  );

  Serial.println(
    texto
  );

  Serial.print(
    "BYTES: "
  );

  Serial.println(
    bytes
  );

  Serial.print(
    "CRLF: "
  );

  Serial.println(
    crlf
  );


  if (
    bytes != longitud
  ) {

    Serial.println(
      "TCP: ERROR DE TRANSMISION"
    );

    clienteEthernet.stop();

    clienteTCPActivo = false;

    return false;
  }


  Serial.println(
    "TCP: ENVIO OK"
  );

  return true;
}


// ============================================================
// ENVIAR JSON POR TCP
// ============================================================

void enviarJSONEthernet() {

  if (
    !ethernetInicializado
  ) {

    Serial.println(
      "ERROR TCP: Ethernet no inicializado"
    );

    return;
  }


  if (
    !clienteTCPActivo
  ) {

    Serial.println(
      "ERROR TCP: no hay cliente activo"
    );

    return;
  }


  if (
    !clienteEthernet.connected()
  ) {

    Serial.println(
      "ERROR TCP: cliente desconectado"
    );

    clienteEthernet.stop();

    clienteTCPActivo = false;

    return;
  }


  String json =
    crearJSON();


  Serial.println();

  Serial.println(
    "------------------------------------------"
  );

  Serial.println(
    "ENVIO TCP"
  );

  Serial.print(
    "JSON: "
  );

  Serial.println(
    json
  );


  diagnosticoSocket();


  enviarTextoTCP(
    json.c_str()
  );


  Serial.println(
    "------------------------------------------"
  );
}


// ============================================================
// ENVIAR EVENTO TCP
// ============================================================

void enviarEvento(
  const char *evento
) {

  if (
    !clienteTCPActivo ||
    !clienteEthernet.connected()
  ) {

    return;
  }


  String json =
    "{\"evento\":\"";

  json +=
    evento;

  json +=
    "\",\"ups_conectada\":";

  json +=
    upsConectada
      ? "true"
      : "false";

  json += "}";


  enviarTextoTCP(
    json.c_str()
  );
}


// ============================================================
// REVISAR CLIENTE TCP
// ============================================================

void revisarClienteEthernet() {

  // ==========================================================
  // CLIENTE ACTUAL
  // ==========================================================

  if (
    clienteTCPActivo
  ) {

    if (
      !clienteEthernet.connected()
    ) {

      Serial.println();
      Serial.println(
        "TCP: CLIENTE DESCONECTADO"
      );

      clienteEthernet.stop();

      clienteTCPActivo = false;

    } else {

      // ========================================================
      // WATCHDOG DE INACTIVIDAD
      // Si el PC no envia latido (PING) en 60 segundos,
      // se libera el socket para permitir una nueva conexion limpia.
      // ========================================================

      if (
        millis() - ultimoHandshake > 60000
      ) {

        Serial.println();

        Serial.println(
          "TCP: TIMEOUT DE INACTIVIDAD (60s sin PING/datos)"
        );

        clienteEthernet.stop();

        clienteTCPActivo = false;

        return;
      }


      // ========================================================
      // LEER DATOS DEL PC (LATIDOS Y COMANDOS)
      // ========================================================

      while (
        clienteEthernet.available()
      ) {

        char c =
          clienteEthernet.read();

        Serial.write(c);

        // ======================================================
        // HANDSHAKE / LATIDO PING
        // ======================================================

        if (c == '\n') {

          Serial.println();

          Serial.println(
            "TCP: HANDSHAKE RECIBIDO"
          );

          ultimoHandshake =
            millis();


          enviarTextoTCP(
            "PONG"
          );
        }
      }

      return;
    }
  }


  // ==========================================================
  // BUSCAR NUEVO CLIENTE
  // ==========================================================

  EthernetClient nuevoCliente =
    servidorEthernet.accept();


  if (
    nuevoCliente
  ) {

    Serial.println();

    Serial.println(
      "=========================================="
    );

    Serial.println(
      "       NUEVO CLIENTE TCP"
    );

    Serial.println(
      "=========================================="
    );


    Serial.print(
      "IP remota: "
    );

    Serial.println(
      nuevoCliente.remoteIP()
    );


    Serial.print(
      "Puerto remoto: "
    );

    Serial.println(
      nuevoCliente.remotePort()
    );


    Serial.print(
      "Status: 0x"
    );

    Serial.println(
      nuevoCliente.status(),
      HEX
    );


    Serial.println(
      "=========================================="
    );


    clienteEthernet =
      nuevoCliente;

    clienteTCPActivo =
      true;


    ultimoHandshake =
      millis();


    // ========================================================
    // MENSAJE INICIAL
    // ========================================================

    enviarTextoTCP(
      "TCP_READY"
    );


    // ========================================================
    // ENVIO DE DATOS INMEDIATOS
    // ========================================================

    if (
      datosValidos
    ) {

      delay(50);

      enviarJSONEthernet();

    } else if (
      ch340.isReady()
    ) {

      Serial.println(
        "TCP: Solicitando Q1 inmediato para nuevo cliente..."
      );

      consultarQ1();
    }


    // ========================================================
    // CONEXION PERMANENTE (STREAMING EN TIEMPO REAL)
    // Se mantiene la conexion abierta permanentemente.
    // ========================================================

    Serial.println(
      "TCP: CONEXION ESTABLECIDA Y ACTIVA"
    );
  }
}


// ============================================================
// UPS DESCONECTADA
// ============================================================

void marcarUPSDesconectada() {

  if (
    !upsConectada
  ) {

    return;
  }


  upsConectada =
    false;


  Serial.println();

  Serial.println(
    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  );

  Serial.println(
    "             UPS DESCONECTADA"
  );

  Serial.println(
    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  );

  Serial.println(
    "No se recibe respuesta de Q1."
  );

  Serial.println(
    "El sistema continuara esperando..."
  );


  enviarEvento(
    "ups_desconectada"
  );
}


// ============================================================
// UPS RECONECTADA
// ============================================================

void marcarUPSReconectada() {

  bool estabaDesconectada =
    !upsConectada;


  upsConectada =
    true;


  q1FallosConsecutivos =
    0;


  if (
    estabaDesconectada
  ) {

    Serial.println();

    Serial.println(
      "******************************************"
    );

    Serial.println(
      "        UPS CONECTADA NUEVAMENTE"
    );

    Serial.println(
      "******************************************"
    );

    Serial.println(
      "Comunicacion restablecida."
    );

    Serial.println(
      "El monitoreo continuara normalmente."
    );


    enviarEvento(
      "ups_reconectada"
    );
  }
}


// ============================================================
// CONSULTAR Q1
// ============================================================

void consultarQ1() {

  if (
    !ch340.isReady()
  ) {

    return;
  }


  Serial.println();

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "         ENVIANDO Q1 A LA UPS"
  );

  Serial.println(
    "=========================================="
  );


  // ==========================================================
  // Q1
  // ==========================================================

  uint8_t q1[] = {
    'Q',
    '1',
    '\r'
  };


  uint8_t rcode =
    ch340.Send(
      3,
      q1
    );


  if (
    rcode != 0
  ) {

    Serial.print(
      "ERROR Q1 TX: 0x"
    );

    Serial.println(
      rcode,
      HEX
    );


    q1FallosConsecutivos++;


    if (
      q1FallosConsecutivos >=
      MAX_FALLOS_Q1
    ) {

      marcarUPSDesconectada();
    }


    return;
  }


  Serial.println(
    "Q1 ENVIADO CORRECTAMENTE"
  );


  // ==========================================================
  // ESPERAR RESPUESTA
  // ==========================================================

  uint8_t rx[64];

  uint16_t len = 0;

  unsigned long inicio =
    millis();

  bool respuesta =
    false;


  while (
    millis() - inicio < 1000
  ) {

    Usb.Task();


    // ========================================================
    // IMPORTANTE:
    // Revisar Ethernet durante la espera de Q1
    // ========================================================

    revisarClienteEthernet();


    uint16_t cantidad =
      sizeof(rx);


    rcode =
      ch340.Receive(
        &cantidad,
        rx
      );


    if (
      rcode == 0 &&
      cantidad > 0
    ) {

      len =
        cantidad;

      respuesta =
        true;

      break;
    }


    delay(10);
  }


  // ==========================================================
  // SIN RESPUESTA
  // ==========================================================

  if (
    !respuesta
  ) {

    Serial.println(
      "NO SE RECIBIO RESPUESTA DE Q1"
    );


    q1FallosConsecutivos++;


    Serial.print(
      "Fallos consecutivos: "
    );

    Serial.println(
      q1FallosConsecutivos
    );


    if (
      q1FallosConsecutivos >=
      MAX_FALLOS_Q1
    ) {

      marcarUPSDesconectada();
    }


    return;
  }


  // ==========================================================
  // RESPUESTA RECIBIDA
  // ==========================================================

  Serial.print(
    "RESPUESTA UPS ("
  );

  Serial.print(
    len
  );

  Serial.println(
    " bytes)"
  );


  Serial.print(
    "HEX: "
  );


  for (
    uint16_t i = 0;
    i < len;
    i++
  ) {

    if (
      rx[i] < 16
    ) {

      Serial.print(
        "0"
      );
    }


    Serial.print(
      rx[i],
      HEX
    );

    Serial.print(
      " "
    );
  }


  Serial.println();


  // ==========================================================
  // PARSEAR
  // ==========================================================

  if (
    !parsearQ1(
      rx,
      len
    )
  ) {

    Serial.println(
      "ERROR PARSEANDO Q1"
    );


    q1FallosConsecutivos++;


    if (
      q1FallosConsecutivos >=
      MAX_FALLOS_Q1
    ) {

      marcarUPSDesconectada();
    }


    return;
  }


  // ==========================================================
  // Q1 CORRECTO
  // ==========================================================

  q1FallosConsecutivos =
    0;


  marcarUPSReconectada();


  mostrarEstadoUPS();


  // ==========================================================
  // ENVIAR AL PC
  // ==========================================================

  enviarJSONEthernet();
}


// ============================================================
// INICIALIZAR ETHERNET
// ============================================================

void inicializarEthernet() {

  Serial.println();

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "       INICIALIZANDO ENC28J60"
  );

  Serial.println(
    "=========================================="
  );


  Ethernet.init(
    PIN_CS_ETH
  );


  Serial.print(
    "CS ENC28J60: GPIO "
  );

  Serial.println(
    PIN_CS_ETH
  );


  Serial.println(
    "Configurando IP fijo..."
  );


  Ethernet.begin(
    mac,
    ipUPS,
    dnsServerIP,
    gatewayIP,
    subnetIP
  );


  delay(1000);


  if (
    Ethernet.linkStatus() ==
    LinkOFF
  ) {

    Serial.println(
      "ADVERTENCIA: cable Ethernet no detectado."
    );

  } else {

    Serial.println(
      "LINK ETHERNET: OK"
    );
  }


  Serial.println(
    "ETHERNET: OK"
  );


  Serial.print(
    "IP ESP32: "
  );

  Serial.println(
    Ethernet.localIP()
  );


  Serial.print(
    "Mascara: "
  );

  Serial.println(
    Ethernet.subnetMask()
  );


  Serial.print(
    "Gateway: "
  );

  Serial.println(
    Ethernet.gatewayIP()
  );


  Serial.print(
    "DNS: "
  );

  Serial.println(
    Ethernet.dnsServerIP()
  );


  servidorEthernet.begin();


  Serial.print(
    "Servidor TCP iniciado en puerto "
  );

  Serial.println(
    PUERTO_TCP
  );


  Serial.println(
    "=========================================="
  );


  ethernetInicializado =
    true;
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(
    115200
  );


  delay(1000);


  Serial.println();

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "       MONITOR UPS POWEST"
  );

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "ESP32 + MAX3421E + CH340 + ENC28J60"
  );

  Serial.println();


  // ==========================================================
  // SPI
  // ==========================================================

  Serial.println(
    "Inicializando SPI..."
  );


  SPI.begin(
    PIN_SCK,
    PIN_MISO,
    PIN_MOSI,
    PIN_CS_USB
  );


  Serial.println(
    "SPI: OK"
  );


  // ==========================================================
  // USB HOST
  // ==========================================================

  Serial.println(
    "Inicializando MAX3421E..."
  );


  if (
    Usb.Init() == -1
  ) {

    Serial.println(
      "ERROR: MAX3421E"
    );


    while (1) {

      delay(1000);
    }
  }


  Serial.println(
    "MAX3421E: OK"
  );


  // ==========================================================
  // ETHERNET
  // ==========================================================

  inicializarEthernet();


  // ==========================================================
  // PRIMER Q1 INMEDIATO
  // ==========================================================

  ultimoQ1 =
    millis() -
    INTERVALO_Q1;


  Serial.println();

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "             SISTEMA LISTO"
  );

  Serial.println(
    "=========================================="
  );

  Serial.println(
    "IP ESP32     : 192.168.1.60"
  );

  Serial.println(
    "Puerto TCP   : 7660"
  );

  Serial.println(
    "PC esperado  : 192.168.1.50"
  );

  Serial.println(
    "Q1           : cada 60 segundos"
  );

  Serial.println(
    "Esperando UPS..."
  );

  Serial.println(
    "=========================================="
  );
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  // ==========================================================
  // USB HOST
  // ==========================================================

  Usb.Task();


  // ==========================================================
  // TCP
  // ==========================================================

  revisarClienteEthernet();


  // ==========================================================
  // DETECTAR CH340
  // ==========================================================

  if (
    ch340.isReady() &&
    !configurando &&
    !ch340Configurado
  ) {

    configurando =
      true;


    Serial.println();

    Serial.println(
      "***************************************"
    );

    Serial.println(
      "CH340 DETECTADO"
    );

    Serial.println(
      "Configurando UPS a 2400 8N1..."
    );

    Serial.println(
      "***************************************"
    );


    delay(200);


    uint8_t rcode =
      ch340.Set2400();


    if (
      rcode == 0
    ) {

      Serial.println(
        "CH340 CONFIGURADO: 2400 8N1"
      );

      Serial.println(
        "COMUNICACION UPS: OK"
      );


      configurando =
        false;

      ch340Configurado =
        true;


      ultimoQ1 =
        millis() -
        INTERVALO_Q1;

    } else {

      Serial.print(
        "ERROR CONFIGURANDO CH340: 0x"
      );

      Serial.println(
        rcode,
        HEX
      );


      configurando =
        false;

      delay(2000);
    }
  }


  // ==========================================================
  // UPS NO DISPONIBLE
  // ==========================================================

  if (
    !ch340.isReady()
  ) {

    if (
      upsConectada
    ) {

      marcarUPSDesconectada();
    }


    configurando =
      false;

    ch340Configurado =
      false;
  }


  // ==========================================================
  // Q1 CADA 60 SEGUNDOS
  // ==========================================================

  if (
    ch340.isReady()
  ) {

    if (
      millis() - ultimoQ1 >=
      INTERVALO_Q1
    ) {

      ultimoQ1 =
        millis();


      consultarQ1();
    }
  }


  delay(5);
}