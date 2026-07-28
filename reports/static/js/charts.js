/* Общий слой над Chart.js: палитра, форматы, единый вид всех графиков.
 *
 * Подключается только на страницах с графиками — 220 КБ библиотеки не должны
 * грузиться там, где графиков нет.
 *
 * Цвета не подбирать на глаз: набор проверен на различимость, в том числе
 * при дальтонизме, и на контраст к белой подложке карточек.
 *   - две серии (план/факт) — синий и оранжевый, это разные сущности;
 *   - этапы SAP упорядочены, поэтому одноцветная шкала от светлого к тёмному,
 *     а не радуга: порядок читается сам собой.
 * Фирменный оранжевый интерфейса (#e07b2a) в сериях намеренно не участвует,
 * иначе график спорит с кнопками и меню.
 */
(function () {
  "use strict";

  const SURFACE = "#ffffff";
  const INK = "#1e1e1e";
  const INK_2 = "#52514e";
  const MUTED = "#898781";
  const GRID = "#e1e0d9";
  const BASELINE = "#c3c2b7";

  const CATEGORICAL = ["#2a78d6", "#eb6834"];
  const ORDINAL = ["#86b6ef", "#2a78d6", "#104281"];

  // своё экранирование, а не esc() из base.html: модуль должен работать и там,
  // где базовый шаблон не подключён
  const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function escape(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, function (ch) {
      return ESC_MAP[ch];
    });
  }

  const nf1 = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

  function applyDefaults() {
    Chart.defaults.font.family =
      "'Golos Text', system-ui, -apple-system, 'Segoe UI', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = INK_2;
    // подписи значений включаются точечно: число над каждым столбцом
    // превращает график в мусор и перестаёт читаться
    if (window.ChartDataLabels) {
      Chart.defaults.set("plugins.datalabels", { display: false });
    }
  }

  function axis(extra) {
    return Object.assign(
      {
        grid: { color: GRID, lineWidth: 1, drawTicks: false },
        border: { color: BASELINE, width: 1 },
        ticks: { color: MUTED, padding: 8 },
      },
      extra || {}
    );
  }

  const legendTop = {
    display: true,
    position: "top",
    align: "start",
    labels: {
      boxWidth: 10,
      boxHeight: 10,
      usePointStyle: true,
      pointStyle: "circle",
      padding: 16,
      color: INK_2,
    },
  };

  function fmt(value, unit) {
    return unit === "шт" ? nf0.format(value) : nf1.format(value);
  }

  /* Рисует столбчатый график по ответу /api/chart/... */
  function renderBars(canvasId, payload) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const unit = payload.unit || "";
    const ordinal = Boolean(payload.ordinal);
    const colors = ordinal ? ORDINAL : CATEGORICAL;

    const empty = payload.datasets.every((d) =>
      d.data.every((v) => !v)
    );
    const holder = canvas.parentElement;
    if (empty) {
      holder.innerHTML =
        '<div class="p-4 text-muted text-center" style="font-size:13px">' +
        "За выбранный период данных нет</div>";
      return null;
    }

    const datasets = payload.datasets.map(function (d, i) {
      return {
        label: d.label,
        data: d.data,
        amounts: d.amounts || null,
        backgroundColor: colors[i % colors.length],
        maxBarThickness: 22,
        borderRadius: { topLeft: 4, topRight: 4 },
        borderSkipped: "bottom",
      };
    });

    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    return new Chart(canvas, {
      type: "bar",
      data: { labels: payload.labels, datasets: datasets },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis({ grid: { display: false } }),
          y: axis({
            beginAtZero: true,
            ticks: {
              color: MUTED,
              padding: 8,
              callback: function (v) {
                return fmt(v, unit);
              },
            },
            title: { display: true, text: unit, color: MUTED },
          }),
        },
        plugins: {
          legend: payload.datasets.length > 1 ? legendTop : { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                let text =
                  ctx.dataset.label + ": " + fmt(ctx.parsed.y, unit) + " " + unit;
                // у SAP по оси количество, а сумма нужна как справка
                const amounts = ctx.dataset.amounts;
                if (amounts && amounts[ctx.dataIndex]) {
                  text += " (" + nf1.format(amounts[ctx.dataIndex]) + " млн ₽)";
                }
                return text;
              },
            },
          },
        },
      },
    });
  }

  /* Забирает данные и рисует. url уже содержит нужные igk и year. */
  async function loadChart(canvasId, url) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const holder = canvas.parentElement;
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      renderBars(canvasId, await resp.json());
    } catch (e) {
      holder.innerHTML =
        '<div class="error-msg">Не удалось построить график: ' +
        escape(e.message) +
        "</div>";
    }
  }

  applyDefaults();
  window.loadChart = loadChart;
})();
