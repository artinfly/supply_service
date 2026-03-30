from django.urls import path
from . import views

urlpatterns = [
    path('',                                       views.index,                     name='index'),

    path('kdr/<str:year>/',                        views.kdr_table,                 name='kdr_table'),
    path('igk-concluded/<str:year>/',              views.igk_concluded_table,       name='igk_concluded_table'),
    path('igk-not-concluded/<str:year>/',          views.igk_not_concluded_table,   name='igk_not_concluded_table'),
    path('igk-terminated/<str:year>/',             views.igk_terminated_table,      name='igk_terminated_table'),
    path('all-contracts/',                         views.all_contracts_table,       name='all_contracts_table'),
    path('history-status/',                        views.history_status_table,      name='history_status_table'),
    path('history-plan/',                          views.history_plan_table,        name='history_plan_table'),
    path('history-fact/',                          views.history_fact_table,        name='history_fact_table'),
    path('contract-dupes/',                        views.contract_dupes_table,      name='contract_dupes_table'),
    path('upload/',                                views.upload_excel,              name='upload_excel'),
    path('export/',                                views.export_page,               name='export_page'),
    path('export/advances/<str:year>/',            views.export_advances,           name='export_advances'),
    path('export/kdr/<str:year>/',                 views.export_kdr,                name='export_kdr'),
    path('export/contracts/<str:year>/',           views.export_contracts_by_agent, name='export_contracts_by_agent'),
    path('export/history-status/',                 views.export_history_status,     name='export_history_status'),
    path('export/history-plan/',                   views.export_history_plan,       name='export_history_plan'),
    path('export/history-fact/',                   views.export_history_fact,       name='export_history_fact'),
    path('export/contract-dupes/',                 views.export_contract_dupes,     name='export_contract_dupes'),

    path('api/kdr/<str:year>/',                    views.api_kdr,                   name='api_kdr'),
    path('api/igk-concluded/<str:year>/',          views.api_igk_concluded,         name='api_igk_concluded'),
    path('api/igk-not-concluded/<str:year>/',      views.api_igk_not_concluded,     name='api_igk_not_concluded'),
    path('api/igk-terminated/<str:year>/',         views.api_igk_terminated,        name='api_igk_terminated'),
    path('api/contracts-by-agent/',                views.api_contracts_by_agent,    name='api_contracts_by_agent'),
    path('api/all-contracts/',                     views.api_all_contracts,         name='api_all_contracts'),
    path('api/history-status/',                    views.api_history_status,        name='api_history_status'),
    path('api/history-plan/',                      views.api_history_plan,          name='api_history_plan'),
    path('api/history-fact/',                      views.api_history_fact,          name='api_history_fact'),
    path('api/contract-dupes/',                    views.api_contract_dupes,        name='api_contract_dupes'),
    path('api/igk-detail/<str:year>/<str:igk>/',   views.api_igk_detail,            name='api_igk_detail'),
]