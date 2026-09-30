/**
 * Графики для сводок на основе Chart.js.
 *
 * Используется на страницах:
 * - dashboard: график незаключённых по ЦФО
 * - znp_table: график заявок по ЦФО и стадиям
 * - znp_sap_table: график заявок SAP по ЦФО и этапам
 *
 * Данные загружаются через /reports/api/chart/... и рисуются
 * столбчатыми диаграммами (вертикальными или горизонтальными).
 *
 * Использование в шаблонах:
 *   <canvas id="my-chart"></canvas>
 *   <script>loadChart("my-chart", "{% url 'api_chart_znp' %}?igk=...")</script>
 */

(function () {
  "use strict";

  /* ============================================================
     Цветовая палитра графиков
     ============================================================ */

  const SURFACE = "#ffffff";   // фон поверхности (границы между сегментами стека)
  const INK_2 = "#52514e";     // вторичный текст (подписи осей, легенда)
  const MUTED = "#898781";     // приглушённый текст (деления осей)
  const GRID = "#e1e0d9";      // линии сетки
  const BASELINE = "#c3c2b7";  // базовая линия оси

  // Цвета для категориальных данных (например, ДЭГ / не ДЭГ)
  const CATEGORICAL = ["#2a78d6", "#eb6834"];
  // Цвета для ординальных данных (например, давность просрочки)
  const ORDINAL = ["#86b6ef", "#2a78d6", "#104281"];
  // Цвета стадий заявок (красный → оранжевый → синий → зелёный)
  const STAGES = ["#be0c0c", "#eb6834", "#2a78d6", "#16a34a"];

  /* ============================================================
     Вспомогательные функции
     ============================================================ */

  // Экранирование специальных символов для защиты от XSS
  // при вставке данных в HTML (например, в сообщения об ошибках)
  const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function escape(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, function (ch) {
      return ESC_MAP[ch];
    });
  }

  // Форматирование чисел в русском стиле (разделители тысяч — пробелы)
  // с одним знаком после запятой (для сумм в миллионах)
  const nf1 = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  // Целые числа (для количества позиций)
  const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

  /**
   * Форматирует значение в зависимости от единицы измерения.
   * "шт" — целое число, иначе — с одним знаком после запятой.
   */
  function fmt(value, unit) {
    return unit === "шт" ? nf0.format(value) : nf1.format(value);
  }

  /* ============================================================
     Настройки Chart.js по умолчанию
     ============================================================ */

  /**
   * Устанавливает глобальные настройки Chart.js:
   * - шрифт Golos Text (тот же, что и в основном интерфейсе)
   * - цвет текста
   * - отключает подписи данных (плагин ChartDataLabels)
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
   * Возвращает конфигурацию оси с базовыми настройками.
   * Дополнительные параметры передаются через `extra` и перекрывают базовые.
   */
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

  // Конфигурация легенды сверху (для графиков с несколькими сериями)
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

  /* ============================================================
     Заглушка «нет данных»: показать / скрыть
     ============================================================ */

  const EMPTY_MSG_CLASS = "chart-empty-msg";

  /**
   * Показывает сообщение «За выбранный период данных нет»
   * вместо canvas (canvas скрывается, но остаётся в DOM —
   * иначе следующий loadChart не найдёт его через getElementById).
   */
  function showEmpty(canvas, holder) {
    let msg = holder.querySelector("." + EMPTY_MSG_CLASS);
    if (!msg) {
      msg = document.createElement("div");
      msg.className = EMPTY_MSG_CLASS;
      msg.textContent = "За выбранный период данных нет";
      holder.appendChild(msg);
    }
    msg.hidden = false;
    canvas.hidden = true;
  }

  /**
   * Прячет заглушку и возвращает canvas в DOM.
   * Вызывается перед рендером нового графика.
   */
  function hideEmpty(canvas, holder) {
    const msg = holder.querySelector("." + EMPTY_MSG_CLASS);
    if (msg) msg.hidden = true;
    canvas.hidden = false;
  }

  /* ============================================================
     Рендеринг столбчатых графиков
     ============================================================ */

  /**
   * Рисует столбчатый график на указанном канвасе.
   *
   * Параметры:
   * - canvasId: id элемента canvas
   * - payload: данные от сервера:
   *   - labels: подписи оси (например, названия ЦФО)
   *   - datasets: массив серий данных
   *   - unit: единица измерения ("млн ₽", "шт")
   *   - ordinal: использовать ординальную палитру
   *   - stacked: стековый график
   *   - horizontal: горизонтальные столбцы
   *
   * Возвращает объект Chart или null, если данных нет.
   */
  function renderBars(canvasId, payload) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const holder = canvas.parentElement;

    // Уничтожаем предыдущий график (если был) ДО всех проверок,
    // чтобы не оставлять висящих ссылок Chart.js на canvas.
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    // Скрываем заглушку, показываем canvas — на случай, если ранее был пустой результат
    hideEmpty(canvas, holder);

    const datasets = payload.datasets || [];
    const unit = payload.unit || "";
    const ordinal = Boolean(payload.ordinal);
    const stacked = Boolean(payload.stacked);
    const horizontal = Boolean(payload.horizontal);

    // Если все данные пустые — показываем сообщение вместо графика.
    // Canvas скрываем, но НЕ удаляем из DOM.
    const empty =
      datasets.length === 0 ||
      datasets.every((d) => !d.data || d.data.every((v) => !v));
    if (empty) {
      showEmpty(canvas, holder);
      return null;
    }

    // Выбор палитры: для горизонтальных — цвета стадий,
    // для вертикальных — категориальные или ординальные
    const colors = ordinal ? ORDINAL : CATEGORICAL;

    // Преобразуем данные сервера в формат датасетов Chart.js
    const chartDatasets = datasets.map(function (d, i) {
      return {
        label: d.label,
        data: d.data,
        amounts: d.amounts || null,  // суммы в миллионах (для тултипов)
        counts: d.counts || null,    // количество позиций (для тултипов)
        backgroundColor: horizontal
          ? STAGES[i % STAGES.length]
          : colors[i % colors.length],
        maxBarThickness: 22,
        borderRadius: 2,
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
                  callback: function (v) { return fmt(v, unit); },
                },
            title: horizontal
              ? { display: false }
              : { display: true, text: unit, color: MUTED },
          }),
        },
        plugins: {
          // Легенда только если серий больше одной
          legend: datasets.length > 1 ? legendTop : { display: false },
          // Тултипы: значение + количество позиций + сумма в миллионах
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const value = horizontal ? ctx.parsed.x : ctx.parsed.y;
                let text = ctx.dataset.label + ": " + fmt(value, unit) + " " + unit;

                const counts = ctx.dataset.counts;
                if (counts && counts[ctx.dataIndex] !== undefined && counts[ctx.dataIndex] !== null) {
                  text += " (" + nf0.format(counts[ctx.dataIndex]) + " поз.)";
                }
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

  /* ============================================================
     Загрузка данных и рендеринг
     ============================================================ */

  /**
   * Загружает данные графика с сервера и рисует его.
   *
   * Используется в шаблонах:
   *   loadChart("chart-contracts", "/reports/api/chart/contracts/?igk=...&year=2026")
   *
   * При ошибке показывает сообщение вместо графика.
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
      holder.innerHTML =
        '<div class="error-msg">Не удалось построить график: ' +
        escape(e.message) +
        "</div>";
    }
  }

  /* ============================================================
     Инициализация
     ============================================================ */

  // Применяем настройки по умолчанию при загрузке скрипта
  applyDefaults();

  // Экспортируем функцию загрузки графиков в глобальную область видимости,
  // чтобы её можно было вызывать из шаблонов
  window.loadChart = loadChart;
})();