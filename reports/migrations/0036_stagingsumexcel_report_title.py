from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0035_stagingsumexcel"),
    ]

    operations = [
        migrations.AddField(
            model_name="stagingsumexcel",
            name="report_title",
            field=models.TextField(
                blank=True,
                null=True,
                verbose_name="Заголовок исходного листа",
            ),
        ),
    ]
