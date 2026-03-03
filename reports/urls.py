from django.urls import path
from . import views

urlpatterns = [
    # API
    path('api/kdr2025/', views.kdr_stat_2025, name='kdr2025'),
    path('api/kdr2026/', views.kdr_stat_2026, name='kdr2026'),
    path('api/kdr2027/', views.kdr_stat_2027, name='kdr2027'),
    path('api/igk-concluded-2025/', views.igk_stat_concluded_2025, name='igk_concluded_2025'),
    path('api/igk-concluded-2026/', views.igk_stat_concluded_2026, name='igk_concluded_2026'),
    path('api/igk-concluded-2027/', views.igk_stat_concluded_2027, name='igk_concluded_2027'),
    path('api/igk-not-concluded-2025/', views.igk_stat_not_concluded_2025, name='igk_not_concluded_2025'),
    path('api/igk-not-concluded-2026/', views.igk_stat_not_concluded_2026, name='igk_not_concluded_2026'),
    path('api/igk-not-concluded-2027/', views.igk_stat_not_concluded_2027, name='igk_not_concluded_2027'),
    path('api/igk-terminated-2025/', views.igk_stat_terminated_2025, name='igk_terminated_2025'),
    path('api/igk-terminated-2026/', views.igk_stat_terminated_2026, name='igk_terminated_2026'),
    path('api/igk-terminated-2027/', views.igk_stat_terminated_2027, name='igk_terminated_2027'),
    path('api/day-stat-only-igk/', views.day_stat_only_igk, name='day_stat_only_igk'),
    path('api/day-stat-with-cfo/', views.day_stat_with_cfo, name='day_stat_with_cfo'),
    path('api/all-pps/', views.all_pps, name='all_pps'),
    path('api/all-contracts/', views.all_contracts, name='all_contracts'),

    # HTML страницы
    path('', views.index, name='index'),
    path('kdr2025/', views.kdr_table, {'year': '2025'}, name='kdr2025_table'),
    path('kdr2026/', views.kdr_table, {'year': '2026'}, name='kdr2026_table'),
    path('kdr2027/', views.kdr_table, {'year': '2027'}, name='kdr2027_table'),
    path('igk-concluded-2025/', views.igk_concluded_table, {'year': '2025'}, name='igk_concluded_2025_table'),
    path('igk-concluded-2026/', views.igk_concluded_table, {'year': '2026'}, name='igk_concluded_2026_table'),
    path('igk-concluded-2027/', views.igk_concluded_table, {'year': '2027'}, name='igk_concluded_2027_table'),
    path('igk-not-concluded-2025/', views.igk_not_concluded_table, {'year': '2025'}, name='igk_not_concluded_2025_table'),
    path('igk-not-concluded-2026/', views.igk_not_concluded_table, {'year': '2026'}, name='igk_not_concluded_2026_table'),
    path('igk-not-concluded-2027/', views.igk_not_concluded_table, {'year': '2027'}, name='igk_not_concluded_2027_table'),
    path('igk-terminated-2025/', views.igk_terminated_table, {'year': '2025'}, name='igk_terminated_2025_table'),
    path('igk-terminated-2026/', views.igk_terminated_table, {'year': '2026'}, name='igk_terminated_2026_table'),
    path('igk-terminated-2027/', views.igk_terminated_table, {'year': '2027'}, name='igk_terminated_2027_table'),
    path('day-stat-only-igk/', views.day_stat_only_igk_table, name='day_stat_only_igk_table'),
    path('day-stat-with-cfo/', views.day_stat_with_cfo_table, name='day_stat_with_cfo_table'),
    path('all-pps/', views.all_pps_table, name='all_pps_table'),
    path('all-contracts/', views.all_contracts_table, name='all_contracts_table'),
]