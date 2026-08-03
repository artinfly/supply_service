from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0004_znp_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="contractshistory",
            name="new_contract_sum",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="contractshistory",
            name="old_contract_sum",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="igkstatdata",
            name="contract_sum",
            field=models.FloatField(null=True),
        ),
    ]
