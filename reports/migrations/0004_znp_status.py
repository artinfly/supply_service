from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0003_sap_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="stagingznpexcel",
            name="znp_status",
            field=models.TextField(null=True),
        ),
        migrations.AddField(
            model_name="znpdata",
            name="znp_status",
            field=models.CharField(max_length=100, null=True),
        ),
    ]
