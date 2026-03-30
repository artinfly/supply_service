from django.contrib import admin
from .models import IgkStatData, NsiCfo, NsiIgk, StagingExcel

admin.site.register(IgkStatData)
admin.site.register(NsiCfo)
admin.site.register(NsiIgk)
admin.site.register(StagingExcel)