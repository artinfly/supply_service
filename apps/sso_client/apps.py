from django.apps import AppConfig


class SsoClientConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sso_client"
    label = "sso_client"
    verbose_name = "Единый вход"
