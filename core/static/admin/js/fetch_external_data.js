/**
 * Скрипт для загрузки данных сотрудника из HR API в форму пользователя админки.
 * 
 * Ожидает кнопку с id="fetch-external-data-btn" и атрибутом data-url-template,
 * содержащим URL с плейсхолдером EMP_PLACEHOLDER для табельного номера.
 * 
 * Заполняет поля: first_name, last_name, patronymic, api_key, is_fired
 */

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('fetch-external-data-btn');
    if (!btn) return;

    // Проверяем наличие URL-шаблона
    const urlTemplate = btn.dataset.urlTemplate;
    if (!urlTemplate) {
        console.error('fetch_external_data: не задан data-url-template для кнопки');
        return;
    }

    /**
     * Заполняет поле формы значением, если поле существует и значение определено.
     * @param {string} id - ID поля формы
     * @param {*} value - Значение для заполнения
     */
    const fillField = (id, value) => {
        const el = document.getElementById(id);
        if (el && value !== undefined && value !== null) {
            el.value = value;
        }
    };

    btn.addEventListener('click', async () => {
        const usernameField = document.getElementById('id_username');
        const status = document.getElementById('fetch-external-data-status');

        if (!usernameField) {
            status.textContent = 'Не найдено поле username';
            return;
        }

        const empNumber = usernameField.value.trim();

        if (!empNumber) {
            status.textContent = 'Сначала заполните username';
            return;
        }

        // Блокируем кнопку на время загрузки
        btn.disabled = true;
        status.textContent = 'Загрузка...';

        const url = urlTemplate.replace('EMP_PLACEHOLDER', encodeURIComponent(empNumber));

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                // При ошибке сервера (500) приходит HTML, а не JSON — тогда
                // показываем код ответа вместо непонятной ошибки разбора JSON
                let message = `Ошибка запроса (код ${response.status})`;
                try {
                    message = (await response.json()).error || message;
                } catch (_) { /* ответ не JSON */ }
                throw new Error(message);
            }

            const data = await response.json();

            // Заполняем поля формы данными из API
            fillField('id_first_name', data.name);
            fillField('id_last_name', data.surname);
            fillField('id_patronymic', data.patronymic);
            fillField('id_api_key', data.api_key);

            // Поле email не используется в кастомной форме, но оставляем на случай стандартной формы
            if (data.email) {
                fillField('id_email', data.email);
            }

            // Чекбокс "Уволен"
            const isFiredField = document.getElementById('id_is_fired');
            if (isFiredField) {
                isFiredField.checked = Boolean(data.is_fired);
            }

            status.textContent = 'Готово';
            
            // Очищаем статус через 3 секунды
            setTimeout(() => {
                if (status.textContent === 'Готово') {
                    status.textContent = '';
                }
            }, 3000);
        } catch (err) {
            status.textContent = 'Ошибка: ' + err.message;
        } finally {
            // Разблокируем кнопку
            btn.disabled = false;
        }
    });
});