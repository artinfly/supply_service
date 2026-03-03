from django.contrib import admin
from .models import IgkStatData, NsiCfo, NsiIgk, DayData, OrdersQuantities, Users, StagingExcel

admin.site.register(IgkStatData)
admin.site.register(NsiCfo)
admin.site.register(NsiIgk)
admin.site.register(DayData)
admin.site.register(OrdersQuantities)
admin.site.register(Users)
admin.site.register(StagingExcel)