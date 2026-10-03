document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('fetch-external-data-btn');
    if (!btn) return;

    const fillField = (id, value) => {
        const el = document.getElementById(id);
        if (el && value !== undefined) {
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

        const url = btn.dataset.urlTemplate.replace('EMP_PLACEHOLDER', encodeURIComponent(empNumber));

        status.textContent = 'Загрузка...';

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Ошибка запроса');
            }

            const data = await response.json();

            fillField('id_first_name', data.name);
            fillField('id_last_name', data.surname);
            fillField('id_email', data.email);
            fillField('id_patronymic', data.patronymic);
            fillField('id_api_key', data.api_key);

            const isFiredField = document.getElementById('id_is_fired');
            if (isFiredField) {
                isFiredField.checked = Boolean(data.is_fired);
            }

            status.textContent = 'Готово';
        } catch (err) {
            status.textContent = 'Ошибка: ' + err.message;
        }
    });
});