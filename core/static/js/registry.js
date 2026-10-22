"use strict";

// Общая логика реестров (договоры, ЗнП ФЗД, ЗнП SAP): фильтры, запрос к API,
// таблица с пагинацией. Страница передаёт в initRegistry только своё:
// колонки, чекбоксы статусов и какие фильтры у неё есть.
// Нужны функции esc, fmtDate и apiError из base.html.

/**
 * Размер страницы из списка #page-size (Infinity, если выбрано «Все»).
 */
function pageSize() {
    const el = document.getElementById('page-size');
    if (!el) return 100;
    const v = parseInt(el.value, 10);
    return v === 0 ? Infinity : v;
}

/**
 * Кнопки страниц в элементе id; onPage(номер) вызывается по клику.
 */
function renderPagination(total, ps, cur, id, onPage) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!isFinite(ps) || total <= ps) { el.innerHTML = ''; return; }

    const pages = Math.ceil(total / ps);
    const d = 2;
    let html = '<div class="d-flex gap-1 flex-wrap align-items-center">';
    html += `<button class="pgn-btn" data-p="1" ${cur === 1 ? 'disabled' : ''}>«</button>`;
    html += `<button class="pgn-btn" data-p="${cur - 1}" ${cur === 1 ? 'disabled' : ''}>‹</button>`;

    for (let p = 1; p <= pages; p++) {
        if (p === 1 || p === pages || (p >= cur - d && p <= cur + d)) {
            html += `<button class="pgn-btn${p === cur ? ' pgn-active' : ''}" data-p="${p}">${p}</button>`;
        } else if (p === cur - d - 1 || p === cur + d + 1) {
            html += '<span style="padding:0 4px;color:var(--text-muted)">…</span>';
        }
    }

    html += `<button class="pgn-btn" data-p="${cur + 1}" ${cur === pages ? 'disabled' : ''}>›</button>`;
    html += `<button class="pgn-btn" data-p="${pages}" ${cur === pages ? 'disabled' : ''}>»</button>`;
    html += `<span class="row-count-label ms-2">стр. ${cur} из ${pages}</span></div>`;
    el.innerHTML = html;

    el.querySelectorAll('.pgn-btn:not([disabled])').forEach(btn => {
        btn.addEventListener('click', () => onPage(parseInt(btn.dataset.p, 10)));
    });
}

/**
 * Значение ячейки для показа (уже экранированное, можно вставлять в HTML).
 *
 * Колонка: field, title, style (атрибут ширины), wrap (класс переноса),
 * format ('number' | 'date'), short (показывать последние 4 символа — ИГК).
 */
