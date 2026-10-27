from django.db import models


class SsoSession(models.Model):
    """Связь сеанса сервиса авторизации (sid) с сессией этого приложения: по ней выполняется выход по уведомлению."""

    sid = models.CharField(max_length=64, db_index=True)
    session_key = models.CharField(max_length=64)
    username = models.CharField(max_length=150, db_index=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "сеанс единого входа"
        verbose_name_plural = "сеансы единого входа"

    def __str__(self):
        return f"{self.username} ({self.sid})"
