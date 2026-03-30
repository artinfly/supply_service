from django.contrib import admin
from django.urls import path, include
from reports import views as report_views

urlpatterns = [
    path('admin/',    admin.site.urls),
    path('',          report_views.index,       name='root'),
    path('login/',    report_views.login_view,  name='login'),
    path('logout/',   report_views.logout_view, name='logout'),
    path('reports/',  include('reports.urls')),
]