function registryCell(col, row, config) {
    let val = row[col.field] ?? '';
    if (config.subtotalLabel && row.is_subtotal === 1 && col.field === config.subtotalLabel.field) {
        val = config.subtotalLabel.text;
    } else if (val !== '' && col.short) {
        val = String(val).slice(-4);
    } else if (val !== '' && col.format === 'number') {
        val = parseFloat(val).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } else if (val !== '' && col.format === 'date') {
        val = fmtDate(val);
    } else if (typeof val === 'string') {
        val = val.trim();
    }
    // Номер договора: место переноса — только после «/»
    return col.field === 'contract' ? esc(val).replace(/\//g, '/<wbr>') : esc(val);
}

/**
 * Подключает реестр к странице.
 *
 * config:
 *   apiUrl        — адрес JSON API;
 *   cols          — колонки таблицы (см. registryCell);
 *   statusBoxes   — чекбоксы статусов: { id, name (как в ссылке ?statuses=),
 *                   values (что отправить в API), reset (отмечен после «Сбросить») };
 *   aliases       — имена из ссылки, которые раскрываются в несколько чекбоксов;
 *   hasYear       — есть список #filter-year;
 *   hasDate       — фильтр ?date= из ссылки карточки (полей нет, видна подпись #date-note);
 *   onlyTotalsId  — чекбокс «Только итоги» (показывает строки с is_subtotal);
 *   subtotalLabel — { field, text }: что написать в итоговой строке.
 */
function initRegistry(config) {
    const el = id => document.getElementById(id);
    const textFilters = ['agent', 'igk', 'cfo'];
    let loadedData = [];
    let currentPage = 1;
    let selectedDate = '';

    function buildUrl() {
        const params = new URLSearchParams();
        for (const name of textFilters) {
            const value = el(`filter-${name}`).value.trim();
            if (value) params.append(name, value);
        }
        if (config.hasDate && selectedDate) params.append('date', selectedDate);
        for (const box of config.statusBoxes) {
            if (el(box.id).checked) box.values.forEach(v => params.append('status', v));
        }
        // Ни одного статуса — пустой параметр, чтобы API вернул пусто, а не всё
        if (!params.has('status')) params.append('status', '');
        if (config.hasYear && el('filter-year').value !== 'all') {
            params.append('year', el('filter-year').value);
        }
        return config.apiUrl + '?' + params.toString();
    }

    async function loadData() {
        el('table-wrapper').innerHTML =
            '<div class="loading-spinner"><div class="spinner-border spinner-border-sm"></div> Загрузка…</div>';
        try {
            const resp = await fetch(buildUrl());
            if (!resp.ok) throw new Error(apiError(resp));
            loadedData = await resp.json();
            currentPage = 1;
            renderPage();
        } catch (e) {
            el('table-wrapper').innerHTML = `<div class="error-msg">Ошибка загрузки: ${esc(e.message)}</div>`;
        }
    }

    function goToPage(page) {
        currentPage = page;
        renderPage();
    }

    function renderPage() {
        const onlyTotals = config.onlyTotalsId && el(config.onlyTotalsId).checked;
        const rows = onlyTotals ? loadedData.filter(r => r.is_subtotal === 1) : loadedData;
        const ps = pageSize();
        const start = isFinite(ps) ? (currentPage - 1) * ps : 0;
        const slice = isFinite(ps) ? rows.slice(start, start + ps) : rows;

        el('row-count').textContent = rows.length;
        if (config.hasDate) {
            el('date-note').textContent = selectedDate ? ` · за ${fmtDate(selectedDate)}` : '';
        }
        renderPagination(rows.length, ps, currentPage, 'pagination-top', goToPage);
        renderPagination(rows.length, ps, currentPage, 'pagination-bot', goToPage);

        if (!slice.length) {
            el('table-wrapper').innerHTML = '<div class="p-4 text-muted text-center">Нет данных по заданным фильтрам</div>';
            return;
        }

        let html = '<table class="report-table registry-table" style="table-layout: auto;"><thead><tr>';
        config.cols.forEach(col => { html += `<th ${col.style || ''}>${esc(col.title)}</th>`; });
        html += '</tr></thead><tbody>';
        slice.forEach(row => {
            html += row.is_subtotal === 1 ? '<tr class="row-subtotal">' : '<tr>';
            config.cols.forEach(col => {
                const align = col.format === 'number' ? 'text-end' : '';
                // Свой режим переноса колонки; иначе длинный текст без ширины переносится
                const wrap = col.wrap || ((!col.format && !col.style) ? 'wrap' : '');
                const classes = [align, wrap].filter(Boolean).join(' ');
                html += `<td class="${classes}">${registryCell(col, row, config)}</td>`;
            });
            html += '</tr>';
        });
        el('table-wrapper').innerHTML = html + '</tbody></table>';
    }

    // Фильтры из адреса страницы: ссылки с карточек сводок и обновление (F5)
    function loadFiltersFromURL() {
        const params = new URLSearchParams(window.location.search);
        for (const name of textFilters) {
            if (params.has(name)) el(`filter-${name}`).value = params.get(name);
        }
        if (config.hasYear && params.has('year')) el('filter-year').value = params.get('year');
        if (config.hasDate && params.has('date')) selectedDate = params.get('date');
        if (params.has('statuses')) {
            const asked = new Set();
            for (const s of params.get('statuses').split(',')) {
                const name = s.trim();
                ((config.aliases || {})[name] || [name]).forEach(x => asked.add(x));
            }
            for (const box of config.statusBoxes) el(box.id).checked = asked.has(box.name);
        }
    }

    function resetFilters() {
        textFilters.forEach(name => { el(`filter-${name}`).value = ''; });
        config.statusBoxes.forEach(box => { el(box.id).checked = box.reset; });
        if (config.onlyTotalsId) el(config.onlyTotalsId).checked = false;
        if (config.hasYear) el('filter-year').value = 'all';
        selectedDate = '';
        loadData();
    }

    el('page-size').addEventListener('change', () => goToPage(1));
    if (config.onlyTotalsId) el(config.onlyTotalsId).addEventListener('change', () => goToPage(1));
    el('filter-agent').addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });
    el('btn-search').addEventListener('click', loadData);
    el('btn-reset').addEventListener('click', resetFilters);

    loadFiltersFromURL();
    loadData();
}
