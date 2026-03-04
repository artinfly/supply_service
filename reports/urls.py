from django.urls import path
from . import views

urlpatterns = [

    # ── Главная страница ──────────────────────────────────────────────
    path('', views.index, name='index'),

    # ── HTML страницы отчётов ─────────────────────────────────────────
    path('kdr/<str:year>/',            views.kdr_table,            name='kdr_table'),
    path('igk-concluded/<str:year>/',  views.igk_concluded_table,  name='igk_concluded_table'),
    path('igk-not-concluded/<str:year>/', views.igk_not_concluded_table, name='igk_not_concluded_table'),
    path('igk-terminated/<str:year>/', views.igk_terminated_table, name='igk_terminated_table'),
    path('day-stat-igk/',              views.day_stat_only_igk_table,  name='day_stat_only_igk_table'),
    path('day-stat-cfo/',              views.day_stat_with_cfo_table,  name='day_stat_with_cfo_table'),
    path('all-pps/',                   views.all_pps_table,         name='all_pps_table'),
    path('all-contracts/',             views.all_contracts_table,   name='all_contracts_table'),

    # ── API (возвращают JSON) ─────────────────────────────────────────
    path('api/kdr/<str:year>/',            views.api_kdr,            name='api_kdr'),
    path('api/igk-concluded/<str:year>/',  views.api_igk_concluded,  name='api_igk_concluded'),
    path('api/igk-not-concluded/<str:year>/', views.api_igk_not_concluded, name='api_igk_not_concluded'),
    path('api/igk-terminated/<str:year>/', views.api_igk_terminated, name='api_igk_terminated'),
    path('api/day-stat-igk/',              views.api_day_stat_igk,   name='api_day_stat_igk'),
    path('api/day-stat-cfo/',              views.api_day_stat_cfo,   name='api_day_stat_cfo'),
    path('api/all-pps/',                   views.api_all_pps,        name='api_all_pps'),
    path('api/all-contracts/',             views.api_all_contracts,  name='api_all_contracts'),
]