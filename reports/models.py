from django.db import models

class NsiCfo(models.Model):
    cfo_id = models.AutoField(primary_key=True)
    cfo = models.CharField(max_length=50, unique=True)

    class Meta:
        managed = False
        db_table = 'nsi_cfo'
        verbose_name = 'ЦФО'

    def __str__(self):
        return self.cfo

class NsiIgk(models.Model):
    igk_id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=50, unique=True)

    class Meta:
        managed = False
        db_table = 'nsi_igk'

    def __str__(self):
        return self.igk

class DayData(models.Model):
    id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=50)
    cfo = models.CharField(max_length=50, null=True, blank=True)
    orders_count = models.IntegerField(null=True, blank=True)
    orders_sum = models.FloatField(null=True, blank=True)
    concluded_orders_count = models.IntegerField(null=True, blank=True)
    concluded_orders_sum = models.FloatField(null=True, blank=True)
    upload_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'day_data'

    def __str__(self):
        return f"{self.igk} / {self.upload_date}"

class IgkStatData(models.Model):
    pp_id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=500, null=True, blank=True)
    c_agent = models.CharField(max_length=500, null=True, blank=True)
    cfo = models.CharField(max_length=500, null=True, blank=True)
    contract = models.CharField(max_length=500, null=True, blank=True)
    status = models.CharField(max_length=500, null=True, blank=True)
    payment_type = models.CharField(max_length=500, null=True, blank=True)
    item = models.CharField(max_length=500, null=True, blank=True)
    order = models.CharField(max_length=500, null=True, blank=True, db_column='order')
    plan = models.FloatField(null=True, blank=True)
    fact = models.FloatField(null=True, blank=True)
    tolerance = models.FloatField(null=True, blank=True)
    stage = models.CharField(max_length=250, null=True, blank=True)
    y25 = models.BooleanField(null=True, blank=True)
    y26 = models.BooleanField(null=True, blank=True)
    y27 = models.BooleanField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    plan_date = models.CharField(max_length=50, null=True, blank=True)
    c_date = models.CharField(max_length=256, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'igk_stat_data'

    def __str__(self):
        return f"{self.igk} / {self.contract}"

class OrdersQuantities(models.Model):
    id = models.AutoField(primary_key=True)
    igk = models.IntegerField()
    cfo = models.IntegerField(null=True, blank=True)
    quantity = models.IntegerField()
    upload_date = models.DateField()
    y25 = models.BooleanField(null=True, blank=True)
    y26 = models.BooleanField(null=True, blank=True)
    y27 = models.BooleanField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'orders_quantities'

class StagingExcel(models.Model):
    id = models.AutoField(primary_key=True)
    igk = models.TextField(null=True, blank=True)
    kontragent = models.TextField(null=True, blank=True)
    cfo = models.TextField(null=True, blank=True)
    dogovor = models.TextField(null=True, blank=True)
    sostoyanie = models.TextField(null=True, blank=True)
    etap_grafika = models.TextField(null=True, blank=True)
    tip_platezha = models.TextField(null=True, blank=True)
    tol = models.TextField(null=True, blank=True)
    predmet = models.TextField(null=True, blank=True)
    sozdan = models.TextField(null=True, blank=True)
    zakaz = models.TextField(null=True, blank=True)
    dataplan = models.TextField(null=True, blank=True)
    plan = models.TextField(null=True, blank=True)
    fakt = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'staging_excel'
