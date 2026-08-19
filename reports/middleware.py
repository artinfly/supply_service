from django.http import JsonResponse
from django.shortcuts import render

from .services.queries import YEARS

SECTIONS = (
    ("access_upload", ("upload",)),
    ("access_export", ("export",)),
    ("access_znp_sap", ("znp_sap",)),
    ("access_znp", ("znp",)),
    ("access_igk", ("igk",)),
    ("access_kdr", ("kdr",)),
    ("access_history", ("history",)),
    ("access_dupes", ("dupes",)),
    ("access_dashboard", ("dashboard", "contracts", "chart")),
)


def perm_for(url_name):
    for section, words in SECTIONS:
        if any(word in url_name for word in words):
            return f"reports.{section}"
    return None


class SectionAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None or not match.url_name or match.namespace:
            return None
        perm = perm_for(match.url_name)
        if perm is None or not request.user.is_authenticated:
            return None
        if request.user.has_perm(perm):
            return None
        if match.url_name.startswith("api_"):
            return JsonResponse({"error": "нет доступа к разделу"}, status=403)
        return render(request, "access_denied.html", {"years": YEARS}, status=403)
