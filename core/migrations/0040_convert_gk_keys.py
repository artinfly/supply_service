import re

from django.db import migrations

_GK_RE = re.compile(r"(\d{4})(?!\d)\s*[/_\s\-]*\s*(\d+)\s*[сc]б", re.IGNORECASE)


def convert_keys(apps, schema_editor):
    """«6066 162сб» -> «6066/162сб». Если новый ключ уже занят — запись не трогаем."""
    Gk = apps.get_model("core", "GozContractVat")
    taken = set(Gk.objects.values_list("igk", flat=True))
    for rec in Gk.objects.all().order_by("id"):
        m = _GK_RE.search(rec.igk or "")
        if not m:
            continue
        key = f"{m.group(1)}/{m.group(2)}сб"
        if key == rec.igk or key in taken:
            continue
        taken.discard(rec.igk)
        taken.add(key)
        rec.igk = key
        rec.save(update_fields=["igk"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_gozcontractvat_contract_date_and_more"),
    ]

    operations = [
        migrations.RunPython(convert_keys, migrations.RunPython.noop),
    ]




