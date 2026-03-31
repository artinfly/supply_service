from django.urls import path

from .views import pages, api, exports

urlpatterns = [
    path('',                                       pages.index,                     name='root'),
    path('login/',                                 pages.login_view,                name='login'),
    path('logout/',                                pages.logout_view,               name='logout'),

    path('kdr/<str:year>/',                        pages.kdr_table,                 name='kdr_table'),
    path('igk-concluded/<str:year>/',              pages.igk_concluded_table,       name='igk_concluded_table'),
    path('igk-not-concluded/<str:year>/',          pages.igk_not_concluded_table,   name='igk_not_concluded_table'),
    path('igk-terminated/<str:year>/',             pages.igk_terminated_table,      name='igk_terminated_table'),
    path('all-contracts/',                         pages.all_contracts_table,       name='all_contracts_table'),
    path('history-status/',                        pages.history_status_table,      name='history_status_table'),
    path('history-plan/',                          pages.history_plan_table,        name='history_plan_table'),
    path('history-fact/',                          pages.history_fact_table,        name='history_fact_table'),
    path('contract-dupes/',                        pages.contract_dupes_table,      name='contract_dupes_table'),
    path('upload/',                                pages.upload_excel,              name='upload_excel'),
    path('export/',                                pages.export_page,               name='export_page'),

    path('export/advances/<str:year>/',            exports.export_advances,         name='export_advances'),
    path('export/kdr/<str:year>/',                 exports.export_kdr,              name='export_kdr'),
    path('export/contracts/<str:year>/',           exports.export_contracts_by_agent, name='export_contracts_by_agent'),
    path('export/history-status/',                 exports.export_history_status,   name='export_history_status'),
    path('export/history-plan/',                   exports.export_history_plan,     name='export_history_plan'),
    path('export/history-fact/',                   exports.export_history_fact,     name='export_history_fact'),
    path('export/contract-dupes/',                 exports.export_contract_dupes,   name='export_contract_dupes'),

    path('api/kdr/<str:year>/',                    api.api_kdr,                     name='api_kdr'),
    path('api/igk-concluded/<str:year>/',          api.api_igk_concluded,           name='api_igk_concluded'),
    path('api/igk-not-concluded/<str:year>/',      api.api_igk_not_concluded,       name='api_igk_not_concluded'),
    path('api/igk-terminated/<str:year>/',         api.api_igk_terminated,          name='api_igk_terminated'),
    path('api/contracts-by-agent/',                api.api_contracts_by_agent,      name='api_contracts_by_agent'),
    path('api/all-contracts/',                     api.api_all_contracts,           name='api_all_contracts'),
    path('api/history-status/',                    api.api_history_status,          name='api_history_status'),
    path('api/history-plan/',                      api.api_history_plan,            name='api_history_plan'),
    path('api/history-fact/',                      api.api_history_fact,            name='api_history_fact'),
    path('api/contract-dupes/',                    api.api_contract_dupes,          name='api_contract_dupes'),
    path('api/igk-detail/<str:year>/<str:igk>/',   api.api_igk_detail,              name='api_igk_detail'),
]