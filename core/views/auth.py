"""Вход и выход из системы, главная страница."""

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

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
    """Выход из системы."""
    logout(request)
    return redirect("login")


@login_required
def index(request):
    """Главная страница: плитки разделов (видны только разрешённые пользователю)."""
    return render(request, "index.html", base_context())
