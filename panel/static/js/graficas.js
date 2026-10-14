(function(window){
  "use strict";

  /* ============================================================
     CENTINELA · MÓDULO DE GRÁFICAS (Chart.js)
     ============================================================ */

  const root = document.documentElement;
  const chartInstances = {};
  let currentRange = '1h';

  function getThemeColors(){
    const isDark = root.getAttribute('data-theme') === 'dark' ||
      (!root.getAttribute('data-theme') && window.matchMedia('(prefers-color-scheme: dark)').matches);
    return {
      textColor: isDark ? '#9A9CA3' : '#64656B',
      gridColor: isDark ? 'rgba(255, 255, 255, 0.07)' : 'rgba(0, 0, 0, 0.07)',
      tooltipBg: isDark ? '#1D1F22' : '#FFFFFF',
      tooltipText: isDark ? '#ECECEE' : '#16171A',
      tooltipBorder: isDark ? '#2B2D31' : '#D8D9DC',
      red: isDark ? '#E1483F' : '#C93B34',
      blue: isDark ? '#5B9DFF' : '#2563EB',
      purple: isDark ? '#B98CE0' : '#7C3AED',
      amber: isDark ? '#D9A441' : '#A8721B',
      green: isDark ? '#4FAE7C' : '#2E8B5C'
    };
  }

  function seededRandom(seed){
    let s = seed % 2147483647; if(s<=0) s += 2147483646;
    return function(){ s = s*16807 % 2147483647; return (s-1)/2147483646; };
  }

  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }

  function genSeries(seed, n, base, spread, driftMax){
    const rand = seededRandom(seed);
    const arr = []; let v = base; let drift = 0;
    for(let i=0; i<n; i++){
      drift += (rand()-0.5)*driftMax;
      drift = clamp(drift, -spread, spread);
      v = base + drift + (rand()-0.5)*spread*0.3;
      arr.push(v);
    }
    return arr;
  }

  function renderStats(containerId, values, unit){
    const el = document.getElementById(containerId);
    if(!el) return;
    const min = Math.min(...values), max = Math.max(...values), avg = values.reduce((a,b)=>a+b,0)/values.length;
    el.innerHTML =
      '<div class="stat-chip"><div class="k">Mínimo</div><div class="v mono">'+min.toFixed(1)+unit+'</div></div>'+
      '<div class="stat-chip"><div class="k">Promedio</div><div class="v mono">'+avg.toFixed(1)+unit+'</div></div>'+
      '<div class="stat-chip"><div class="k">Máximo</div><div class="v mono">'+max.toFixed(1)+unit+'</div></div>';
  }

  function renderDirectStats(containerId, s, unit){
    const el = document.getElementById(containerId);
    if(!el || !s) return;
    el.innerHTML =
      '<div class="stat-chip"><div class="k">Mínimo</div><div class="v mono">'+(s.min !== undefined ? s.min.toFixed(1) : '—')+unit+'</div></div>'+
      '<div class="stat-chip"><div class="k">Promedio</div><div class="v mono">'+(s.avg !== undefined ? s.avg.toFixed(1) : '—')+unit+'</div></div>'+
      '<div class="stat-chip"><div class="k">Máximo</div><div class="v mono">'+(s.max !== undefined ? s.max.toFixed(1) : '—')+unit+'</div></div>';
  }

  function createOrUpdateChart(canvasId, config, isLive = false){
    const canvas = document.getElementById(canvasId);
    if(!canvas || typeof Chart === 'undefined') return null;

    if(chartInstances[canvasId]){
      const chart = chartInstances[canvasId];
      chart.data.labels = config.data.labels;
      config.data.datasets.forEach((newDs, idx) => {
        if(chart.data.datasets[idx]){
          chart.data.datasets[idx].data = newDs.data;
          chart.data.datasets[idx].label = newDs.label;
          chart.data.datasets[idx].borderColor = newDs.borderColor;
          chart.data.datasets[idx].backgroundColor = newDs.backgroundColor;
          chart.data.datasets[idx].pointRadius = newDs.pointRadius;
          chart.data.datasets[idx].pointHoverRadius = newDs.pointHoverRadius;
        } else {
          chart.data.datasets.push(newDs);
        }
      });
      chart.data.datasets.splice(config.data.datasets.length);
      chart.update(isLive ? 'none' : undefined);
      return chart;
    }

    const ctx = canvas.getContext('2d');
    chartInstances[canvasId] = new Chart(ctx, config);
    return chartInstances[canvasId];
  }

  function getCommonChartOptions(unit, colors){
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 350
      },
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: colors.tooltipBg,
          titleColor: colors.tooltipText,
          bodyColor: colors.tooltipText,
          borderColor: colors.tooltipBorder,
          borderWidth: 1,
          padding: 10,
          cornerRadius: 8,
          displayColors: true,
          callbacks: {
            label: function(context) {
              const label = context.dataset.label || '';
              const val = context.parsed.y !== null ? context.parsed.y.toFixed(1) : '';
              return ` ${label}: ${val} ${unit}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: colors.gridColor },
          ticks: { color: colors.textColor, font: { family: "'IBM Plex Mono', monospace", size: 10 }, maxRotation: 0 }
        },
        y: {
          grid: { color: colors.gridColor },
          ticks: {
            color: colors.textColor,
            font: { family: "'IBM Plex Mono', monospace", size: 10 },
            callback: function(v){ return v + (unit === '%' ? '%' : ''); }
          }
        }
      }
    };
  }

  const rangeSeeds = {'1h':11, '24h':22, '7d':33, '30d':44};
  const rangePoints = {'1h':30, '24h':24, '7d':7, '30d':30};

  function genTimeLabels(range, count){
    const labels = [];
    if(range === '1h'){
      for(let i=count-1; i>=0; i--){
        labels.push(i === 0 ? 'Ahora' : `-${i*2}m`);
      }
    } else if(range === '24h'){
      for(let i=0; i<count; i++){
        labels.push(`${String(i).padStart(2,'0')}:00`);
      }
    } else if(range === '7d'){
      const days = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
      for(let i=0; i<count; i++){
        labels.push(days[i % 7]);
      }
    } else {
      for(let i=1; i<=count; i++){
        labels.push(`D${i}`);
      }
    }
    return labels;
  }

  let isFetchingHistorico = false;

  async function renderHistorico(range, deviceId, isLive = false){
    if(isFetchingHistorico) return;
    isFetchingHistorico = true;

    currentRange = range || currentRange || '1h';
    const colors = getThemeColors();

    let labels = null;
    let vin = null;
    let vout = null;
    let load = null;
    let temp = null;
    let batt = null;
    let stats = null;

    // Intentar consultar datos reales de la API REST /api/historico/
    try {
      const devId = deviceId || (window.__centinelaApp?.selectedDevice?.id) || '';
      const url = devId ? `/api/dispositivos/${devId}/historico/?range=${currentRange}` : `/api/historico/?range=${currentRange}`;
      const res = await fetch(url);
      const json = await res.json();
      if(json.ok && json.data && Array.isArray(json.data.labels) && json.data.labels.length > 0){
        labels = json.data.labels.slice();
        vin = json.data.vin.slice();
        vout = json.data.vout.slice();
        load = json.data.load.slice();
        temp = json.data.temp.slice();
        batt = json.data.battery.slice();
        stats = json.stats;
      }
    } catch(e) {}
    finally {
      isFetchingHistorico = false;
    }

    // Fallback con series simuladas si no hay registros o falla la conexión
    if(!labels || labels.length === 0){
      const n = rangePoints[currentRange], seed = rangeSeeds[currentRange];
      labels = genTimeLabels(currentRange, n);
      vin = genSeries(seed, n, 120, 4, 2.2);
      vout = genSeries(seed+1, n, 120, 2, 1.2);
      load = genSeries(seed+2, n, 46, 18, 6);
      temp = genSeries(seed+3, n, 29, 5, 1.5);
      batt = genSeries(seed+4, n, 92, 14, 5).map(v=>clamp(v,0,100));
    }

    const radius = labels.length > 20 ? 0 : 2;

    // 1. Gráfica de Voltaje (Entrada vs Salida)
    createOrUpdateChart('chartVoltageCanvas', {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'V. Entrada',
            data: vin,
            borderColor: colors.red,
            backgroundColor: 'transparent',
            borderWidth: 2,
            tension: 0.35,
            pointRadius: radius,
            pointHoverRadius: 6,
            pointHoverBackgroundColor: colors.red
          },
          {
            label: 'V. Salida',
            data: vout,
            borderColor: colors.blue,
            backgroundColor: 'transparent',
            borderWidth: 2,
            tension: 0.35,
            pointRadius: radius,
            pointHoverRadius: 6,
            pointHoverBackgroundColor: colors.blue
          }
        ]
      },
      options: getCommonChartOptions('V', colors)
    }, isLive);

    if(stats?.voltage){
      renderDirectStats('statsVoltage', stats.voltage, 'V');
    } else {
      renderStats('statsVoltage', vin.concat(vout), 'V');
    }

    // 2. Gráfica de Carga (%)
    createOrUpdateChart('chartLoadCanvas', {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Carga',
          data: load,
          borderColor: colors.purple,
          backgroundColor: colors.purple + '22',
          fill: true,
          borderWidth: 2,
          tension: 0.35,
          pointRadius: radius,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: colors.purple
        }]
      },
      options: getCommonChartOptions('%', colors)
    }, isLive);

    if(stats?.load){
      renderDirectStats('statsLoad', stats.load, '%');
    } else {
      renderStats('statsLoad', load, '%');
    }

    // 3. Gráfica de Temperatura (°C)
    createOrUpdateChart('chartTempCanvas', {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Temperatura',
          data: temp,
          borderColor: colors.amber,
          backgroundColor: colors.amber + '22',
          fill: true,
          borderWidth: 2,
          tension: 0.35,
          pointRadius: radius,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: colors.amber
        }]
      },
      options: getCommonChartOptions('°C', colors)
    }, isLive);

    if(stats?.temp){
      renderDirectStats('statsTemp', stats.temp, '°C');
    } else {
      renderStats('statsTemp', temp, '°C');
    }

    // 4. Gráfica de Batería (%)
    createOrUpdateChart('chartBatteryCanvas', {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Nivel Batería',
          data: batt,
          borderColor: colors.green,
          backgroundColor: colors.green + '22',
          fill: true,
          borderWidth: 2,
          tension: 0.35,
          pointRadius: radius,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: colors.green
        }]
      },
      options: getCommonChartOptions('%', colors)
    }, isLive);

    if(stats?.battery){
      renderDirectStats('statsBattery', stats.battery, '%');
    } else {
      renderStats('statsBattery', batt, '%');
    }
  }

  // Inicializar listeners del selector de rango
  function initGraficasListeners(){
    const rangeSeg = document.getElementById('rangeSeg');
    if(rangeSeg){
      rangeSeg.addEventListener('click', function(e){
        const btn = e.target.closest('button'); if(!btn) return;
        this.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        renderHistorico(btn.dataset.range);
      });
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initGraficasListeners);
  } else {
    initGraficasListeners();
  }

  // Exponer funciones globales
  window.renderHistorico = renderHistorico;
  window.getCurrentChartRange = () => currentRange;

})(window);
