"""
Вход через сервис авторизации.

    login       - отправляет браузер на сервис авторизации (/sso/authorize/) с адресом возврата и state;
    callback    - получает одноразовый билет, проверяет его запросом сервер-сервер, создаёт или обновляет
                  местного пользователя (по логину) и открывает сессию;
    logout      - закрывает сессию здесь и отправляет браузер на выход из сервиса авторизации,
                  который уведомит остальные приложения;
    backchannel_logout - уведомление сервиса авторизации о выходе (сервер-сервер, подпись HMAC).
"""

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from functools import wraps
from importlib import import_module
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_not_required
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import redirect, render, resolve_url
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import conf
from .models import SsoSession

SESSION_STATES = "sso_states"
SESSION_SID = "sso_sid"
MAX_STATES = 10
PROFILE_FIELDS = ("first_name", "last_name", "patronymic", "department", "position")
TIMEOUT = 5
BACKCHANNEL_MAX_AGE = 300

# Запросы идут на сервис авторизации в локальной сети: системный прокси (HTTP_PROXY) не нужен.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sso_only(view):
    """Адреса единого входа отвечают 404, пока он выключен (не задан SSO_SERVER_URL)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not conf.enabled():
            raise Http404("Единый вход не настроен")
        return view(request, *args, **kwargs)

    return wrapper


class SsoError(Exception):
    pass


class NoLocalUser(Exception):
    """Пользователь есть в сервисе авторизации, но не заведён в этом проекте (при SSO_AUTO_CREATE=False)."""


def bounce(request, url):
    """
    Переход на сервис авторизации страницей с meta refresh, а не ответом 302: браузер проверяет
    CSP form-action на всех редиректах после отправки формы (например, кнопки «Выйти»),
    и прямой редирект на чужой адрес был бы заблокирован.
    """
    return render(request, "sso_client/redirect.html", {"url": url})


def _absolute(request, path):
    base = conf.client_url()
    if base:
        return base + path.lstrip("/")
    return request.build_absolute_uri(path)


def home():
    """
    Куда вести после входа, если не указано иное: LOGIN_REDIRECT_URL проекта (имя маршрута или путь).
    Если настройки нет (у Django по умолчанию это несуществующий /accounts/profile/) или такой адрес
    в проекте не находится - главная "/". Больше клиент от этих настроек не зависит
    (LOGOUT_REDIRECT_URL не используется: после выхода браузер возвращается с сервиса авторизации на "/").
    """
    try:
        url = resolve_url(getattr(settings, "LOGIN_REDIRECT_URL", None) or "/")
        resolve(urlsplit(url).path)
    except (NoReverseMatch, Resolver404):
        return "/"
    return url


def _safe_next(request, url):
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return home()


@login_not_required
@require_GET
@sso_only
def login(request):
    next_url = _safe_next(request, request.GET.get("next"))
    if request.user.is_authenticated:
        return redirect(next_url)

    state = secrets.token_urlsafe(16)
    states = request.session.get(SESSION_STATES, {})
    states = dict(
        list(states.items())[-(MAX_STATES - 1) :]
    )  # несколько вкладок входят одновременно
    states[state] = next_url
    request.session[SESSION_STATES] = states

    params = urllib.parse.urlencode(
        {
            "client_id": conf.client_id(),
            "redirect_uri": _absolute(request, reverse("sso_client:callback")),
            "state": state,
        }
    )
    return bounce(request, f"{conf.server_url()}sso/authorize/?{params}")


def _validate(request, ticket):
    data = urllib.parse.urlencode(
        {
            "client_id": conf.client_id(),
            "client_secret": conf.client_secret(),
            "ticket": ticket,
            "redirect_uri": _absolute(request, reverse("sso_client:callback")),
        }
    ).encode()
    url = conf.server_internal_url() + "sso/api/validate/"
    try:
        with _opener.open(
            urllib.request.Request(url, data=data, method="POST"), timeout=TIMEOUT
        ) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            code = json.loads(exc.read()).get("error", exc.code)
        except ValueError:
            code = exc.code
        raise SsoError(f"сервис авторизации отклонил вход ({code})") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SsoError(f"сервис авторизации недоступен ({exc})") from exc


def sync_user(data):
    """Создаёт или обновляет местного пользователя (профиль и активность) по данным сервиса авторизации. Ищется по логину."""
    User = get_user_model()
    if conf.auto_create():
        user, _ = User.objects.get_or_create(username=data["username"])
    else:
        user = User.objects.filter(username=data["username"]).first()
        if user is None:
            raise NoLocalUser(data["username"])
    for field in PROFILE_FIELDS:
        if hasattr(user, field) and field in data:
            setattr(user, field, data[field])
    user.is_active = True
    if hasattr(user, "must_change_password"):
        user.must_change_password = False  # паролем управляет сервис авторизации
    user.set_unusable_password()  # пароль хранит и проверяет только сервис авторизации
    user.save()  # группы и права (staff, superuser) остаются локальными
    return user


@login_not_required
@require_GET
@sso_only
def callback(request):
    states = request.session.get(SESSION_STATES, {})
    state = request.GET.get("state", "")
    if state not in states:
        # Чаще всего - вернулись по старой ссылке или истекла сессия: начинаем вход заново
        return redirect("sso_client:login")
    next_url = states.pop(state)
    request.session[SESSION_STATES] = states

    try:
        result = _validate(request, request.GET.get("ticket", ""))
    except SsoError as exc:
        return render(request, "sso_client/error.html", {"text": str(exc)}, status=502)

    try:
        user = sync_user(result["user"])
    except NoLocalUser:
        return render(
            request,
            "sso_client/no_user.html",
            {"username": result["user"]["username"]},
            status=403,
        )
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[SESSION_SID] = result["sid"]
    SsoSession.objects.filter(
        created__lt=timezone.now() - timedelta(seconds=settings.SESSION_COOKIE_AGE)
    ).delete()
    SsoSession.objects.create(
        sid=result["sid"],
        session_key=request.session.session_key,
        username=user.username,
    )
    return redirect(_safe_next(request, next_url))


@login_not_required
@sso_only
def logout(request):
    if request.method != "POST":
        return redirect(home())
    if request.session.session_key:
        SsoSession.objects.filter(session_key=request.session.session_key).delete()
    auth_logout(request)
    params = urllib.parse.urlencode(
        {"client_id": conf.client_id(), "next": _absolute(request, "/")}
    )
    return bounce(request, f"{conf.server_url()}sso/logout/?{params}")


def password_change(request):
    """Смена пароля в админке: при едином входе пароль меняется в сервисе авторизации."""
    if not conf.enabled():
        from django.contrib import admin

        return admin.site.password_change(request)
    return redirect(f"{conf.server_url()}password/change/")


def _delete_sessions(queryset):
    store = import_module(settings.SESSION_ENGINE).SessionStore
    count = 0
    for item in queryset:
        store().delete(item.session_key)
        count += 1
    queryset.delete()
    return count


@login_not_required
@csrf_exempt
@require_POST
@sso_only
def backchannel_logout(request):
    expected = hmac.new(
        conf.client_secret().encode(), request.body, hashlib.sha256
    ).hexdigest()
    if not conf.client_secret() or not hmac.compare_digest(
        expected, request.headers.get("X-SSO-Signature", "")
    ):
        return HttpResponseForbidden("bad signature")
    try:
        data = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("bad json")
    if (
        data.get("client_id") != conf.client_id()
        or abs(time.time() - int(data.get("iat", 0))) > BACKCHANNEL_MAX_AGE
    ):
        return HttpResponseForbidden("stale or foreign request")

    if data.get("sid"):
        count = _delete_sessions(SsoSession.objects.filter(sid=data["sid"]))
    elif data.get("username"):
        count = _delete_sessions(SsoSession.objects.filter(username=data["username"]))
    else:
        return HttpResponseBadRequest("nothing to do")
    return HttpResponse(f"ok {count}")
