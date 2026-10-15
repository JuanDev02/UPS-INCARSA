(function(){
  "use strict";

  /* ==========================================================================
     CENTINELA · SISTEMA DE MONITOREO DE UPS INCARSA
     CONTROLADOR PRINCIPAL REACTIVO CON ALPINE.JS (scripts.js)
     ==========================================================================
     Este archivo gestiona toda la lógica reactiva del frontend de Centinela:
     - Máquina de estados para pantallas (Login -> Boot -> App).
     - Autenticación segura y control de roles (Admin / Supervisor) vía Django.
     - Navegación SPA instantánea sin recarga de página.
     - Catálogo de flota (30 UPS), búsqueda en tiempo real y KPIs calculados.
     - Telemetría en vivo, tacómetros SVG y decodificación de protocolo Megatec.
     - Simulación de cortes eléctricos y auditoría auditable con exportación CSV/PDF.
     - Configuración de parámetros y modales reactivos.
     ========================================================================== */

  const root = document.documentElement;

  // Recupera el tema guardado por el usuario en localStorage ('dark' o 'light')
  let savedTheme = null;
  try {
    savedTheme = localStorage.getItem('centinela-theme');
  } catch(e){}


  /* ==========================================================================
     [SECCIÓN 0] UTILIDADES GLOBALES Y GENERACIÓN DE DATOS SEMILLA
     ==========================================================================
     Funciones de apoyo puro de JavaScript utilizadas por el componente
     Alpine para seguridad, notificaciones, matemáticas y datos iniciales.
     ========================================================================== */

  /**
   * Obtiene el token CSRF para peticiones HTTP POST seguras contra Django.
   * Busca primero el input oculto {% csrf_token %} y luego la cookie 'csrftoken'.
   * @returns {string} Token CSRF válido.
   */
  function getCsrfToken(){
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    if(input) return input.value;
    const cookie = document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
  }

  /**
   * Despliega notificaciones flotantes temporales (Toasts) en pantalla.
   * Se auto-destruyen a los 3.2 segundos con animación CSS suave.
   * @param {string} msg - Mensaje a mostrar.
   * @param {boolean} warn - true para alerta roja/advertencia, false para confirmación verde.
   */
  function toast(msg, warn){
    const host = document.getElementById('toast-host');
    if(!host) return;
    const el = document.createElement('div');
    el.className = 'toast' + (warn ? ' warn' : '');
    el.innerHTML = (warn
      ? '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2.4"><circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16h.01"/></svg>'
      : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.4"><path d="M20 6 9 17l-5-5"/></svg>'
    ) + '<span>' + msg + '</span>';
    host.appendChild(el);
    setTimeout(() => {
      el.style.animation = 'toast-in .25s ease reverse forwards';
      setTimeout(() => el.remove(), 260);
    }, 3200);
  }

  // Ayudantes matemáticos para simulación de lecturas físicas fluctuantes
  function rnd(base, spread){ return base + (Math.random() - 0.5) * spread; }
  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }

  // Catálogo de sedes en Colombia para distribución del inventario
  const fleetLocs = [
    ['Sala de Servidores', 'Bogotá'], ['Oficina Cali', 'Cali'], ['Datacenter Sur', 'Bogotá'], ['Bodega Norte', 'Medellín'],
    ['Piso 3 · Administración', 'Bogotá'], ['Planta Eléctrica', 'Barranquilla'], ['Torre B · Rack 2', 'Bogotá'],
    ['Sucursal Medellín', 'Medellín'], ['Almacén Central', 'Cali'], ['Recepción Principal', 'Bogotá'],
    ['Centro de Datos', 'Bucaramanga'], ['Rack Telecom', 'Pereira']
  ];

  /**
   * Genera el catálogo inicial de 30 equipos con estados simulados:
   * - En red normal (verde)
   * - En batería (rojo)
   * - Desconectadas sin comunicación (ámbar)
   * @returns {Array<Object>} Lista de 30 objetos UPS.
   */
  function buildFleetData(){
    const batteryIdx = [3, 11, 19];
    const offlineIdx = [8, 24];
    const items = [];
    for(let i = 0; i < 30; i++){
      const loc = fleetLocs[i % fleetLocs.length];
      let status = 'online';
      if(batteryIdx.includes(i)) status = 'battery';
      if(offlineIdx.includes(i)) status = 'offline';
      const battery = status === 'offline' ? null : Math.round(clamp(rnd(status === 'battery' ? 55 : 90, status === 'battery' ? 40 : 16), 4, 100));
      const load = status === 'offline' ? null : Math.round(clamp(rnd(46, 22), 5, 98));
      items.push({
        id: i + 1,
        name: 'UPS-' + String(i + 1).padStart(2, '0'),
        loc: loc[0] + ' · ' + loc[1],
        status,
        battery,
        load,
        alert: status === 'offline' || (battery !== null && battery < 20)
      });
    }
    return items;
  }

  /**
   * Genera el historial inicial de auditoría para la pestaña de Eventos.
   * Simula cortes de energía previos, caídas de enlace TCP y sobretensiones.
   * @returns {Array<Object>} Lista de eventos históricos.
   */
  function seedEventsData(){
    const now = Date.now();
    return [
      {tipo: 'battery', label: 'Modo batería', inicio: new Date(now - 3600e3 * 5), fin: new Date(now - 3600e3 * 5 + 228e3), dur: '3m 48s', detalle: 'Corte de red detectado — recuperado automáticamente'},
      {tipo: 'comm', label: 'Desconexión TCP', inicio: new Date(now - 3600e3 * 20), fin: new Date(now - 3600e3 * 20 + 9e3), dur: '9s', detalle: 'Pérdida momentánea de enlace con el ESP32'},
      {tipo: 'info', label: 'Sobretensión detectada', inicio: new Date(now - 3600e3 * 30), fin: new Date(now - 3600e3 * 30 + 2e3), dur: '2s', detalle: 'Pico de 134V en entrada'},
      {tipo: 'battery', label: 'Modo batería', inicio: new Date(now - 3600e3 * 48), fin: new Date(now - 3600e3 * 48 + 612e3), dur: '10m 12s', detalle: 'Corte de red prolongado'},
      {tipo: 'comm', label: 'Reconexión establecida', inicio: new Date(now - 3600e3 * 72), fin: new Date(now - 3600e3 * 72), dur: '—', detalle: 'Enlace restablecido tras reinicio del ESP32'}
    ];
  }

  // Mensajes secuenciales que se muestran durante la animación del preloader
  const bootSteps = [
    'Estableciendo sesión…',
    'Abriendo socket TCP → 192.168.1.50:4196…',
    'Sincronizando protocolo Megatec…',
    'Cargando lecturas históricas…',
    'Listo.'
  ];


  /* ==========================================================================
     [COMPONENTE MAESTRO REACTIVO: centinelaApp]
     ==========================================================================
     Registrado en Alpine vía 'alpine:init'. Todo el estado se vincula al <body>
     mediante <body x-data="centinelaApp" :data-theme="theme">.
     ========================================================================== */

  document.addEventListener('alpine:init', () => {
    Alpine.data('centinelaApp', () => ({

      /* ------------------------------------------------------------------------
         [SECCIÓN 1] MÁQUINA DE PANTALLAS Y GESTIÓN DE TEMAS (DARK / LIGHT)
         ------------------------------------------------------------------------
         - Controla qué pantalla principal ve el usuario:
           'login' -> Formulario de inicio de sesión
           'boot'  -> Preloader con anillo de progreso
           'app'   -> Panel principal de monitoreo
         - Alterna el tema visual y redibuja las gráficas de Chart.js con la paleta adecuada.
         ------------------------------------------------------------------------ */
      screen: 'login', // 'login' | 'boot' | 'app'
      theme: savedTheme,
      
      /**
       * Getter computado: determina si la interfaz debe mostrarse en modo oscuro.
       */
      get isDark() {
        return this.theme === 'dark' || (!this.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
      },

      /**
       * Alterna entre modo claro y oscuro, persiste en localStorage
       * y refresca los colores de Chart.js si la vista histórica está visible.
       */
      toggleTheme() {
        const next = this.isDark ? 'light' : 'dark';
        this.theme = next;
        root.setAttribute('data-theme', next);
        try { localStorage.setItem('centinela-theme', next); } catch(e){}
        if(typeof window.renderHistorico === 'function'){
          window.renderHistorico(this.currentRange);
        }
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 2] AUTENTICACIÓN, PRELOADER Y SESIÓN CON DJANGO
         ------------------------------------------------------------------------
         - Enlace bidireccional con el formulario de login vía x-model.
         - Petición asíncrona a '/api/login/' con firma CSRF.
         - Animación secuencial del preloader (anillo circular SVG y textos).
         - Verificación automática de sesión existente ('/api/me/').
         - Cierre de sesión seguro ('/api/logout/').
         ------------------------------------------------------------------------ */
      credentials: { username: '', password: '', remember: true },
      loginError: '',
      loginLoading: false,
      user: null, // { username, name, role, is_admin }

      /**
       * Procesa el login enviando las credenciales al backend Django.
       */
      async submitLogin() {
        const u = this.credentials.username.trim();
        const p = this.credentials.password.trim();
        if(!u || !p){
          this.loginError = 'Ingresa tu usuario y contraseña.';
          return;
        }

        this.loginLoading = true;
        this.loginError = '';

        try {
          const res = await fetch('/api/login/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
              username: u,
              password: p,
              remember: !!this.credentials.remember
            })
          });
          const data = await res.json();

          if(data.ok && data.user){
            try {
              if (this.credentials.remember) {
                localStorage.setItem('centinela_remember_username', u);
              } else {
                localStorage.removeItem('centinela_remember_username');
              }
            } catch(e) {}

            this.user = data.user;
            this.startBoot(); // Inicia la animación de encendido
          } else {
            this.loginError = data.error || 'Credenciales incorrectas.';
          }
        } catch(err){
          this.loginError = 'Error de conexión con el servidor.';
        } finally {
          this.loginLoading = false;
        }
      },

      // Variables y getters para el Preloader de inicio
      bootPct: 0,
      bootLog: bootSteps[0],

      /**
       * Calcula el stroke-dashoffset del círculo SVG del preloader (radio = 35).
       * Perímetro = 2 * PI * 35 = ~219.9
       */
      get bootStrokeOffset() {
        const c = 2 * Math.PI * 35;
        return c - (c * this.bootPct / 100);
      },

      /**
       * Ejecuta la animación secuencial de inicialización antes de abrir el dashboard.
       */
      startBoot() {
        this.screen = 'boot';
        this.bootPct = 0;
        let step = 0;

        const next = () => {
          step++;
          this.bootPct = Math.min(100, Math.round((step / bootSteps.length) * 100));
          this.bootLog = bootSteps[Math.min(step, bootSteps.length) - 1] || '';

          if(step < bootSteps.length){
            setTimeout(next, 380);
          } else {
            setTimeout(() => {
              this.screen = 'app';
              this.initAppServices();
            }, 350);
          }
        };

        setTimeout(next, 200);
      },

      /**
       * Cierra la sesión activa en Django y recarga la página.
       */
      async logout() {
        try {
          await fetch('/api/logout/', {
            method: 'POST',
            headers: {'X-CSRFToken': getCsrfToken()}
          });
        } catch(e){}
        location.reload();
      },

      /**
       * Auto-login: Comprueba si el navegador ya cuenta con una sesión activa en Django.
       */
      async verifySession() {
        try {
          const res = await fetch('/api/me/');
          const data = await res.json();
          if(data.authenticated && data.user){
            this.user = data.user;
            if(this.user.is_admin) {
              this.fetchUsers();
            }
            this.screen = 'app';
            this.initAppServices();
          }
        } catch(e){}
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 3] NAVEGACIÓN SPA Y SELECTOR DE RANGOS HISTÓRICOS
         ------------------------------------------------------------------------
         - Cambia instantáneamente entre vistas ('flota', 'monitor', 'historico', etc.)
           usando x-show="currentView === '...'" sin recargar la página.
         - Control de acceso por rol (solo administradores pueden abrir 'config').
         - Selección y sincronización de rangos temporales para Chart.js.
         ------------------------------------------------------------------------ */
      currentView: 'panel',
      mobileMenuOpen: false,
      currentRange: '1h',

      /**
       * Getter computado: indica si el usuario está en una vista de nivel general (flota / catálogo)
       * o si está inspeccionando los detalles de una UPS individual.
       */
      get isGlobalView() {
        return this.currentView === 'panel' || this.currentView === 'config';
      },

      /**
       * Cambia la vista activa del panel con validación de roles de usuario.
       * @param {string} view - Identificador de la vista.
       */
      setView(view) {
        if(view === 'flota') view = 'panel';
        if(!this.user?.is_admin && (view === 'config' || view === 'device-config')){
          view = 'panel'; // Restringe acceso a configuración para supervisores
        }
        this.currentView = view;
        this.mobileMenuOpen = false;
        if(view === 'config' && this.user?.is_admin){
          this.fetchUsers();
        }
        if(view === 'historico' && typeof window.renderHistorico === 'function'){
          setTimeout(() => window.renderHistorico(this.currentRange, this.selectedDevice.id), 50);
        }
        if(view === 'eventos'){
          this.fetchEvents();
        }
      },

      /**
       * Cambia el intervalo temporal de análisis y re-dibuja las gráficas de Chart.js.
       * @param {string} range - '1h' | '24h' | '7d' | '30d'
       */
      setRange(range) {
        this.currentRange = range;
        if(typeof window.renderHistorico === 'function'){
          window.renderHistorico(range, this.selectedDevice.id);
        }
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 4] CATÁLOGO DE LA FLOTA (30 UPS), BÚSQUEDA Y KPIs
         ------------------------------------------------------------------------
         - Almacena el inventario de las 30 unidades monitoreadas.
         - Getters computados en tiempo real para las 4 tarjetas de KPIs superiores.
         - Filtro reactivo en vivo por texto (x-model="fleetSearch") y botones de estado.
         - Transición al monitor individual al hacer clic en cualquier tarjeta.
         ------------------------------------------------------------------------ */
      fleet: [],
      fleetSearch: '',
      fleetFilter: 'todas', // 'todas' | 'battery' | 'alert' | 'offline'
      upsDropdownOpen: false,
      upsNavSearch: '',

      /**
       * Getter computado: Lista de UPS filtrada para el buscador del dropdown en el navbar.
       */
      get dropdownFleet() {
        const q = this.upsNavSearch.trim().toLowerCase();
        if(!q) return this.fleet;
        return this.fleet.filter(f =>
          (f.name && f.name.toLowerCase().includes(q)) ||
          (f.loc && f.loc.toLowerCase().includes(q)) ||
          (f.host && f.host.toLowerCase().includes(q))
        );
      },

      /**
       * Getter computado: Objeto de la UPS activa seleccionada actualmente en la flota.
       */
      get activeDevice() {
        return this.fleet.find(f => f.id === this.selectedDevice.id) || null;
      },

      /**
       * Getter computado: Estado ('online', 'battery', 'offline') de la UPS actualmente seleccionada.
       */
      get activeDeviceStatus() {
        const dev = this.activeDevice;
        if(dev && dev.status) return dev.status;
        if(this.telemetry.onBattery) return 'battery';
        return 'online';
      },

      /**
       * Getter computado: Etiqueta legible en español del estado de la UPS activa.
       */
      get activeDeviceStatusLabel() {
        const st = this.activeDeviceStatus;
        if(st === 'battery') return 'En batería';
        if(st === 'offline') return 'Sin enlace';
        return 'En red';
      },

      /**
       * Selecciona una UPS desde el dropdown del navbar y mantiene la vista actual.
       */
      selectDeviceFromNav(f) {
        this.selectDevice(f, true);
        this.upsDropdownOpen = false;
      },

      /**
       * Getter computado: Calcula automáticamente los totales de la flota.
       */
      get kpis() {
        const total = this.fleet.length;
        const enBateria = this.fleet.filter(f => f.status === 'battery').length;
        const alertas = this.fleet.filter(f => f.alert).length;
        const desconectadas = this.fleet.filter(f => f.status === 'offline').length;
        return {
          total,
          enBateria,
          alertas,
          desconectadas,
          enLinea: Math.max(0, total - desconectadas - enBateria)
        };
      },

      /**
       * Getter computado: Filtra las tarjetas de UPS según búsqueda y chip activo.
       */
      get filteredFleet() {
        const q = this.fleetSearch.trim().toLowerCase();
        return this.fleet.filter(f => {
          if(q && !(f.name.toLowerCase().includes(q) || f.loc.toLowerCase().includes(q))) return false;
          if(this.fleetFilter === 'battery') return f.status === 'battery';
          if(this.fleetFilter === 'alert') return f.alert;
          if(this.fleetFilter === 'offline') return f.status === 'offline';
          return true;
        });
      },

      /**
       * Selecciona una UPS de la flota y actualiza telemetría y configuración.
       * @param {Object} f - Objeto UPS seleccionado.
       * @param {boolean} stayInView - Si es true, permanece en la vista actual en lugar de saltar a 'monitor'.
       */
      selectDevice(f, stayInView = false) {
        this.selectedDevice.id = f.id;
        this.selectedDevice.name = f.name;
        this.selectedDevice.loc = f.loc + (f.host ? ` · ${f.host}:${f.port}` : '');
        this.quickConfig.name = f.name;
        this.quickConfig.loc = f.loc;
        this.quickConfig.ip = f.host || '127.0.0.1';
        this.quickConfig.port = String(f.port || '7660');
        this.telemetry.status = f.status;
        if(f.status === 'offline') {
          this.telemetry.vin = 0.0;
          this.telemetry.vout = 0.0;
          this.telemetry.hz = 0.0;
          this.telemetry.load = 0;
          this.telemetry.battery = 0;
          this.telemetry.temp = 0.0;
          this.telemetry.onBattery = false;
          this.telemetry.status_q1 = '00000000';
          this.telemetry.q1_bits = {};
        }
        this.loadDeviceConfig(f.id);
        this.fetchLiveTelemetry(f.id);

        if(!stayInView) {
          toast('Abriendo detalle de ' + f.name + '…');
          this.setView('monitor');
        } else {
          toast('UPS seleccionada: ' + f.name);
          if(this.currentView === 'historico' && typeof window.renderHistorico === 'function'){
            window.renderHistorico(this.currentRange, f.id);
          }
        }
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 5] TELEMETRÍA EN VIVO, PROTOCOLO MEGATEC Y SIMULADOR DE CORTE
         ------------------------------------------------------------------------
         - Almacena las variables eléctricas en tiempo real (Vin, Vout, Hz, %, °C).
         - Mapeo y decodificación de los 8 bits de estado del comando Megatec Q1.
         - Tacómetros y arcos SVG calculados matemáticamente.
         - Modo demostración: Interruptor de corte de energía que simula fallas de red
           y registra automáticamente los incidentes en la tabla de auditoría.
         ------------------------------------------------------------------------ */
      currentTime: Date.now(),

      selectedDevice: {
        id: null,
        name: 'UPS-Servidores-01',
        loc: 'Sala de servidores · 192.168.1.50:4196'
      },

      telemetry: {
        vin: 0.0,
        vout: 0.0,
        hz: 0.0,
        load: 0,
        battery: 0,
        temp: 0.0,
        status: 'offline',
        onBattery: false,
        statusChangedAt: null,
        statusDurationSeconds: 0,
        lastRead: Date.now(),
        lastReadText: 'hace 1s'
      },

      // Catálogo descriptivo de los 8 bits del protocolo Megatec (Q1)
      bitLabels: [
        {name: 'Falla de red eléctrica', key: 'a'},
        {name: 'Batería baja', key: 'b'},
        {name: 'Bypass / boost activo', key: 'c'},
        {name: 'Falla de UPS', key: 'd'},
        {name: 'Tipo standby', key: 'e'},
        {name: 'Prueba en progreso', key: 'f'},
        {name: 'Apagado programado', key: 'g'},
        {name: 'Beeper encendido', key: 'h'}
      ],

      /**
       * Evalúa si un LED del protocolo Megatec debe encenderse según la telemetría actual.
       * @param {string} key - Clave del bit ('a'..'h').
       * @returns {boolean} Estado activo/inactivo.
       */
      isBitActive(key) {
        if(this.activeDeviceStatus === 'offline' || this.telemetry.status === 'offline') {
          return false;
        }
        const q = this.telemetry.q1_bits;
        if(q) {
          if(key === 'a') return q.utility_fail || this.telemetry.onBattery;
          if(key === 'b') return q.battery_low || this.telemetry.battery < 20;
          if(key === 'c') return q.bypass_boost;
          if(key === 'd') return q.ups_failed;
          if(key === 'e') return q.standby;
          if(key === 'f') return q.test_in_progress;
          if(key === 'g') return q.shutdown_active;
          if(key === 'h') return q.beeper_on;
        }
        if(key === 'a') return this.telemetry.onBattery;
        if(key === 'b') return this.telemetry.battery < 20;
        if(key === 'd' || key === 'h') return this.telemetry.battery < 10;
        return false;
      },

      /**
       * Helper: Formatea segundos a HH:MM:SS
       */
      formatDuration(totalSecs) {
        if(totalSecs === undefined || totalSecs === null || isNaN(totalSecs)) return '00:00:00';
        const s = Math.max(0, Math.floor(totalSecs));
        const hh = String(Math.floor(s / 3600)).padStart(2, '0');
        const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
        const ss = String(s % 60).padStart(2, '0');
        return `${hh}:${mm}:${ss}`;
      },

      /**
       * Getter computado: Texto de etiqueta según el estado de la UPS seleccionada.
       */
      get statusTimerLabel() {
        const dev = this.activeDevice;
        const st = (dev && dev.status) || this.telemetry.status;
        if(st === 'battery' || this.telemetry.onBattery) return 'En batería hace';
        if(st === 'offline') return 'Descomunicada hace';
        return 'En red eléctrica hace';
      },

      /**
       * Getter computado: Calcula el tiempo activo en formato HH:MM:SS basado en la fecha persistida en la BD.
       * Se re-evalúa reactivamente en cada segundo gracias a currentTime (sin resetear al recargar la página).
       */
      get uptime() {
        const _tick = this.currentTime; // Dependencia reactiva que cambia cada 1s
        const now = Date.now();
        const dev = this.activeDevice;

        let start = this.telemetry.statusChangedAt;
        if(!start && dev && dev.status_changed_at) {
          start = new Date(dev.status_changed_at).getTime();
        }
        if(!start && dev && dev.status_duration_seconds !== undefined) {
          start = now - (dev.status_duration_seconds * 1000);
        }
        if(!start) {
          return '00:00:00';
        }
        const secs = Math.max(0, (now - start) / 1000);
        return this.formatDuration(secs);
      },

      /**
       * Helper para tarjetas de flota: Obtiene el tiempo en estado de cualquier UPS de la lista
       */
      getDeviceDuration(f) {
        const _tick = this.currentTime;
        if(!f) return '00:00:00';
        let start = f.status_changed_at ? new Date(f.status_changed_at).getTime() : null;
        if(!start && f.status_duration_seconds !== undefined) {
          start = Date.now() - (f.status_duration_seconds * 1000);
        }
        if(!start) return '00:00:00';
        return this.formatDuration((Date.now() - start) / 1000);
      },

      /**
       * Calcula y formatea la autonomía según la capacidad total de la batería
       * (1 hora y 30 minutos = 90 minutos de respaldo al 100%).
       * @param {number} pct - Porcentaje de carga (0-100%).
       */
      formatAutonomy(pct) {
        if(!pct || pct <= 0) return '0 min';
        // 90 minutos totales al 100% de batería (1 hora y 30 minutos)
        const totalMinutes = Math.max(1, Math.round((pct / 100) * 90));
        if(totalMinutes < 60) {
          return `${totalMinutes} min`;
        }
        const hours = Math.floor(totalMinutes / 60);
        const mins = totalMinutes % 60;
        return mins > 0 ? `${hours}h ${mins} min` : `${hours}h`;
      },

      /**
       * Getter computado: Subtítulo dinámico con estimación de autonomía de descarga.
       */
      get batterySubtitle() {
        if(this.activeDeviceStatus === 'offline' || this.telemetry.status === 'offline') {
          return 'Sin comunicación con la UPS';
        }
        const pct = this.telemetry.battery || 0;
        const autonomyText = this.formatAutonomy(pct);
        if(this.telemetry.onBattery) {
          return `Descargando · autonomía ~${autonomyText}`;
        }
        return pct >= 98
          ? `Batería cargada · autonomía ~${autonomyText}`
          : `En carga · autonomía estimada ~${autonomyText}`;
      },

      /**
       * Getter computado: Color de la barra de carga según umbrales de seguridad.
       */
      get cargaColor() {
        if(this.activeDeviceStatus === 'offline' || this.telemetry.status === 'offline') return 'var(--text-faint)';
        return this.telemetry.load > 85 ? 'var(--red)' : (this.telemetry.load > 65 ? 'var(--amber)' : 'var(--purple)');
      },

      /**
       * Getter computado: Calcula el arco circular SVG para el anillo de batería.
       * Radio = 16 -> Perímetro = 2 * PI * 16 = ~100.5
       */
      get batteryStrokeOffset() {
        if(this.activeDeviceStatus === 'offline' || this.telemetry.status === 'offline' || !this.telemetry.battery) return 100.5;
        const r = 16;
        const c = 2 * Math.PI * r;
        return c - (c * this.telemetry.battery / 100);
      },

      // Marca de tiempo del corte de red simulado
      outageStartedAt: null,

      /**
       * Activa/desactiva la simulación de corte de suministro eléctrico.
       * Al restaurar la red, calcula la duración del corte e inserta un evento en auditoría.
       * @param {boolean} checked - true = sin luz (batería), false = red eléctrica OK.
       */
      toggleOutage(checked) {
        this.telemetry.onBattery = checked;
        if(checked){
          this.outageStartedAt = new Date();
          toast(this.selectedDevice.name + ' entró en modo batería', true);
        } else {
          if(this.outageStartedAt){
            const end = new Date();
            const durSec = Math.round((end - this.outageStartedAt) / 1000);
            const evData = {
              tipo: 'battery',
              label: 'Modo batería',
              inicio: this.outageStartedAt,
              fin: end,
              dur: durSec + 's',
              detalle: 'Corte de red simulado desde el panel'
            };
            this.events.unshift(evData);

            // Persistir evento en base de datos mediante la API REST
            fetch('/api/eventos/', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
              },
              body: JSON.stringify({
                device_id: this.selectedDevice.id,
                event_type: 'battery_mode',
                severity: 'critical',
                started_at: this.outageStartedAt.toISOString(),
                ended_at: end.toISOString(),
                detail: 'Corte de red simulado desde el panel de control'
              })
            }).catch(() => {});

            this.outageStartedAt = null;
          }
          toast('Red eléctrica restablecida');
        }
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 6] AUDITORÍA DE EVENTOS, FILTROS Y EXPORTACIÓN (CSV / PDF)
         ------------------------------------------------------------------------
         - Almacena el historial auditable de incidencias de energía y enlace TCP.
         - Filtrado dinámico por categorías ('todos', 'battery', 'comm', 'info').
         - Formateo de fechas y horas en horario estándar de Colombia.
         - Generación dinámica y descarga de archivo CSV sin librerías externas.
         - Exportación a PDF mediante la API nativa de impresión del navegador.
         ------------------------------------------------------------------------ */
      events: [],
      eventFilter: 'todos',

      /**
       * Consulta los eventos reales desde la API REST /api/eventos/
       */
      async fetchEvents() {
        try {
          const devId = this.selectedDevice?.id;
          const filterParam = this.eventFilter !== 'todos' ? `&tipo=${this.eventFilter}` : '';
          const url = devId ? `/api/dispositivos/${devId}/eventos/?limit=50${filterParam}` : `/api/eventos/?limit=50${filterParam}`;
          const res = await fetch(url);
          const data = await res.json();
          if(data.ok && Array.isArray(data.events) && data.events.length > 0) {
            this.events = data.events;
          } else if(this.events.length === 0) {
            this.events = seedEventsData();
          }
        } catch(e) {
          if(this.events.length === 0) this.events = seedEventsData();
        }
      },

      /**
       * Getter computado: Filtra los eventos mostrados en el cuerpo de la tabla.
       */
      get filteredEvents() {
        return this.events.filter(e => this.eventFilter === 'todos' || e.tipo === this.eventFilter);
      },

      /**
       * Formatea fechas y horas de forma clara, legible y profesional:
       * Ejemplo: "14 Oct 2026, 04:05:48 PM"
       * @param {Date|string} d - Fecha a formatear.
       * @returns {string} Fecha formateada.
       */
      fmtDate(d) {
        if(!d) return '—';
        const dt = (d instanceof Date) ? d : new Date(d);
        if(isNaN(dt.getTime())) return '—';

        const day = dt.getDate().toString().padStart(2, '0');
        const months = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
        const month = months[dt.getMonth()];
        const year = dt.getFullYear();

        let hours = dt.getHours();
        const minutes = dt.getMinutes().toString().padStart(2, '0');
        const seconds = dt.getSeconds().toString().padStart(2, '0');
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours.toString().padStart(2, '0') : '12';

        return `${day} ${month} ${year}, ${hours}:${minutes}:${seconds} ${ampm}`;
      },

      /**
       * Construye y descarga un archivo CSV con las filas de la auditoría.
       */
      exportCsv() {
        const rows = [['Tipo', 'Inicio', 'Fin', 'Duración', 'Detalle']].concat(
          this.events.map(e => [e.label, this.fmtDate(e.inicio), e.fin ? this.fmtDate(e.fin) : '', e.dur, e.detalle])
        );
        const csv = rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
        const blob = new Blob([csv], {type: 'text/csv;charset=utf-8;'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'centinela_eventos.csv';
        a.click();
        toast('CSV exportado');
      },

      /**
       * Abre el cuadro de diálogo de impresión para generar o guardar el reporte en PDF.
       */
      exportPdf() {
        toast('Preparando vista de impresión / PDF…');
        setTimeout(() => window.print(), 300);
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 7] CONFIGURACIÓN, GESTIÓN DE EQUIPOS Y MODAL REACTIVO
         ------------------------------------------------------------------------
         - Lista de UPS conectadas al servidor con su dirección IP y puerto.
         - Ventana modal reactiva para registrar nuevos equipos (soporta tecla ESC
           y cierre automático al hacer clic en el backdrop exterior).
         - Formulario de ajuste de umbrales eléctricos (Vmin, Vmax, Batería crítica).
         ------------------------------------------------------------------------ */
      devices: [{ id: 1, name: 'UPS-Servidores-01', loc: 'Sala de Servidores', ip: '192.168.1.50:7660', status: 'online' }],
      modalDeviceOpen: false,
      newDevice: { name: '', loc: '', ip: '', port: '7660' },
      systemUsers: [],
      modalUserOpen: false,
      userSaving: false,
      userEditForm: { id: null, role: '', username: '', password: '', password_confirm: '' },
      quickConfig: {
        name: 'UPS-Servidores-01',
        loc: 'Sala de servidores',
        ip: '192.168.1.50',
        port: '7660',
        vmin: '105',
        vmax: '130',
        batCrit: '20',
        interval: '2'
      },

      scrollToTop() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      },

      openDeviceDetailsConfig(d) {
        this.selectedDevice.id = d.id;
        this.selectedDevice.name = d.name;
        this.selectedDevice.loc = (d.loc || d.location || '') + (d.ip ? ` · ${d.ip}` : '');
        this.quickConfig.name = d.name;
        this.quickConfig.loc = d.loc || d.location || '';
        if(d.ip){
          const parts = d.ip.split(':');
          this.quickConfig.ip = parts[0] || '192.168.1.50';
          this.quickConfig.port = parts[1] || '7660';
        }
        this.loadDeviceConfig(d.id);
        this.setView('device-config');
        toast('Parámetros de ' + d.name);
      },

      openDeviceModal() {
        this.modalDeviceOpen = true;
      },

      closeDeviceModal() {
        this.modalDeviceOpen = false;
        this.newDevice = { name: '', loc: '', ip: '', port: '7660' };
      },

      async fetchUsers() {
        if(!this.user?.is_admin) return;
        try {
          const res = await fetch('/api/usuarios/');
          const data = await res.json();
          if(data.ok && Array.isArray(data.users)) {
            this.systemUsers = data.users;
          }
        } catch(e) {
          console.warn('Error obteniendo usuarios:', e);
        }
      },

      openUserModal(u) {
        this.userEditForm = {
          id: u.id,
          role: u.role || (u.is_admin ? 'Administrador' : 'Supervisor'),
          username: u.username,
          password: '',
          password_confirm: ''
        };
        this.modalUserOpen = true;
      },

      closeUserModal() {
        this.modalUserOpen = false;
        this.userEditForm = { id: null, role: '', username: '', password: '', password_confirm: '' };
      },

      async saveUserCredentials() {
        const username = this.userEditForm.username.trim();
        const pwd = this.userEditForm.password.trim();
        const pwdConf = this.userEditForm.password_confirm.trim();

        if(!username) {
          toast('El nombre de usuario es obligatorio');
          return;
        }

        if(pwd) {
          if(pwd.length < 4) {
            toast('La contraseña debe tener al menos 4 caracteres');
            return;
          }
          if(pwd !== pwdConf) {
            toast('Las contraseñas no coinciden');
            return;
          }
        }

        this.userSaving = true;
        try {
          const res = await fetch('/api/usuarios/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
              user_id: this.userEditForm.id,
              username: username,
              password: pwd
            })
          });
          const data = await res.json();
          if(data.ok) {
            toast(data.message || 'Credenciales actualizadas exitosamente');
            this.closeUserModal();
            await this.fetchUsers();
            if(this.user && (this.user.username === this.userEditForm.username || this.user.id === this.userEditForm.id)) {
              this.user.username = username;
            }
          } else {
            toast(data.error || 'Error al actualizar credenciales');
          }
        } catch(e) {
          console.error('Error guardando credenciales:', e);
          toast('Error de red al actualizar credenciales');
        } finally {
          this.userSaving = false;
        }
      },

      /**
       * Carga la configuración y umbrales eléctricos desde la API REST.
       */
      async loadDeviceConfig(id) {
        if(!id) return;
        try {
          const res = await fetch(`/api/dispositivos/${id}/`);
          const data = await res.json();
          if(data.ok && data.device) {
            const d = data.device;
            this.quickConfig.name = d.name;
            this.quickConfig.loc = d.location;
            this.quickConfig.ip = d.host;
            this.quickConfig.port = String(d.port || '7660');
            if(d.alert_config) {
              this.quickConfig.vmin = String(d.alert_config.voltage_min_alert || 100);
              this.quickConfig.vmax = String(d.alert_config.voltage_max_alert || 135);
              this.quickConfig.batCrit = String(d.alert_config.load_max_alert || 85);
            }
          }
        } catch(e) {
          console.warn('Error cargando configuración:', e);
        }
      },

      /**
       * Registra una nueva UPS en la base de datos vía POST /api/dispositivos/.
       */
      async saveNewDevice() {
        const name = this.newDevice.name.trim();
        const loc = this.newDevice.loc.trim();
        const ip = this.newDevice.ip.trim();
        const port = this.newDevice.port.trim() || '7660';

        if(!name) {
          toast('El nombre de la UPS es obligatorio');
          return;
        }
        if(!ip) {
          toast('La dirección IP es obligatoria');
          return;
        }

        try {
          const res = await fetch('/api/dispositivos/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
              name: name,
              location: loc,
              host: ip,
              port: port
            })
          });
          const data = await res.json();
          if(data.ok) {
            this.closeDeviceModal();
            await this.fetchFleet();
            toast(data.message || (name + ' agregada al inventario'));
          } else {
            toast(data.error || 'Error al guardar la UPS');
          }
        } catch(e) {
          toast('Error de red al registrar la UPS');
        }
      },

      /**
       * Guarda los cambios en el formulario de configuración vía PATCH /api/dispositivos/<id>/.
       */
      async saveQuickConfig() {
        if(!this.selectedDevice.id) {
          toast('No hay UPS seleccionada para modificar');
          return;
        }

        try {
          const res = await fetch(`/api/dispositivos/${this.selectedDevice.id}/`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
              name: this.quickConfig.name,
              location: this.quickConfig.loc,
              host: this.quickConfig.ip,
              port: this.quickConfig.port,
              vmin: parseFloat(this.quickConfig.vmin) || 100,
              vmax: parseFloat(this.quickConfig.vmax) || 135,
              load_max_alert: parseFloat(this.quickConfig.batCrit) || 85
            })
          });
          const data = await res.json();
          if(data.ok) {
            this.selectedDevice.name = data.device.name;
            this.selectedDevice.loc = `${data.device.location} · ${data.device.host}:${data.device.port}`;
            await this.fetchFleet();
            toast(data.message || 'Cambios guardados');
          } else {
            toast(data.error || 'Error al guardar cambios');
          }
        } catch(e) {
          toast('Error de red al actualizar configuración');
        }
      },

      resetQuickConfig() {
        if(this.selectedDevice.id) {
          this.loadDeviceConfig(this.selectedDevice.id);
        }
        toast('Edición cancelada');
      },

      /**
       * Elimina permanentemente una UPS registrada tras confirmación del usuario.
       */
      async deleteDevice(d) {
        if(!d || !d.id) {
          toast('No se especificó la UPS a eliminar');
          return;
        }
        const devName = d.name || 'esta UPS';
        const confirmDelete = window.confirm(`¿Estás seguro de que deseas eliminar permanentemente la UPS "${devName}"?\n\nEsta acción cancelará su monitoreo en segundo plano y desvinculará el equipo del sistema.`);
        if(!confirmDelete) return;

        try {
          const res = await fetch(`/api/dispositivos/${d.id}/`, {
            method: 'DELETE',
            headers: {
              'X-CSRFToken': getCsrfToken()
            }
          });
          const data = await res.json();
          if(data.ok) {
            toast(data.message || `UPS "${devName}" eliminada`);
            await this.fetchFleet();
            // Si el dispositivo eliminado era el seleccionado, cambiar selección o volver al panel
            if(this.selectedDevice && this.selectedDevice.id === d.id) {
              if(this.devices.length > 0) {
                this.selectDevice(this.devices[0]);
              } else {
                this.selectedDevice = { id: null, name: '', loc: '' };
                this.setView('panel');
              }
            }
          } else {
            toast(data.error || 'Error al eliminar la UPS');
          }
        } catch(e) {
          console.error('Error eliminando UPS:', e);
          toast('Error de red al intentar eliminar la UPS');
        }
      },


      /* ------------------------------------------------------------------------
         [SECCIÓN 8] CICLO DE VIDA (LIFECYCLE) Y SERVICIOS PERIÓDICOS
         ------------------------------------------------------------------------
         - init(): Constructor automático de Alpine que se ejecuta al montarse el DOM.
         - initAppServices(): Inicia los temporizadores de fondo (lecturas periódicas,
           ping de latencia del ESP32 y render inicial de Chart.js).
         ------------------------------------------------------------------------ */
      init() {
        // Exposición para depuración en consola del navegador
        window.__centinelaApp = this;
        window.__centinelaNav = this;

        if(this.theme) root.setAttribute('data-theme', this.theme);

        // Prellenar nombre de usuario recordado
        try {
          const rememberedUser = localStorage.getItem('centinela_remember_username');
          if (rememberedUser) {
            this.credentials.username = rememberedUser;
            this.credentials.remember = true;
          }
        } catch(e) {}

        this.events = seedEventsData();
        this.verifySession();
        this.fetchFleet();
      },

      /**
       * Consulta el catálogo real de UPS desde la API /api/flota/
       */
      async fetchFleet() {
        try {
          const res = await fetch('/api/flota/');
          const data = await res.json();
          if(data.ok && Array.isArray(data.devices) && data.devices.length > 0) {
            this.fleet = data.devices;
            this.devices = data.devices.map(d => ({
              id: d.id,
              name: d.name,
              loc: d.loc || d.location || '',
              host: d.host || (d.ip ? d.ip.split(':')[0] : '—'),
              port: String(d.port || (d.ip ? d.ip.split(':')[1] : '7660')),
              ip: `${d.host}:${d.port}`,
              status: d.status
            }));
            if(!this.selectedDevice.id) {
              const first = data.devices[0];
              this.selectedDevice.id = first.id;
              this.selectedDevice.name = first.name;
              this.selectedDevice.loc = `${first.loc} · ${first.host}:${first.port}`;
              this.loadDeviceConfig(first.id);
              this.fetchLiveTelemetry(first.id);
            }
          } else if(this.fleet.length === 0) {
            this.fleet = buildFleetData();
            this.devices = this.fleet.map(d => ({
              id: d.id,
              name: d.name,
              loc: d.loc,
              host: `192.168.1.${50 + d.id}`,
              port: '7660',
              ip: `192.168.1.${50 + d.id}:7660`,
              status: d.status
            }));
          }
        } catch(e) {
          if(this.fleet.length === 0) {
            this.fleet = buildFleetData();
            this.devices = this.fleet.map(d => ({
              id: d.id,
              name: d.name,
              loc: d.loc,
              host: `192.168.1.${50 + d.id}`,
              port: '7660',
              ip: `192.168.1.${50 + d.id}:7660`,
              status: d.status
            }));
          }
        }
      },

      /**
       * Consulta telemetría en tiempo real desde la API /api/dispositivos/<id>/telemetria/
       */
      async fetchLiveTelemetry(deviceId = null) {
        if(this.telemetry.onBattery && this._demoModeActive) return; // Respeta simulación demo si está activa
        try {
          const targetId = deviceId || this.selectedDevice.id;
          const url = targetId ? `/api/dispositivos/${targetId}/telemetria/` : '/api/telemetria/live/';
          const res = await fetch(url);
          const data = await res.json();
          if(data.ok && data.telemetry) {
            const t = data.telemetry;
            const isOffline = (t.status === 'offline') || (data.device && data.device.status === 'offline') || (this.activeDeviceStatus === 'offline');
            this.telemetry.status = (data.device ? data.device.status : t.status) || 'offline';

            if(isOffline) {
              this.telemetry.vin = 0.0;
              this.telemetry.vout = 0.0;
              this.telemetry.hz = 0.0;
              this.telemetry.load = 0;
              this.telemetry.battery = 0;
              this.telemetry.temp = 0.0;
              this.telemetry.onBattery = false;
              this.telemetry.status_q1 = '00000000';
              this.telemetry.q1_bits = {};
            } else {
              this.telemetry.vin = t.vin;
              this.telemetry.vout = t.vout;
              this.telemetry.hz = t.hz;
              this.telemetry.load = t.load;
              this.telemetry.battery = t.battery_pct !== null ? t.battery_pct : (t.battery_voltage || 100);
              this.telemetry.temp = t.temp;
              this.telemetry.onBattery = t.on_battery;
              this.telemetry.status_q1 = t.status_q1;
              this.telemetry.q1_bits = t.q1_bits;
            }

            if(t.status_changed_at) {
              this.telemetry.statusChangedAt = new Date(t.status_changed_at).getTime();
            } else if(t.status_duration_seconds !== undefined) {
              this.telemetry.statusChangedAt = Date.now() - (t.status_duration_seconds * 1000);
            }

            this.telemetry.lastRead = Date.now();
            if(data.device) {
              this.selectedDevice.name = data.device.name;
              this.selectedDevice.loc = `${data.device.location} · ${data.device.host}:${data.device.port}`;
              if(data.device.status_changed_at && !this.telemetry.statusChangedAt) {
                this.telemetry.statusChangedAt = new Date(data.device.status_changed_at).getTime();
              }
            }
          }
        } catch(e){}
      },

      /**
       * Arranca los servicios continuos del dashboard una vez autenticado.
       */
      initAppServices() {
        if(this._servicesStarted) return;
        this._servicesStarted = true;

        // Segundero en tiempo real para cronómetros reactivos (1s)
        setInterval(() => {
          this.currentTime = Date.now();
        }, 1000);

        // Renderizado inicial de las 4 gráficas de Chart.js
        if(typeof window.renderHistorico === 'function'){
          window.renderHistorico('1h');
        }

        // Bucle de telemetría en vivo cada 3s desde la API REST
        setInterval(() => {
          this.fetchLiveTelemetry();
        }, 3000);

        // Bucle de actualización en caliente de las gráficas de Histórico cada 3s
        setInterval(() => {
          if(this.currentView === 'historico' && typeof window.renderHistorico === 'function'){
            window.renderHistorico(this.currentRange, this.selectedDevice.id, true);
          }
        }, 3000);

        // Bucle de actualización en caliente de la tabla de Eventos cada 5s
        setInterval(() => {
          if(this.currentView === 'eventos'){
            this.fetchEvents();
          }
        }, 5000);

        // Bucle de actualización periódica de la flota cada 10s
        setInterval(() => {
          this.fetchFleet();
        }, 10000);

        // Bucle de latencia simulada del socket TCP cada 4s
        setInterval(() => {
          const ms = Math.round(rnd(24, 10));
          const el1 = document.getElementById('pingVal');
          const el2 = document.getElementById('pingVal2');
          if(el1) el1.textContent = 'Latencia: ' + ms + 'ms';
          if(el2) el2.textContent = 'Latencia: ' + ms + 'ms';
        }, 4000);
      }

    }));
  });

})();