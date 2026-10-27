"""Вход и выход из системы, главная страница.

Если включён единый вход (в .env задан SSO_SERVER_URL), вход и выход выполняет
apps.sso_client: пароль проверяет сервис авторизации. Иначе — обычный вход по паролю.
"""

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from apps.sso_client import conf as sso
from apps.sso_client.views import logout as sso_logout

from .common import base_context


def _next_url(request):
    """Адрес из ?next=, куда вернуть пользователя после входа, или None.

    login_required отправляет на вход с ?next=<исходная страница>. Берём только
    адреса этого же сайта, чтобы по ссылке нельзя было увести на чужой.
    """
    url = request.POST.get("next") or request.GET.get("next")
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return None


def login_view(request):
    """Страница входа. Уже вошедшего пользователя отправляет на главную."""
    if request.user.is_authenticated:
        return redirect(_next_url(request) or "root")
    if sso.enabled():
        url = reverse("sso_client:login")
        if next_url := _next_url(request):
            url += "?" + urlencode({"next": next_url})
        return redirect(url)

    error = False
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
        if user:
            login(request, user)
            return redirect(_next_url(request) or "root")
        error = True

    return render(
        request, "login.html", {"error": error, "next": _next_url(request) or ""}
    )


def logout_view(request):
    """Выход из системы — только POST-запросом (кнопка «Выйти» в меню).

    GET (открыли адрес /logout/ напрямую или по чужой ссылке) не разлогинивает,
    а просто возвращает на главную.
    """
    if request.method != "POST":
        return redirect("root")
    if sso.enabled():
        return sso_logout(request)
    logout(request)
    return redirect("login")


@login_required
def index(request):
    """Главная страница: плитки разделов (видны только разрешённые пользователю)."""
    return render(request, "index.html", base_context())
