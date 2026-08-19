from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0013_delete_nsicfo_remove_igkstatdata_is_deleted"),
    ]

    operations = [
        CreateExtension("pgcrypto"),
    ]
