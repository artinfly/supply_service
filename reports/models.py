from django.db import models


class NsiCfo(models.Model):
    cfo_id = models.AutoField(primary_key=True)
    cfo    = models.CharField(max_length=50, unique=True)

    class Meta:
        managed      = False
        db_table     = 'nsi_cfo'
        verbose_name = 'ЦФО'

    def __str__(self):
        return self.cfo


class NsiIgk(models.Model):
    igk_id = models.AutoField(primary_key=True)
    igk    = models.CharField(max_length=50, unique=True)

    class Meta:
        managed      = False
        db_table     = 'nsi_igk'
        verbose_name = 'ИГК'

    def __str__(self):
        return self.igk


class IgkStatData(models.Model):
    pp_id        = models.AutoField(primary_key=True)
    igk          = models.CharField(max_length=500, null=True)
    c_agent      = models.CharField(max_length=500, null=True)
    cfo          = models.CharField(max_length=500, null=True)
    contract     = models.CharField(max_length=500, null=True)
    status       = models.CharField(max_length=500, null=True)
    payment_type = models.CharField(max_length=500, null=True)
    item         = models.CharField(max_length=500, null=True)
    order        = models.CharField(max_length=500, null=True, db_column='order')
    plan         = models.FloatField(null=True)
    fact         = models.FloatField(null=True)
    tolerance    = models.FloatField(null=True)
    stage        = models.CharField(max_length=250, null=True)
    y25          = models.BooleanField(null=True)
    y26          = models.BooleanField(null=True)
    y27          = models.BooleanField(null=True)
    is_deleted   = models.BooleanField(default=False)
    plan_date    = models.CharField(max_length=50, null=True)
    c_date       = models.CharField(max_length=256, null=True)

    class Meta:
        managed      = False
        db_table     = 'igk_stat_data'
        verbose_name = 'Позиция договора'

    def __str__(self):
        return f'{self.igk} / {self.contract}'


class StagingExcel(models.Model):
    id           = models.AutoField(primary_key=True)
    igk          = models.TextField(null=True)
    kontragent   = models.TextField(null=True)
    cfo          = models.TextField(null=True)
    dogovor      = models.TextField(null=True)
    sostoyanie   = models.TextField(null=True)
    tip_platezha = models.TextField(null=True)
    predmet      = models.TextField(null=True)
    zakaz        = models.TextField(null=True)
    plan         = models.TextField(null=True)
    fakt         = models.TextField(null=True)
    tol          = models.TextField(null=True)
    etap_grafika = models.TextField(null=True)
    dataplan     = models.TextField(null=True)
    sozdan       = models.TextField(null=True)

    class Meta:
        managed      = False
        db_table     = 'staging_excel'
        verbose_name = 'Строка импорта'

    def __str__(self):
        return f'{self.igk} / {self.dogovor}'