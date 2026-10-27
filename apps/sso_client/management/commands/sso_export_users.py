"""
Выгрузка пользователей этого проекта для переноса в сервис авторизации:

    python manage.py sso_export_users > users.json
    (на сервере авторизации) python manage.py sso_import_users users.json

Файл содержит хэши паролей: храните и передавайте его как пароли, после импорта удалите.
"""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

FIELDS = (
    "username",
    "password",
    "first_name",
    "last_name",
    "patronymic",
    "department",
    "position",
    "is_active",
    "must_change_password",
)


class Command(BaseCommand):
    help = "Выгрузка пользователей в JSON для команды sso_import_users сервиса авторизации."

    def add_arguments(self, parser):
        parser.add_argument(
            "--active", action="store_true", help="только активные пользователи"
        )

    def handle(self, active=False, **options):
        users = get_user_model().objects.prefetch_related("groups").order_by("username")
        if active:
            users = users.filter(is_active=True)
        rows = []
        for user in users:
            row = {
                field: getattr(user, field) for field in FIELDS if hasattr(user, field)
            }
            row["groups"] = sorted(g.name for g in user.groups.all())
            rows.append(row)
        self.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2))
