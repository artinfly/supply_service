from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0006_staging_contract_sum"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="stagingexcel",
            name="sozdan",
        ),
    ]
