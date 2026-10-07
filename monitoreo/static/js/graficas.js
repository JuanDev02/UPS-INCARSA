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

  function createOrUpdateChart(canvasId, config){
    if(chartInstances[canvasId]){
      chartInstances[canvasId].destroy();
    }
    const canvas = document.getElementById(canvasId);
    if(!canvas || typeof Chart === 'undefined') return null;
    const ctx = canvas.getContext('2d');
    chartInstances[canvasId] = new Chart(ctx, config);
    return chartInstances[canvasId];
  }

  function getCommonChartOptions(unit, colors){
    return {
      responsive: true,
      maintainAspectRatio: false,
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

  function renderHistorico(range){
    currentRange = range || currentRange || '1h';
    const n = rangePoints[currentRange], seed = rangeSeeds[currentRange];
    const labels = genTimeLabels(currentRange, n);
    const colors = getThemeColors();

    // 1. Gráfica de Voltaje (Entrada vs Salida)
    const vin = genSeries(seed, n, 120, 4, 2.2);
    const vout = genSeries(seed+1, n, 120, 2, 1.2);
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
            pointRadius: 0,
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
            pointRadius: 0,
            pointHoverRadius: 6,
            pointHoverBackgroundColor: colors.blue
          }
        ]
      },
      options: getCommonChartOptions('V', colors)
    });
    renderStats('statsVoltage', vin.concat(vout), 'V');

    // 2. Gráfica de Carga (%)
    const load = genSeries(seed+2, n, 46, 18, 6);
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
          pointRadius: 0,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: colors.purple
        }]
      },
      options: getCommonChartOptions('%', colors)
    });
    renderStats('statsLoad', load, '%');

    // 3. Gráfica de Temperatura (°C)
    const temp = genSeries(seed+3, n, 29, 5, 1.5);
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
          pointRadius: 0,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: colors.amber
        }]
      },
      options: getCommonChartOptions('°C', colors)
    });
    renderStats('statsTemp', temp, '°C');

    // 4. Gráfica de Batería (%)
    const batt = genSeries(seed+4, n, 92, 14, 5).map(v=>clamp(v,0,100));
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
          pointRadius: 0,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: colors.green
        }]
      },
      options: getCommonChartOptions('%', colors)
    });
    renderStats('statsBattery', batt, '%');
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
