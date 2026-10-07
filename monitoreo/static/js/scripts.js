(function(){
  "use strict";

  /* ==========================================================================
     CENTINELA · SISTEMA DE MONITOREO DE UPS INCARSA
     CONTROLADOR PRINCIPAL DEL FRONTEND (scripts.js)
     ==========================================================================
     Este archivo orquesta toda la interacción del usuario y la lógica de la
     interfaz en Vanilla JavaScript (sin frameworks pesados):
       1. Gestión de Temas (Modo Oscuro / Modo Claro)
       2. Manejo de CSRF y Control de Acceso por Roles (Admin vs Supervisor)
       3. Autenticación, Login con Django y Secuencia de Arranque (Bootloader)
       4. Enrutamiento y Navegación entre Pestañas (SPA - Single Page App)
       5. Sistema de Notificaciones Flotantes (Toasts)
       6. Telemetría Eléctrica, Protocolo Megatec (Q1) y Tacómetros
       7. Auditoría de Eventos de Red, Filtros y Exportación (CSV / PDF)
       8. Gestión y Registro de Dispositivos UPS (Formularios y Modales)
       9. Vista General de la Flota (Catálogo de 30 Equipos, Búsqueda y KPIs)
      10. Ciclo de Vida, Inicialización y Verificación de Sesión Activa
     ========================================================================== */


  /* ==========================================================================
     1. GESTIÓN DE TEMA (MODO CLARO / MODO OSCURO)
     ========================================================================== */

  // Referencia al elemento raíz <html> para inyectar el atributo data-theme="dark|light"
  const root = document.documentElement;

  /**
   * Aplica el tema visual al documento modificando el atributo CSS data-theme.
   * Además, cambia dinámicamente el ícono SVG de los botones (Sol <-> Luna).
   * 
   * @param {string|null} t - 'dark', 'light' o null (para usar la preferencia del sistema operativo).
   */
  function applyTheme(t){
    if(t){ 
      root.setAttribute('data-theme', t); 
    } else { 
      root.removeAttribute('data-theme'); 
    }
    
    // Determina si el modo efectivo resultante es oscuro
    const isDark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    // Actualiza los íconos de cambio de tema tanto en la barra superior como en el login
    document.querySelectorAll('#themeIcon, #loginThemeIcon').forEach(icon => {
      icon.innerHTML = isDark
        ? '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>' // Ícono de Luna
        : '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'; // Ícono de Sol
    });
  }

  // Intenta recuperar el tema guardado previamente por el usuario en localStorage
  let savedTheme = null;
  try { 
    savedTheme = localStorage.getItem('centinela-theme'); 
  } catch(e){}
  applyTheme(savedTheme);

  // Rango de tiempo seleccionado por defecto en la pestaña de gráficas históricas
  let currentRange = '1h';

  /**
   * Alterna entre modo claro y oscuro, guarda la elección en localStorage
   * y notifica al módulo de gráficas (graficas.js) para que recalcule los colores del canvas.
   */
  function toggleTheme(){
    const current = root.getAttribute('data-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    
    try { 
      localStorage.setItem('centinela-theme', next); 
    } catch(e){}
    
    // Si la función global expuesta por graficas.js existe, redibuja los gráficos con la nueva paleta
    if(typeof window.renderHistorico === 'function'){
      window.renderHistorico(currentRange);
    }
  }

  // Asigna el evento click a los botones de tema (en el panel principal y en la pantalla de login)
  document.getElementById('themeToggle').addEventListener('click', toggleTheme);
  document.getElementById('loginThemeFab').addEventListener('click', toggleTheme);


  /* ==========================================================================
     2. SEGURIDAD CSRF Y CONTROL DE ACCESO POR ROLES (ADMIN VS SUPERVISOR)
     ========================================================================== */

  /**
   * Obtiene el token CSRF (Cross-Site Request Forgery) requerido por Django para llamadas POST/PUT.
   * Busca primero en el input oculto generado por {% csrf_token %} y como alternativa en las cookies.
   * 
   * @returns {string} El token CSRF en texto plano.
   */
  function getCsrfToken(){
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    if(input) return input.value;
    const cookie = document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
  }

  // Objeto que almacena los datos de la sesión del usuario actual
  let currentUser = null;

  /**
   * Aplica el Control de Acceso Basado en Roles (RBAC) en la interfaz:
   * - Si es Administrador (is_admin: true):
   *     Tiene acceso total: pestaña de configuración, botón de agregar UPS y switch de simulación.
   * - Si es Supervisor (is_admin: false):
   *     Modo solo lectura: se ocultan todos los elementos marcados con la clase CSS '.admin-only'.
   * 
   * @param {Object} user - Objeto con {username, name, role, is_admin} retornado por el backend.
   */
  function applyUserPermissions(user){
    currentUser = user;
    const nameEl = document.getElementById('topUserName');
    const roleEl = document.getElementById('topUserRole');
    const iconEl = document.getElementById('topUserIcon');
    
    // Muestra el nombre y el rol en el chip de usuario de la barra superior
    if(nameEl) nameEl.textContent = user.name || user.username;
    if(roleEl) roleEl.textContent = user.role;
    if(iconEl) iconEl.textContent = user.is_admin ? '🛡️' : '👁️';

    // Filtra la visibilidad de elementos exclusivos para administradores
    document.querySelectorAll('.admin-only').forEach(el => {
      if(!user.is_admin){
        el.style.display = 'none'; // Ocultar para Supervisores
      } else {
        el.style.display = '';     // Restaurar visualización normal para Administradores
      }
    });

    // Seguridad de interfaz: si un supervisor estaba ubicado en la pestaña de configuración, regresarlo a la flota
    if(!user.is_admin){
      const activeNav = document.querySelector('.nav-link.active');
      if(activeNav && activeNav.dataset.view === 'config'){
        const flotaBtn = document.querySelector('.nav-link[data-view="flota"]');
        if(flotaBtn) flotaBtn.click();
      }
    }
  }


  /* ==========================================================================
     3. AUTENTICACIÓN, LOGIN CON DJANGO Y SECUENCIA DE ARRANQUE (BOOTLOADER)
     ========================================================================== */

  const loginForm = document.getElementById('loginForm');
  const loginError = document.getElementById('loginError');
  const loginErrorText = document.getElementById('loginErrorText');

  /**
   * Manejador del evento Submit del formulario de Login:
   * 1. Captura usuario y contraseña.
   * 2. Realiza petición asíncrona (fetch POST) a la API de Django en '/api/login/'.
   * 3. Si las credenciales son válidas, guarda la sesión y arranca el preloader animado.
   * 4. Si fallan, muestra el mensaje de error con una micro-animación de sacudida (shake).
   */
  loginForm.addEventListener('submit', async function(e){
    e.preventDefault();
    const u = document.getElementById('loginUser').value.trim();
    const p = document.getElementById('loginPass').value.trim();

    // Validación preventiva en cliente para campos vacíos
    if(!u || !p){
      if(loginErrorText) loginErrorText.textContent = 'Ingresa tu usuario y contraseña.';
      loginError.classList.remove('show'); 
      void loginError.offsetWidth; // Forzar reflujo del navegador para reiniciar la animación CSS
      loginError.classList.add('show');
      return;
    }

    const btn = document.getElementById('loginBtn');
    document.getElementById('loginSpinner').classList.add('on');
    document.getElementById('loginBtnText').textContent = 'Verificando…';
    btn.disabled = true;

    try {
      // Envío seguro de credenciales con protección CSRF al backend Django
      const res = await fetch('/api/login/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ username: u, password: p })
      });
      const data = await res.json();

      if(data.ok && data.user){
        // Autenticación exitosa: configuramos permisos e iniciamos animación de transición
        applyUserPermissions(data.user);
        document.getElementById('login-screen').style.animation = 'fade-out .35s ease forwards';
        setTimeout(startBoot, 320);
      } else {
        // Credenciales inválidas o cuenta inactiva
        if(loginErrorText) loginErrorText.textContent = data.error || 'Credenciales incorrectas.';
        loginError.classList.remove('show'); 
        void loginError.offsetWidth; 
        loginError.classList.add('show');
        document.getElementById('loginSpinner').classList.remove('on');
        document.getElementById('loginBtnText').textContent = 'Ingresar';
        btn.disabled = false;
      }
    } catch(err){
      // Problema de red o servidor no disponible
      if(loginErrorText) loginErrorText.textContent = 'Error de conexión con el servidor.';
      loginError.classList.remove('show'); 
      void loginError.offsetWidth; 
      loginError.classList.add('show');
      document.getElementById('loginSpinner').classList.remove('on');
      document.getElementById('loginBtnText').textContent = 'Ingresar';
      btn.disabled = false;
    }
  });

  // Mensajes secuenciales que simulan la conexión por socket y preparación de telemetría
  const bootSteps = [
    'Estableciendo sesión…',
    'Abriendo socket TCP → 192.168.1.50:4196…',
    'Sincronizando protocolo Megatec…',
    'Cargando lecturas históricas…',
    'Listo.'
  ];

  /**
   * Ejecuta la animación circular del preloader antes de dar paso al panel principal.
   * Utiliza la fórmula del perímetro del círculo (2 * PI * r) para animar el trazo SVG.
   */
  function startBoot(){
    document.getElementById('login-screen').classList.add('hidden');
    const pre = document.getElementById('preloader');
    pre.classList.remove('hidden');
    const bar = document.getElementById('bootBar');
    const pct = document.getElementById('bootPct');
    const log = document.getElementById('bootLog');
    const circumference = 2 * Math.PI * 35; // Perímetro con radio = 35px
    bar.style.strokeDasharray = circumference;
    
    let step = 0;
    function next(){
      step++;
      const p = Math.min(100, Math.round((step / bootSteps.length) * 100));
      bar.style.strokeDashoffset = circumference - (circumference * p / 100);
      pct.textContent = p + '%';
      log.innerHTML = bootSteps[Math.min(step, bootSteps.length) - 1] || '';
      
      if(step < bootSteps.length){ 
        setTimeout(next, 420); // Avanzar al siguiente paso del preloader
      } else { 
        setTimeout(() => {
          pre.style.animation = 'fade-out .3s ease forwards';
          setTimeout(() => { 
            pre.classList.add('hidden'); 
            document.getElementById('app').classList.remove('hidden'); 
            initApp(); // Inicializa todos los componentes y servicios del panel
          }, 280);
        }, 380); 
      }
    }
    setTimeout(next, 250);
  }

  // Inyección de regla CSS dinámica para suavizar las transiciones de salida
  const styleFade = document.createElement('style');
  styleFade.textContent = '@keyframes fade-out{ to{ opacity:0; transform:scale(.98); } }';
  document.head.appendChild(styleFade);


  /* ==========================================================================
     4. ENRUTAMIENTO Y NAVEGACIÓN ENTRE PESTAÑAS (SPA)
     ========================================================================== */

  /**
   * Configura la navegación de tipo SPA (Single Page Application):
   * Permite alternar entre las vistas (Flota, Monitor, Histórico, Eventos, Configuración)
   * sin necesidad de recargar la página en el navegador.
   */
  function initNav(){
    document.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', () => {
        // Marca visualmente el botón activo de la barra de navegación
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        
        // Oculta todas las vistas y muestra únicamente la seleccionada
        document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
        document.getElementById('view-' + link.dataset.view).classList.remove('hidden');
        document.getElementById('navLinks').classList.remove('open');
        
        // Al acceder a la pestaña de Histórico, redibujar las gráficas de Chart.js con el tamaño adecuado
        if(link.dataset.view === 'historico' && typeof window.renderHistorico === 'function'){
          setTimeout(() => window.renderHistorico(currentRange), 50);
        }
      });
    });

    // Menú hamburguesa responsivo para dispositivos móviles y tablets
    document.getElementById('menuToggle').addEventListener('click', () => {
      document.getElementById('navLinks').classList.toggle('open');
    });

    // Botón de Cerrar Sesión: invalida la sesión en Django mediante POST y reinicia la vista
    document.getElementById('logoutBtn').addEventListener('click', async () => {
      try {
        await fetch('/api/logout/', {
          method: 'POST',
          headers: {'X-CSRFToken': getCsrfToken()}
        });
      } catch(e){}
      location.reload();
    });
  }


  /* ==========================================================================
     5. SISTEMA DE NOTIFICACIONES FLOTANTES (TOASTS)
     ========================================================================== */

  /**
   * Despliega una notificación flotante temporal en la esquina de la pantalla.
   * 
   * @param {string} msg - Texto informativo o de alerta que se mostrará al usuario.
   * @param {boolean} [warn=false] - true para alerta crítica (estilo rojo), false para informativo (verde).
   */
  function toast(msg, warn){
    const host = document.getElementById('toast-host');
    const el = document.createElement('div');
    el.className = 'toast' + (warn ? ' warn' : '');
    el.innerHTML = (warn
      ? '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2.4"><circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16h.01"/></svg>'
      : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.4"><path d="M20 6 9 17l-5-5"/></svg>'
    ) + '<span>' + msg + '</span>';
    host.appendChild(el);
    
    // Desaparece y se elimina del árbol DOM tras 3.2 segundos
    setTimeout(() => { 
      el.style.animation = 'toast-in .25s ease reverse forwards'; 
      setTimeout(() => el.remove(), 260); 
    }, 3200);
  }


  /* ==========================================================================
     6. TELEMETRÍA ELÉCTRICA, PROTOCOLO MEGATEC (Q1) Y TACÓMETROS
     ========================================================================== */

  // Estructura de datos con el estado en tiempo real de la UPS bajo monitoreo activo
  let state = {
    vin: 120.4,          // Voltaje de entrada de la red (V)
    vout: 120.1,         // Voltaje entregado a la carga (V)
    hz: 60.0,            // Frecuencia eléctrica (Hz)
    load: 45,            // Porcentaje de capacidad utilizada (%)
    battery: 100,        // Nivel de carga de la batería (%)
    temp: 28.4,          // Temperatura del transformador/inversor (°C)
    onBattery: false,    // true: operando desde inversor / false: operando desde red
    connectedSince: Date.now() - 8048000, // Marca de tiempo del inicio del enlace
    lastRead: Date.now(),
    events: []
  };

  /**
   * Definición oficial de los 8 bits del byte de estado del comando Q1 (Protocolo Megatec UPS):
   *   Bit a: Utility Fail (Falla de red eléctrica)
   *   Bit b: Battery Low (Batería en nivel crítico)
   *   Bit c: Bypass / Boost Active (AVR elevando o reduciendo voltaje)
   *   Bit d: UPS Failed (Falla de hardware interno)
   *   Bit e: UPS Type (0: On-line, 1: Standby)
   *   Bit f: Test in Progress (Auto-diagnóstico de batería corriendo)
   *   Bit g: Shutdown Active (Comando de apagado programado activo)
   *   Bit h: Beeper On (Alarma acústica sonando)
   */
  const bitLabels = [
    {name: 'Falla de red eléctrica', key: 'a'},
    {name: 'Batería baja', key: 'b'},
    {name: 'Bypass / boost activo', key: 'c'},
    {name: 'Falla de UPS', key: 'd'},
    {name: 'Tipo standby', key: 'e'},
    {name: 'Prueba en progreso', key: 'f'},
    {name: 'Apagado programado', key: 'g'},
    {name: 'Beeper encendido', key: 'h'}
  ];

  /**
   * Genera un valor numérico pseudo-aleatorio con variación controlada (para simular ruido de sensor).
   * @param {number} base - Valor central promedio.
   * @param {number} spread - Rango máximo de oscilación.
   * @returns {number}
   */
  function rnd(base, spread){ return base + (Math.random() - 0.5) * spread; }

  /**
   * Limita un valor numérico dentro de un rango mínimo y máximo (evita desbordamientos).
   * @param {number} v - Valor de entrada.
   * @param {number} min - Límite inferior.
   * @param {number} max - Límite superior.
   * @returns {number}
   */
  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }

  /**
   * Dibuja los 8 indicadores LED correspondientes a los bits Megatec en la sección de diagnóstico.
   * Enciende el LED rojo o ámbar si el bit de alarma respectivo se encuentra activo.
   */
  function renderBitmask(){
    const row = document.getElementById('bitmaskRow');
    if(!row) return;
    const active = {};
    if(state.onBattery){ active.a = true; }
    if(state.battery < 20){ active.b = true; }
    if(state.battery < 10){ active.d = true; active.h = true; }
    
    row.innerHTML = bitLabels.map(b => {
      const on = !!active[b.key];
      const warn = b.key === 'b';
      return '<div class="bit-chip' + (on ? ' on' : '') + (on && warn ? ' warn' : '') + '"><span class="led"></span><span class="name">' + b.name + '</span></div>';
    }).join('');
  }

  /**
   * Calcula el offset del trazo SVG circular según el porcentaje (0 a 100%).
   * @param {number} pct - Porcentaje a representar.
   * @param {number} r - Radio del círculo SVG.
   * @returns {number} Desplazamiento en píxeles para stroke-dashoffset.
   */
  function ringOffset(pct, r){ 
    const c = 2 * Math.PI * r; 
    return c - (c * pct / 100); 
  }

  /**
   * Actualiza todos los elementos gráficos de telemetría en la pestaña Monitor:
   * - Tacómetros numéricos (Voltaje entrada/salida, Frecuencia, Temperatura).
   * - Barra de porcentaje de carga eléctrica con colores por umbral (normal, advertencia, crítico).
   * - Medidor circular de batería con estimación de autonomía restante en minutos.
   * - Insignias y barra de identidad (cambia a color rojo de alarma si está en batería).
   * - Contador de tiempo de enlace activo (Uptime).
   */
  function renderGauges(){
    document.getElementById('gVin').textContent = state.vin.toFixed(1);
    document.getElementById('gVout').textContent = state.vout.toFixed(1);
    document.getElementById('gHz').textContent = state.hz.toFixed(1);
    document.getElementById('gTemp').textContent = state.temp.toFixed(1);
    document.getElementById('gCarga').textContent = Math.round(state.load);
    
    // Barra de carga porcentual
    document.getElementById('gCargaBar').style.width = state.load + '%';
    document.getElementById('gCargaBar').style.background = state.load > 85 ? 'var(--red)' : (state.load > 65 ? 'var(--amber)' : 'var(--red)');
    
    // Medidor circular de batería restante
    document.getElementById('gBateria').textContent = Math.round(state.battery);
    const ring = document.getElementById('ringBateria');
    ring.setAttribute('stroke-dashoffset', ringOffset(state.battery, 16));
    ring.style.stroke = state.battery < 20 ? 'var(--red)' : 'var(--green)';
    document.getElementById('gBateriaSub').textContent = state.onBattery
      ? 'Descargando · autonomía ~' + Math.max(1, Math.round(state.battery * 0.42)) + ' min'
      : 'En carga · autonomía estimada 34 min';

    // Barra de estado de identidad superior
    const bar = document.getElementById('identityBar');
    const badge = document.getElementById('identityBadge');
    const text = document.getElementById('identityText');
    const dot = document.getElementById('identityDot');
    const topDot = document.getElementById('topDot');
    const topText = document.getElementById('topStatusText');
    const topChip = document.getElementById('topStatusChip');
    
    if(state.onBattery){
      // Estado de corte eléctrico / batería
      bar.classList.add('alarm'); 
      badge.classList.remove('online'); 
      badge.classList.add('battery');
      text.textContent = 'Funcionando en batería'; 
      dot.classList.add('red'); 
      topDot.classList.add('red');
      topText.textContent = 'En batería';
      topChip.classList.remove('online'); 
      topChip.classList.add('battery');
    } else {
      // Estado de suministro normal
      bar.classList.remove('alarm'); 
      badge.classList.add('online'); 
      badge.classList.remove('battery');
      text.textContent = 'Red eléctrica'; 
      dot.classList.remove('red'); 
      topDot.classList.remove('red');
      topText.textContent = 'En línea';
      topChip.classList.remove('battery'); 
      topChip.classList.add('online');
    }
    
    // Cálculo y formateo del tiempo de conexión activa (HH:MM:SS)
    const secs = Math.floor((Date.now() - state.connectedSince) / 1000);
    const hh = String(Math.floor(secs / 3600)).padStart(2, '0');
    const mm = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
    const ss = String(secs % 60).padStart(2, '0');
    document.getElementById('upTime').textContent = hh + ':' + mm + ':' + ss;
    document.getElementById('lastRead').textContent = 'hace 1s';
    
    // Actualizar los LEDs Megatec
    renderBitmask();
  }

  // Marca temporal de cuando comenzó el corte eléctrico simulado
  let outageStartedAt = null;

  /**
   * Bucle periódico de telemetría (se ejecuta cada 2 segundos):
   * Simula la llegada de lecturas eléctricas fluctuantes:
   * - En modo normal: el voltaje oscila alrededor de 120V y la batería se recarga.
   * - En modo batería: el voltaje de entrada cae a 0V, el inversor sostiene la salida y la batería se descarga.
   */
  function tick(){
    if(state.onBattery){
      state.vin = rnd(3, 4);                             // Entrada cae a ~0V
      state.vout = clamp(rnd(119.5, 1.2), 100, 130);      // Salida estable gracias al inversor
      state.battery = clamp(state.battery - 0.9, 0, 100);    // Descarga gradual
      state.load = clamp(rnd(48, 6), 10, 100);
    } else {
      state.vin = clamp(rnd(120, 3), 100, 135);
      state.vout = clamp(state.vin + rnd(0, 0.6), 100, 135);
      state.battery = clamp(state.battery + 1.4, 0, 100);    // Recarga gradual
      state.load = clamp(rnd(45, 8), 10, 95);
    }
    state.hz = clamp(rnd(60, 0.15), 58, 62);
    state.temp = clamp(rnd(28, 0.6), 18, 45);
    state.lastRead = Date.now();
    renderGauges();
  }

  /**
   * Interruptor de Modo Demostración (Simular Corte de Luz):
   * Permite a los administradores probar las alertas visuales y la auditoría de eventos.
   */
  document.getElementById('simOutage').addEventListener('change', function(e){
    state.onBattery = e.target.checked;
    if(state.onBattery){
      outageStartedAt = new Date();
      toast('UPS-Servidores-01 entró en modo batería', true);
    } else {
      if(outageStartedAt){
        const end = new Date();
        const durSec = Math.round((end - outageStartedAt) / 1000);
        // Inserta el nuevo evento en la primera posición del historial
        state.events.unshift({
          tipo: 'battery', 
          label: 'Modo batería',
          inicio: outageStartedAt, 
          fin: end, 
          dur: durSec + 's',
          detalle: 'Corte de red simulado desde el panel'
        });
        renderEvents();
      }
      toast('Red eléctrica restablecida');
    }
  });


  /* ==========================================================================
     7. AUDITORÍA DE EVENTOS DE ENERGÍA, FILTROS Y EXPORTACIÓN (CSV / PDF)
     ========================================================================== */

  /**
   * Genera el conjunto inicial de eventos históricos de prueba
   * (cortes de energía, caídas de enlace TCP, picos de sobretensión).
   */
  function seedEvents(){
    const now = Date.now();
    state.events = [
      {tipo: 'battery', label: 'Modo batería', inicio: new Date(now - 3600e3 * 5), fin: new Date(now - 3600e3 * 5 + 228e3), dur: '3m 48s', detalle: 'Corte de red detectado — recuperado automáticamente'},
      {tipo: 'comm', label: 'Desconexión TCP', inicio: new Date(now - 3600e3 * 20), fin: new Date(now - 3600e3 * 20 + 9e3), dur: '9s', detalle: 'Pérdida momentánea de enlace con el ESP32'},
      {tipo: 'info', label: 'Sobretensión detectada', inicio: new Date(now - 3600e3 * 30), fin: new Date(now - 3600e3 * 30 + 2e3), dur: '2s', detalle: 'Pico de 134V en entrada'},
      {tipo: 'battery', label: 'Modo batería', inicio: new Date(now - 3600e3 * 48), fin: new Date(now - 3600e3 * 48 + 612e3), dur: '10m 12s', detalle: 'Corte de red prolongado'},
      {tipo: 'comm', label: 'Reconexión establecida', inicio: new Date(now - 3600e3 * 72), fin: new Date(now - 3600e3 * 72), dur: '—', detalle: 'Enlace restablecido tras reinicio del ESP32'}
    ];
  }

  /**
   * Formatea un objeto Date en cadena legible con formato local de Colombia (DD/MM HH:MM:SS).
   * @param {Date} d - Objeto fecha.
   * @returns {string} Fecha formateada.
   */
  function fmtDate(d){ 
    return d.toLocaleDateString('es-CO', {day: '2-digit', month: '2-digit'}) + ' ' + 
           d.toLocaleTimeString('es-CO', {hour: '2-digit', minute: '2-digit', second: '2-digit'}); 
  }

  // Filtro de auditoría seleccionado ('todos', 'battery', 'comm', 'info')
  let currentFilter = 'todos';

  /**
   * Dibuja las filas de la tabla de eventos aplicando el filtro activo.
   * Si no hay eventos para el filtro, muestra una fila con mensaje explicativo.
   */
  function renderEvents(){
    const body = document.getElementById('eventsBody');
    if(!body) return;
    const list = state.events.filter(e => currentFilter === 'todos' || e.tipo === currentFilter);
    document.getElementById('eventCount').textContent = list.length + ' eventos';
    
    body.innerHTML = list.map(e => {
      const tagClass = e.tipo;
      return '<tr><td><span class="tag ' + tagClass + '">' + e.label + '</span></td>' +
        '<td class="mono">' + fmtDate(e.inicio) + '</td>' +
        '<td class="mono">' + (e.fin ? fmtDate(e.fin) : '—') + '</td>' +
        '<td class="mono">' + e.dur + '</td>' +
        '<td style="white-space:normal; color:var(--text-dim);">' + e.detalle + '</td></tr>';
    }).join('') || '<tr><td colspan="5" style="text-align:center; color:var(--text-faint); padding:26px;">Sin eventos para este filtro.</td></tr>';
  }

  /**
   * Manejador de clics en los botones de filtro de eventos (Todos, Modo batería, Comunicación, Sobretensión).
   */
  document.getElementById('filterSeg').addEventListener('click', function(e){
    const btn = e.target.closest('button'); 
    if(!btn) return;
    this.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.dataset.filter;
    renderEvents();
  });

  /**
   * Exporta la lista de eventos activa a un archivo delimitado por comas (.CSV).
   * Crea un Blob en memoria y genera una descarga automática en el navegador.
   */
  document.getElementById('exportCsv').addEventListener('click', function(){
    const rows = [['Tipo', 'Inicio', 'Fin', 'Duración', 'Detalle']].concat(
      state.events.map(e => [e.label, fmtDate(e.inicio), e.fin ? fmtDate(e.fin) : '', e.dur, e.detalle])
    );
    const csv = rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob([csv], {type: 'text/csv;charset=utf-8;'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); 
    a.download = 'centinela_eventos.csv'; 
    a.click();
    toast('CSV exportado');
  });

  /**
   * Prepara la vista e invoca el diálogo de impresión nativo del navegador (Guardar como PDF).
   */
  document.getElementById('exportPdf').addEventListener('click', function(){
    toast('Preparando vista de impresión / PDF…');
    setTimeout(() => window.print(), 300);
  });


  /* ==========================================================================
     8. GESTIÓN Y REGISTRO DE DISPOSITIVOS UPS (CONFIGURACIÓN)
     ========================================================================== */

  /**
   * Formulario de configuración rápida de la UPS seleccionada:
   * Modifica el nombre, ubicación e IP mostrados en el encabezado del panel.
   */
  document.getElementById('configForm').addEventListener('submit', function(e){
    e.preventDefault();
    document.getElementById('upsName').textContent = document.getElementById('cfgName').value;
    document.getElementById('upsLoc').textContent = document.getElementById('cfgLoc').value + ' · ' + document.getElementById('cfgIp').value + ':' + document.getElementById('cfgPort').value;
    toast('Cambios guardados');
  });

  // Lista local de dispositivos registrados en la pestaña de Configuración
  let devices = [{name: 'UPS-Servidores-01', ip: '192.168.1.50:4196'}];

  /**
   * Dibuja la lista de equipos en la tabla de configuración.
   */
  function renderDevices(){
    const el = document.getElementById('deviceList');
    if(!el) return;
    el.innerHTML = devices.map(d =>
      '<div class="device-row"><div class="di"><span class="dot pulse"></span><b>' + d.name + '</b></div><span class="ip mono">' + d.ip + '</span></div>'
    ).join('');
  }

  // Controladores para abrir y cerrar el modal emergente de "Agregar nueva UPS"
  document.getElementById('addDeviceBtn').addEventListener('click', () => document.getElementById('modalBackdrop').classList.remove('hidden'));
  document.getElementById('modalCancel').addEventListener('click', () => document.getElementById('modalBackdrop').classList.add('hidden'));
  
  /**
   * Guarda un nuevo dispositivo en el inventario desde el modal emergente.
   */
  document.getElementById('modalSave').addEventListener('click', () => {
    const name = document.getElementById('newDevName').value.trim() || 'Nueva UPS';
    const ip = document.getElementById('newDevIp').value.trim() || '0.0.0.0';
    const port = document.getElementById('newDevPort').value.trim() || '4196';
    devices.push({name, ip: ip + ':' + port});
    renderDevices();
    document.getElementById('modalBackdrop').classList.add('hidden');
    toast(name + ' agregada al inventario');
  });


  /* ==========================================================================
     9. VISTA GENERAL DE LA FLOTA (CATÁLOGO DE 30 EQUIPOS, BÚSQUEDA Y KPIS)
     ========================================================================== */

  // Catálogo de sedes y ubicaciones representativas en Colombia
  const fleetLocs = [
    ['Sala de Servidores', 'Bogotá'], ['Oficina Cali', 'Cali'], ['Datacenter Sur', 'Bogotá'], ['Bodega Norte', 'Medellín'],
    ['Piso 3 · Administración', 'Bogotá'], ['Planta Eléctrica', 'Barranquilla'], ['Torre B · Rack 2', 'Bogotá'],
    ['Sucursal Medellín', 'Medellín'], ['Almacén Central', 'Cali'], ['Recepción Principal', 'Bogotá'],
    ['Centro de Datos', 'Bucaramanga'], ['Rack Telecom', 'Pereira']
  ];

  // Colección de equipos de la flota
  let fleet = [];

  /**
   * Construye el catálogo de 30 equipos con estados heterogéneos:
   * - Equipos en línea (suministro normal).
   * - Equipos en batería (simulando fallas eléctricas zonales).
   * - Equipos desconectados (sin enlace de red con su ESP32).
   */
  function buildFleet(){
    const batteryIdx = [3, 11, 19]; 
    const offlineIdx = [8, 24];
    fleet = [];
    for(let i = 0; i < 30; i++){
      const loc = fleetLocs[i % fleetLocs.length];
      let status = 'online';
      if(batteryIdx.includes(i)) status = 'battery';
      if(offlineIdx.includes(i)) status = 'offline';
      const battery = status === 'offline' ? null : Math.round(clamp(rnd(status === 'battery' ? 55 : 90, status === 'battery' ? 40 : 16), 4, 100));
      const load = status === 'offline' ? null : Math.round(clamp(rnd(46, 22), 5, 98));
      fleet.push({
        id: i + 1, 
        name: 'UPS-' + String(i + 1).padStart(2, '0'),
        loc: loc[0] + ' · ' + loc[1], 
        status, 
        battery, 
        load,
        alert: status === 'offline' || (battery !== null && battery < 20)
      });
    }
  }

  /**
   * Renderiza las 4 tarjetas superiores de KPIs de la Flota:
   * 1. Total de UPS registradas.
   * 2. Equipos operando actualmente en modo batería.
   * 3. Alertas activas críticas (batería < 20% o sin enlace).
   * 4. Equipos con suministro de red normal.
   */
  function renderKpis(){
    const total = fleet.length;
    const enBateria = fleet.filter(f => f.status === 'battery').length;
    const alertas = fleet.filter(f => f.alert).length;
    const desconectadas = fleet.filter(f => f.status === 'offline').length;
    
    document.getElementById('kpiRow').innerHTML = [
      ['blue', '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>', total, 'UPS registradas'],
      ['red', '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/>', enBateria, 'En batería ahora'],
      ['amber', '<circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16h.01"/>', alertas, 'Alertas activas'],
      ['green', '<path d="M20 6 9 17l-5-5"/>', total - desconectadas - enBateria, 'En línea normal']
    ].map(k =>
      '<div class="kpi-card"><div class="kpi-icon ' + k[0] + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' + k[1] + '</svg></div>' +
      '<div><div class="kpi-num mono">' + k[2] + '</div><div class="kpi-label">' + k[3] + '</div></div></div>'
    ).join('');
  }

  // Filtro de visualización de la flota ('todas', 'battery', 'alert', 'offline')
  let fleetFilter = 'todas';

  /**
   * Dibuja la cuadrícula de tarjetas de UPS:
   * - Filtra según el texto escrito en el buscador y el botón de filtro seleccionado.
   * - Muestra barras de carga y nivel de batería para equipos conectados.
   * - Asigna evento click a cada tarjeta para navegar al detalle individual en la pestaña Monitor.
   */
  function renderFleet(){
    const q = (document.getElementById('fleetSearch').value || '').toLowerCase();
    const list = fleet.filter(f => {
      if(q && !(f.name.toLowerCase().includes(q) || f.loc.toLowerCase().includes(q))) return false;
      if(fleetFilter === 'battery') return f.status === 'battery';
      if(fleetFilter === 'alert') return f.alert;
      if(fleetFilter === 'offline') return f.status === 'offline';
      return true;
    });

    const grid = document.getElementById('fleetGrid');
    if(!grid) return;
    if(!list.length){ 
      grid.innerHTML = '<div class="fleet-empty">No hay UPS que coincidan con el filtro.</div>'; 
      return; 
    }
    
    const statusLabel = {online: 'Red eléctrica', battery: 'En batería', offline: 'Sin comunicación'};
    
    grid.innerHTML = list.map(f => {
      const dotCls = f.status === 'online' ? '' : (f.status === 'battery' ? 'red pulse' : '');
      const body = f.status === 'offline'
        ? '<div class="fc-offline-msg"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16h.01"/></svg> Sin comunicación con el ESP32</div>'
        : '<div class="fc-stat"><span>Carga</span><b class="mono">' + f.load + '%</b></div>' +
          '<div class="g-bar"><div class="g-bar-fill" style="width:' + f.load + '%; background:' + (f.status === 'battery' ? 'var(--red)' : 'var(--purple)') + '"></div></div>' +
          '<div class="fc-stat"><span>Batería</span><b class="mono">' + f.battery + '%</b></div>' +
          '<div class="g-bar"><div class="g-bar-fill" style="width:' + f.battery + '%; background:' + (f.battery < 20 ? 'var(--red)' : 'var(--green)') + '"></div></div>';
      
      return '<div class="fleet-card ' + f.status + '" data-id="' + f.id + '">' +
        '<div class="fc-top"><span class="fc-name">' + f.name + '</span><span class="dot ' + (f.status === 'online' ? 'pulse' : '') + ' ' + dotCls + '" style="background:' + (f.status === 'online' ? 'var(--green)' : (f.status === 'battery' ? 'var(--red)' : 'var(--amber)')) + '"></span></div>' +
        '<div class="fc-loc">' + f.loc + '</div>' +
        '<span class="fc-badge ' + f.status + '">' + statusLabel[f.status] + '</span>' +
        body +
        '</div>';
    }).join('');

    // Permite que al tocar una tarjeta se abra inmediatamente el monitor individual de esa UPS
    grid.querySelectorAll('.fleet-card').forEach(card => {
      card.addEventListener('click', () => {
        const f = fleet.find(x => x.id == card.dataset.id);
        toast('Abriendo detalle de ' + f.name + '…');
        document.querySelector('.nav-link[data-view="monitor"]').click();
      });
    });
  }

  // Escuchador de entrada de texto en el buscador de la flota
  document.getElementById('fleetSearch').addEventListener('input', renderFleet);
  
  // Segmentos de filtro de flota (Todas, En batería, Alertas, Desconectadas)
  document.getElementById('fleetFilterSeg').addEventListener('click', function(e){
    const btn = e.target.closest('button'); 
    if(!btn) return;
    this.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    fleetFilter = btn.dataset.ffilter;
    renderFleet();
  });

  // Temporizador para simular fluctuaciones en la latencia TCP del ESP32
  let pingInterval;
  function simulatePing(){
    const el = document.getElementById('pingVal');
    if(el) el.textContent = 'Latencia: ' + Math.round(rnd(24, 10)) + 'ms';
  }


  /* ==========================================================================
     10. CICLO DE VIDA, INICIALIZACIÓN Y VERIFICACIÓN DE SESIÓN ACTIVA
     ========================================================================== */

  /**
   * Función Maestra de Inicialización (Bootstrapper):
   * Arranca la navegación, genera los datos iniciales, dibuja las tarjetas,
   * tacómetros y comienza los temporizadores periódicos (tick cada 2s, ping cada 4s).
   */
  function initApp(){
    initNav();
    seedEvents();
    renderEvents();
    renderDevices();
    buildFleet();
    renderKpis();
    renderFleet();
    renderGauges();
    
    // Si graficas.js ya cargó, dibuja las 4 gráficas iniciales de Chart.js
    if(typeof window.renderHistorico === 'function'){
      window.renderHistorico('1h');
    }
    
    // Inicia el bucle de actualización en vivo
    tick();
    setInterval(tick, 2000);
    pingInterval = setInterval(simulatePing, 4000);
  }

  /**
   * Verificación Automática de Sesión al Cargar la Página (Auto-Login):
   * Pregunta a Django en '/api/me/' si ya existe una cookie de sesión activa.
   * Si es así, omite el login y entra de inmediato al panel con los permisos correspondientes.
   */
  (async function verifySession(){
    try {
      const res = await fetch('/api/me/');
      const data = await res.json();
      if(data.authenticated && data.user){
        applyUserPermissions(data.user);
        document.getElementById('login-screen').classList.add('hidden');
        document.getElementById('app').classList.remove('hidden');
        initApp();
      }
    } catch(e){}
  })();

  // Observador de redimensionamiento de ventana
  window.addEventListener('resize', () => {});
})();