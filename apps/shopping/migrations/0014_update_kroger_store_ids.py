from django.db import migrations


KROGER_UPDATES = [
    {
        "address": "4600 Leetsdale Dr",
        "external_store_id": "62000124",
        "name": "King Soopers #62000124 (Leetsdale & Cherry / Glendale)",
    },
    {
        "address": "1950 Chestnut Pl",
        "external_store_id": "62000115",
        "name": "King Soopers #62000115 (Chestnut / LoDo)",
    },
    {
        "address": "1331 Speer Blvd",
        "external_store_id": "62000001",
        "name": "King Soopers #62000001 (Speer Blvd)",
    },
    {
        "address": "1155 E 9th Ave",
        "external_store_id": "62000029",
        "name": "King Soopers #62000029 (9th & Downing / Capitol Hill)",
    },
    {
        "address": "2810 Quebec St",
        "external_store_id": "62000042",
        "name": "King Soopers #62000042 (Central Park / Quebec)",
    },
    {
        "address": "7984 W Alameda Ave",
        "external_store_id": "62000055",
        "name": "King Soopers #62000055 (Belmar / Lakewood)",
    },
    {
        "address": "5301 W 38th Ave",
        "external_store_id": "62000078",
        "name": "King Soopers #62000078 (Wheat Ridge / 38th & Sheridan)",
    },
    {
        "address": "1725 Sheridan Blvd",
        "external_store_id": "62000090",
        "name": "King Soopers #62000090 (Edgewater / 20th & Depew)",
    },
]


def update_kroger_locations(apps, schema_editor):
    StoreLocation = apps.get_model("shopping", "StoreLocation")
    for update in KROGER_UPDATES:
        StoreLocation.objects.filter(address__iexact=update["address"]).update(
            external_store_id=update["external_store_id"],
            name=update["name"],
        )


def reverse_kroger_locations(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0013_cleanup_category_pseudo_aisles"),
    ]

    operations = [
        migrations.RunPython(update_kroger_locations, reverse_kroger_locations),
    ]
