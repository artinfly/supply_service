from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0002_performance_indexes_and_snapshot_key"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="znpdatasap",
            index=models.Index(fields=["cfo"], name="znp_data_sa_cfo_03ed7d_idx"),
        ),
        migrations.AddIndex(
            model_name="znpdatasap",
            index=models.Index(fields=["igk"], name="znp_data_sa_igk_d6552e_idx"),
        ),
    ]
