from django.db import migrations


def purge_empty_negative_aisles(apps, schema_editor):
    StoreItemAisle = apps.get_model("shopping", "StoreItemAisle")
    StoreItemAisle.objects.filter(aisle_name="").delete()
    StoreItemAisle.objects.filter(aisle_name__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0015_alter_shoppinglistitem_priority"),
    ]

    operations = [
        migrations.RunPython(purge_empty_negative_aisles, reverse_code=migrations.RunPython.noop),
    ]
