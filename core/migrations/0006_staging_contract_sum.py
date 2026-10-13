from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0005_contract_sum"),
    ]

    operations = [
        migrations.AddField(
            model_name="stagingexcel",
            name="summa_dogovora",
            field=models.TextField(null=True),
        ),
    ]
