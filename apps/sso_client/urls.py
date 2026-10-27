"""Адреса единого входа: подключаются в config/urls.py как path("sso/", include(...)).

Вход и выход сайта (/reports/login/, /reports/logout/, core/views/auth.py) сами передают
работу сюда, если единый вход включён, — шаблоны и меню менять не нужно.
"""

from django.urls import path

from . import views

app_name = "sso_client"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("callback/", views.callback, name="callback"),
    path("logout/", views.logout, name="logout"),
    path("backchannel-logout/", views.backchannel_logout, name="backchannel_logout"),
]
