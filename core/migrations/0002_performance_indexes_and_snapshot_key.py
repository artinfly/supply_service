from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="stagingznpexcel",
            options={
                "managed": True,
                "verbose_name": "Строка импорта ЗнП",
                "verbose_name_plural": "Строки импорта ЗнП",
            },
        ),
        migrations.AlterModelOptions(
            name="znpdata",
            options={
                "managed": True,
                "verbose_name": "Заявка на платёж",
                "verbose_name_plural": "Заявки на платёж",
            },
        ),
        migrations.AlterModelOptions(
            name="znpdatasap",
            options={
                "managed": True,
                "verbose_name": "Заявка на платёж(САП)",
                "verbose_name_plural": "Заявки на платёж(САП)",
            },
        ),
        migrations.AlterField(
            model_name="contractcountssnapshot",
            name="cfo",
            field=models.CharField(max_length=500),
        ),
        migrations.AddIndex(
            model_name="contractshistory",
            index=models.Index(fields=["hash"], name="contracts_h_hash_23adb6_idx"),
        ),
        migrations.AddIndex(
            model_name="igkstatdata",
            index=models.Index(
                fields=["crc32_hash"], name="igk_stat_da_crc32_h_1965c4_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="igkstatdata",
            index=models.Index(fields=["igk"], name="igk_stat_da_igk_46cfe1_idx"),
        ),
        migrations.AddIndex(
            model_name="igkstatdata",
            index=models.Index(fields=["cfo"], name="igk_stat_da_cfo_2cf4c7_idx"),
        ),
        migrations.AddIndex(
            model_name="igkstatdata",
            index=models.Index(fields=["status"], name="igk_stat_da_status_99097f_idx"),
        ),
        migrations.AddIndex(
            model_name="igkstatdata",
            index=models.Index(
                fields=["payment_type"], name="igk_stat_da_payment_441c09_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="znpdata",
            index=models.Index(
                fields=["crc32_hash"], name="znp_data_crc32_h_2b86ce_idx"
            ),
        ),
        migrations.RunSQL(
            sql="""
                DELETE FROM contract_counts_snapshot a
                USING contract_counts_snapshot b
                WHERE a.id < b.id
                  AND a.upload_date = b.upload_date
                  AND a.igk = b.igk
                  AND a.cfo = b.cfo
                  AND a.year_col = b.year_col
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name="contractcountssnapshot",
            constraint=models.UniqueConstraint(
                fields=("upload_date", "igk", "cfo", "year_col"),
                name="contract_counts_snapshot_unique_key",
            ),
        ),
    ]
