/**
 * Модуль для построения столбчатых диаграмм с помощью Chart.js.
 * 
 * Поддерживает горизонтальные и вертикальные графики, стековые режимы,
 * кастомные тултипы с дополнительными данными (количество позиций, суммы в млн ₽).
 * 
 * Зависимости: Chart.js (глобальный объект Chart)
 */
(function () {
  "use strict";

  // --- Цветовая палитра ---

  const SURFACE = "#ffffff";
  const INK_2 = "#52514e";
  const MUTED = "#898781";
  const GRID = "#e1e0d9";
  const BASELINE = "#c3c2b7";

  const CATEGORICAL = ["#2a78d6", "#eb6834"];
  const ORDINAL = ["#86b6ef", "#2a78d6", "#104281"];
  // Цвета этапов по порядку наборов данных; совпадают с цветами карточек сводок.
  // 5-й цвет нужен графику SAP («Готово к передаче в 18 отдел»), раньше
  // он повторял 1-й красный и сливался с «На согласовании».
  const STAGES = ["#be0c0c", "#eb6834", "#2a78d6", "#16a34a", "#ca8a04"];

  // --- Константы оформления ---

  const MAX_BAR_THICKNESS = 22;
  const BAR_BORDER_RADIUS = 2;
  const LEGEND_BOX_SIZE = 10;
  const LEGEND_PADDING = 16;
  const TICK_PADDING = 8;

  // --- Утилиты ---

  const nf1 = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

  /**
   * Форматирует число с учётом единицы измерения.
   * @param {number} value - Число для форматирования
   * @param {string} unit - Единица измерения ("шт" или другая)
   * @returns {string} Отформатированная строка
   */
  function fmt(value, unit) {
    return unit === "шт" ? nf0.format(value) : nf1.format(value);
  }

  // --- Настройки Chart.js по умолчанию ---

  /**
   * Применяет глобальные настройки шрифтов и цветов для всех графиков.
   * Отключает плагин datalabels, если он загружен.
   */
  function applyDefaults() {
    Chart.defaults.font.family =
      "'Golos Text', system-ui, -apple-system, 'Segoe UI', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = INK_2;
    if (window.ChartDataLabels) {
      Chart.defaults.set("plugins.datalabels", { display: false });
    }
  }

  /**
   * Создаёт конфигурацию оси с базовыми настройками сетки и подписей.
   * @param {Object} [extra] - Дополнительные настройки для переопределения
   * @returns {Object} Конфигурация оси
   */
  function axis(extra) {
    return Object.assign(
      {
        grid: { color: GRID, lineWidth: 1, drawTicks: false },
        border: { color: BASELINE, width: 1 },
        ticks: { color: MUTED, padding: TICK_PADDING },
      },
      extra || {}
    );
  }

  const legendTop = {
    display: true,
    position: "top",
    align: "start",
    labels: {
      boxWidth: LEGEND_BOX_SIZE,
      boxHeight: LEGEND_BOX_SIZE,
      usePointStyle: true,
      pointStyle: "circle",
      padding: LEGEND_PADDING,
      color: INK_2,
    },
  };

  // --- Управление состоянием "нет данных" ---

  const EMPTY_MSG_CLASS = "chart-empty-msg";

  /**
   * Показывает сообщение вместо графика и скрывает canvas.
   * @param {HTMLCanvasElement} canvas - Элемент canvas графика
   * @param {HTMLElement} holder - Контейнер графика
   * @param {string} [text] - Текст; по умолчанию «За выбранный период данных нет»
   */
  function showEmpty(canvas, holder, text) {
    let msg = holder.querySelector("." + EMPTY_MSG_CLASS);
    if (!msg) {
      msg = document.createElement("div");
      msg.className = EMPTY_MSG_CLASS;
      holder.appendChild(msg);
    }
    // Текст задаётся каждый раз: одно и то же место показывает и «нет данных», и ошибку
    msg.textContent = text || "За выбранный период данных нет";
    msg.hidden = false;
    canvas.hidden = true;
  }

  /**
   * Скрывает сообщение "нет данных" и показывает canvas.
   * @param {HTMLCanvasElement} canvas - Элемент canvas графика
   * @param {HTMLElement} holder - Контейнер графика
   */
  function hideEmpty(canvas, holder) {
    const msg = holder.querySelector("." + EMPTY_MSG_CLASS);
    if (msg) msg.hidden = true;
    canvas.hidden = false;
  }

  // --- Рендеринг графика ---

  /**
   * Строит столбчатую диаграмму на основе данных с сервера.
   * 
   * @param {string} canvasId - ID элемента canvas
   * @param {Object} payload - Данные графика:
   *   - labels: массив подписей оси
   *   - datasets: массив наборов данных (label, data, counts, amounts)
   *   - unit: единица измерения ("млн ₽" или "шт")
   *   - ordinal: использовать ординальную палитру
   *   - stacked: стековый режим
   *   - horizontal: горизонтальная ориентация
   * @returns {Chart|null} Созданный объект Chart или null при ошибке
   */
  function renderBars(canvasId, payload) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const holder = canvas.parentElement;

    // Удаляем предыдущий график, если есть
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    hideEmpty(canvas, holder);

    const datasets = payload.datasets || [];
    const unit = payload.unit || "";
    const ordinal = Boolean(payload.ordinal);
    const stacked = Boolean(payload.stacked);
    const horizontal = Boolean(payload.horizontal);

    // Проверяем, есть ли данные
    const empty =
      datasets.length === 0 ||
      datasets.every((d) => !d.data || d.data.every((v) => !v));
    if (empty) {
      showEmpty(canvas, holder);
      return null;
    }

    const colors = ordinal ? ORDINAL : CATEGORICAL;

    // Формируем наборы данных для Chart.js
    const chartDatasets = datasets.map(function (d, i) {
      return {
        label: d.label,
        data: d.data,
        amounts: d.amounts || null,
        counts: d.counts || null,
        backgroundColor: horizontal
          ? STAGES[i % STAGES.length]
          : colors[i % colors.length],
        maxBarThickness: MAX_BAR_THICKNESS,
        borderRadius: BAR_BORDER_RADIUS,
        borderColor: SURFACE,
        borderWidth: stacked ? 1 : 0,
      };
    });

    return new Chart(canvas, {
      type: "bar",
      data: { labels: payload.labels, datasets: chartDatasets },
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
              ? { color: MUTED, padding: TICK_PADDING, callback: function (v) { return fmt(v, unit); } }
              : { color: MUTED, padding: TICK_PADDING },
            title: horizontal
              ? { display: true, text: unit, color: MUTED }
              : { display: false },
          }),
          y: axis({
            beginAtZero: !horizontal,
            stacked: stacked,
            grid: { display: !horizontal },
            ticks: horizontal
              ? { color: MUTED, padding: TICK_PADDING }
              : {
                  color: MUTED,
                  padding: TICK_PADDING,
                  callback: function (v) { return fmt(v, unit); },
                },
            title: horizontal
              ? { display: false }
              : { display: true, text: unit, color: MUTED },
          }),
        },
        plugins: {
          legend: datasets.length > 1 ? legendTop : { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const value = horizontal ? ctx.parsed.x : ctx.parsed.y;
                let text = ctx.dataset.label + ": " + fmt(value, unit) + " " + unit;

                // Добавляем количество позиций, если есть
                const counts = ctx.dataset.counts;
                if (counts && counts[ctx.dataIndex] !== undefined && counts[ctx.dataIndex] !== null) {
                  text += " (" + nf0.format(counts[ctx.dataIndex]) + " поз.)";
                }
                // Добавляем сумму в млн ₽, если есть и не нулевая
                const amounts = ctx.dataset.amounts;
                if (amounts && amounts[ctx.dataIndex] !== undefined && amounts[ctx.dataIndex] !== null && amounts[ctx.dataIndex] !== 0) {
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

  // --- Загрузка данных ---

  /**
   * Загружает данные графика по URL и рендерит диаграмму.
   * При ошибке показывает сообщение в контейнере.
   * 
   * @param {string} canvasId - ID элемента canvas
   * @param {string} url - URL для fetch запроса
   */
  async function loadChart(canvasId, url) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const holder = canvas.parentElement;
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      renderBars(canvasId, await resp.json());
    } catch (e) {
      // Canvas не удаляем (раньше здесь был holder.innerHTML = ...): иначе после
      // ошибки график нельзя перестроить, например при смене периода на ЗнП (ФЗД).
      // Текст выводится через textContent, поэтому HTML в нём не сработает.
      const existing = Chart.getChart(canvas);
      if (existing) existing.destroy();
      showEmpty(canvas, holder, "Не удалось построить график: " + e.message);
    }
  }

  // --- Инициализация ---

  applyDefaults();
  window.loadChart = loadChart;
})();