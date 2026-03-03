from django.db import models

class NsiCfo(models.Model):
    cfo_id = models.AutoField(primary_key=True)
    cfo = models.CharField(max_length=50)

    class Meta:
        managed = False
        db_table = '"dbo"."nsi_cfo"'

class NsiIgk(models.Model):
    igk_id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=50)

    class Meta:
        managed = False
        db_table = '"dbo"."nsi_igk"'

class Users(models.Model):
    uid = models.AutoField(primary_key=True)
    username = models.CharField(max_length=16)
    password = models.CharField(max_length=256)
    full_name = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"dbo"."users"'

class DayData(models.Model):
    id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=50)
    cfo = models.CharField(max_length=50, blank=True, null=True)
    orders_count = models.IntegerField(blank=True, null=True)
    orders_sum = models.FloatField(blank=True, null=True)
    concluded_orders_count = models.IntegerField(blank=True, null=True)
    concluded_orders_sum = models.FloatField(blank=True, null=True)
    upload_date = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"dbo"."day_data"'

class IgkStatData(models.Model):
    pp_id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=500, blank=True, null=True)
    c_agent = models.CharField(max_length=500, blank=True, null=True)
    cfo = models.CharField(max_length=500, blank=True, null=True)
    contract = models.CharField(max_length=500, blank=True, null=True)
    status = models.CharField(max_length=500, blank=True, null=True)
    payment_type = models.CharField(max_length=500, blank=True, null=True)
    item = models.CharField(max_length=500, blank=True, null=True)
    order = models.CharField(max_length=500, blank=True, null=True)
    plan = models.FloatField(blank=True, null=True)
    fact = models.FloatField(blank=True, null=True)
    tolerance = models.FloatField(blank=True, null=True)
    stage = models.CharField(max_length=250, blank=True, null=True)
    y25 = models.BooleanField(blank=True, null=True)
    y26 = models.BooleanField(blank=True, null=True)
    y27 = models.BooleanField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False)
    plan_date = models.CharField(max_length=50, blank=True, null=True)
    c_date = models.CharField(max_length=256, blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"dbo"."igk_stat_data"'

class OrdersQuantities(models.Model):
    id = models.AutoField(primary_key=True)
    igk = models.IntegerField()
    cfo = models.IntegerField(blank=True, null=True)
    quantity = models.IntegerField()
    upload_date = models.DateField()
    y25 = models.BooleanField(blank=True, null=True)
    y26 = models.BooleanField(blank=True, null=True)
    y27 = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"dbo"."orders_quantities"'

class StagingExcel(models.Model):
    id = models.AutoField(primary_key=True)
    igk = models.CharField(max_length=50, blank=True, null=True)
    kontragent = models.CharField(max_length=500, blank=True, null=True)
    kontragent_star = models.CharField(max_length=500, blank=True, null=True)
    inn_kontragenta = models.CharField(max_length=50, blank=True, null=True)
    cfo = models.CharField(max_length=50, blank=True, null=True)
    dogovor = models.CharField(max_length=500, blank=True, null=True)
    ssylka = models.CharField(max_length=500, blank=True, null=True)
    sostoyanie = models.CharField(max_length=100, blank=True, null=True)
    etap_grafika = models.CharField(max_length=500, blank=True, null=True)
    tip_platezha = models.CharField(max_length=100, blank=True, null=True)
    srok = models.CharField(max_length=50, blank=True, null=True)
    podpisan = models.CharField(max_length=50, blank=True, null=True)
    kod_stati_byudzheta = models.CharField(max_length=50, blank=True, null=True)
    tol = models.CharField(max_length=50, blank=True, null=True)
    predmet = models.CharField(max_length=500, blank=True, null=True)
    schetorg = models.CharField(max_length=100, blank=True, null=True)
    schetkontr = models.CharField(max_length=100, blank=True, null=True)
    punktep = models.CharField(max_length=100, blank=True, null=True)
    datapodp = models.CharField(max_length=50, blank=True, null=True)
    sozdan = models.CharField(max_length=50, blank=True, null=True)
    dataplanpodp = models.CharField(max_length=50, blank=True, null=True)
    obekt_raschetov = models.CharField(max_length=500, blank=True, null=True)
    zakaz = models.CharField(max_length=100, blank=True, null=True)
    summa_dogovora = models.CharField(max_length=50, blank=True, null=True)
    zerk = models.CharField(max_length=50, blank=True, null=True)
    dataplan = models.CharField(max_length=50, blank=True, null=True)
    plan = models.CharField(max_length=50, blank=True, null=True)
    procent = models.CharField(max_length=50, blank=True, null=True)
    fakt = models.CharField(max_length=50, blank=True, null=True)
    procent_d = models.CharField(max_length=50, blank=True, null=True)
    procent_e = models.CharField(max_length=50, blank=True, null=True)
    ostatok = models.CharField(max_length=50, blank=True, null=True)
    procent_e1 = models.CharField(max_length=50, blank=True, null=True)
    ostatokmaks = models.CharField(max_length=50, blank=True, null=True)
    planetisp = models.CharField(max_length=50, blank=True, null=True)
    ispolneno = models.CharField(max_length=50, blank=True, null=True)
    pervdata = models.CharField(max_length=50, blank=True, null=True)
    posldata = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"dbo"."staging_excel"'