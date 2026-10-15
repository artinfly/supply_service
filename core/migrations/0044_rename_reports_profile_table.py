"""Переименование таблицы профилей reports_profile -> core_profile.

Приложение раньше называлось reports, и таблица профилей создавалась как
reports_profile. Миграция 0043 только записывает в Django имя core_profile,
но саму таблицу не переименовывает (для Django это «ничего не изменилось»).
Из-за этого на старых базах админка пользователей падала с ошибкой
«отношение core_profile не существует».

SQL ниже безопасен для любой базы:
  * есть reports_profile и нет core_profile — таблица переименовывается;
  * core_profile уже есть (новая база или переименовали вручную) — ничего не делается.
"""

from django.db import migrations

RENAME_SQL = """
DO $$
BEGIN
    IF to_regclass('core_profile') IS NULL AND to_regclass('reports_profile') IS NOT NULL THEN
        ALTER TABLE reports_profile RENAME TO core_profile;
    END IF;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0043_alter_igkstatdata_c_date_alter_profile_table"),
    ]

    # Обратная операция не нужна: имя core_profile правильное для текущего кода
    operations = [migrations.RunSQL(RENAME_SQL, migrations.RunSQL.noop)]
