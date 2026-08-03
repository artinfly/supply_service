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
  const STAGES = ["#be0c0c", "#eb6834", "#2a78d6", "#16a34a"];

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

  function renderBars(canvasId, payload) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const unit = payload.unit || "";
    const ordinal = Boolean(payload.ordinal);
    const stacked = Boolean(payload.stacked);
    const horizontal = Boolean(payload.horizontal);
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
        counts: d.counts || null,
        backgroundColor: horizontal
          ? STAGES[i % STAGES.length]
          : colors[i % colors.length],
        maxBarThickness: 22,
        borderRadius: 2,
        borderColor: SURFACE,
        borderWidth: stacked ? 1 : 0,
      };
    });

    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    return new Chart(canvas, {
      type: "bar",
      data: { labels: payload.labels, datasets: datasets },
      options: {
        indexAxis: horizontal ? "y" : "x",
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis({
            grid: { display: horizontal },
            stacked: stacked,
            beginAtZero: horizontal,
            ticks: horizontal
              ? { color: MUTED, padding: 8, callback: function (v) { return fmt(v, unit); } }
              : { color: MUTED, padding: 8 },
            title: horizontal
              ? { display: true, text: unit, color: MUTED }
              : { display: false },
          }),
          y: axis({
            beginAtZero: !horizontal,
            stacked: stacked,
            grid: { display: !horizontal },
            ticks: horizontal
              ? { color: MUTED, padding: 8 }
              : {
                  color: MUTED,
                  padding: 8,
                  callback: function (v) {
                    return fmt(v, unit);
                  },
                },
            title: horizontal
              ? { display: false }
              : { display: true, text: unit, color: MUTED },
          }),
        },
        plugins: {
          legend: payload.datasets.length > 1 ? legendTop : { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const value = horizontal ? ctx.parsed.x : ctx.parsed.y;
                let text = ctx.dataset.label + ": " + fmt(value, unit) + " " + unit;
                const counts = ctx.dataset.counts;
                if (counts) {
                  text += " (" + nf0.format(counts[ctx.dataIndex]) + " поз.)";
                }
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
