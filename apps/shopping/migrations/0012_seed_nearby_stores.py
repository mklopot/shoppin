"""
Data migration to seed major supermarket locations in Denver / Colorado metro area.
Provides realistic, high-accuracy store coordinates for Whole Foods, King Soopers, Safeway,
Trader Joe's, and Sprouts so that geolocation 'Near Me' lookups return the actual closest stores.
"""

from django.db import migrations

STORES_DATA = [
    # Whole Foods Markets
    {
        "name": "Whole Foods Market (Union Station)",
        "chain": "whole_foods",
        "external_store_id": "WFM-DEN-US",
        "address": "1701 Wewatta St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80202",
        "latitude": 39.7533,
        "longitude": -105.0002,
    },
    {
        "name": "Whole Foods Market (Cherry Creek)",
        "chain": "whole_foods",
        "external_store_id": "WFM-CC",
        "address": "2375 E 1st Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80206",
        "latitude": 39.7196,
        "longitude": -104.9535,
    },
    {
        "name": "Whole Foods Market (Governor's Park / Cap Hill)",
        "chain": "whole_foods",
        "external_store_id": "WFM-GP",
        "address": "900 E 11th Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80218",
        "latitude": 39.7335,
        "longitude": -104.9750,
    },
    {
        "name": "Whole Foods Market (Colfax / Lakewood)",
        "chain": "whole_foods",
        "external_store_id": "WFM-LKWD",
        "address": "14357 W Colfax Ave",
        "city": "Lakewood",
        "state": "CO",
        "zip_code": "80401",
        "latitude": 39.7350,
        "longitude": -105.1580,
    },
    {
        "name": "Whole Foods Market (Southglenn)",
        "chain": "whole_foods",
        "external_store_id": "WFM-SGLN",
        "address": "6853 S York St",
        "city": "Centennial",
        "state": "CO",
        "zip_code": "80122",
        "latitude": 39.5930,
        "longitude": -104.9600,
    },
    {
        "name": "Whole Foods Market (Boulder - Pearl St)",
        "chain": "whole_foods",
        "external_store_id": "WFM-BLDR",
        "address": "2905 Pearl St",
        "city": "Boulder",
        "state": "CO",
        "zip_code": "80301",
        "latitude": 40.0210,
        "longitude": -105.2570,
    },

    # King Soopers (Kroger)
    {
        "name": "King Soopers #01400115 (Chestnut / LoDo)",
        "chain": "kroger",
        "external_store_id": "01400115",
        "address": "1950 Chestnut Pl",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80202",
        "latitude": 39.7554,
        "longitude": -104.9984,
    },
    {
        "name": "King Soopers #01400035 (Speer Blvd)",
        "chain": "kroger",
        "external_store_id": "01400035",
        "address": "1331 Speer Blvd",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80204",
        "latitude": 39.7289,
        "longitude": -104.9814,
    },
    {
        "name": "King Soopers #01400029 (9th & Downing / Capitol Hill)",
        "chain": "kroger",
        "external_store_id": "01400029",
        "address": "1155 E 9th Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80218",
        "latitude": 39.7310,
        "longitude": -104.9725,
    },
    {
        "name": "King Soopers #01400018 (Leetsdale & Cherry / Glendale)",
        "chain": "kroger",
        "external_store_id": "01400018",
        "address": "4600 Leetsdale Dr",
        "city": "Glendale",
        "state": "CO",
        "zip_code": "80246",
        "latitude": 39.7047,
        "longitude": -104.9332,
    },
    {
        "name": "King Soopers #01400042 (Central Park / Quebec)",
        "chain": "kroger",
        "external_store_id": "01400042",
        "address": "2810 Quebec St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80207",
        "latitude": 39.7565,
        "longitude": -104.9014,
    },
    {
        "name": "King Soopers #01400012 (Edgewater / 20th & Depew)",
        "chain": "kroger",
        "external_store_id": "01400012",
        "address": "1725 Sheridan Blvd",
        "city": "Edgewater",
        "state": "CO",
        "zip_code": "80214",
        "latitude": 39.7440,
        "longitude": -105.0530,
    },
    {
        "name": "King Soopers #01400078 (Wheat Ridge / 38th & Sheridan)",
        "chain": "kroger",
        "external_store_id": "01400078",
        "address": "5301 W 38th Ave",
        "city": "Wheat Ridge",
        "state": "CO",
        "zip_code": "80033",
        "latitude": 39.7690,
        "longitude": -105.0550,
    },
    {
        "name": "King Soopers #01400055 (Belmar / Lakewood)",
        "chain": "kroger",
        "external_store_id": "01400055",
        "address": "7984 W Alameda Ave",
        "city": "Lakewood",
        "state": "CO",
        "zip_code": "80226",
        "latitude": 39.7110,
        "longitude": -105.0860,
    },

    # Safeway
    {
        "name": "Safeway #1466 (Corona St)",
        "chain": "safeway",
        "external_store_id": "1466",
        "address": "560 Corona St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80218",
        "latitude": 39.7259,
        "longitude": -104.9733,
    },
    {
        "name": "Safeway #0878 (20th & Clarkson / Five Points)",
        "chain": "safeway",
        "external_store_id": "0878",
        "address": "2150 E 20th Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80205",
        "latitude": 39.7471,
        "longitude": -104.9620,
    },
    {
        "name": "Safeway #1479 (Federal Blvd & 26th)",
        "chain": "safeway",
        "external_store_id": "1479",
        "address": "2660 Federal Blvd",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80211",
        "latitude": 39.7550,
        "longitude": -105.0250,
    },
    {
        "name": "Safeway #1659 (Highlands / 38th & Tennyson)",
        "chain": "safeway",
        "external_store_id": "1659",
        "address": "3800 Tennyson St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80212",
        "latitude": 39.7695,
        "longitude": -105.0440,
    },
    {
        "name": "Safeway #2714 (Park Hill / 14th & Krameria)",
        "chain": "safeway",
        "external_store_id": "2714",
        "address": "6220 E 14th Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80220",
        "latitude": 39.7372,
        "longitude": -104.9156,
    },
    {
        "name": "Safeway #0384 (Evans & Monaco)",
        "chain": "safeway",
        "external_store_id": "0384",
        "address": "6360 E Evans Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80222",
        "latitude": 39.6785,
        "longitude": -104.9130,
    },

    # Trader Joe's & Sprouts & Natural Grocers
    {
        "name": "Trader Joe's (Logan St / Cap Hill)",
        "chain": "trader_joes",
        "external_store_id": "TJ-DEN-LOGAN",
        "address": "750 Logan St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80203",
        "latitude": 39.7282,
        "longitude": -104.9824,
    },
    {
        "name": "Trader Joe's (8th & Colorado)",
        "chain": "trader_joes",
        "external_store_id": "TJ-DEN-COLO",
        "address": "790 N Colorado Blvd",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80206",
        "latitude": 39.7288,
        "longitude": -104.9403,
    },
    {
        "name": "Sprouts Farmers Market (Colfax & Garfield)",
        "chain": "sprouts",
        "external_store_id": "SPR-COLFAX",
        "address": "2880 E Colfax Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80206",
        "latitude": 39.7401,
        "longitude": -104.9534,
    },
    {
        "name": "Sprouts Farmers Market (Highlands / 38th & Wolff)",
        "chain": "sprouts",
        "external_store_id": "SPR-38TH",
        "address": "3625 W 38th Ave",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80211",
        "latitude": 39.7693,
        "longitude": -105.0354,
    },
    {
        "name": "Natural Grocers (Colfax & Washington)",
        "chain": "other",
        "external_store_id": "NG-WASH",
        "address": "1433 Washington St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80203",
        "latitude": 39.7391,
        "longitude": -104.9785,
    },
    {
        "name": "Target Grocery (Downtown Denver / 16th St Mall)",
        "chain": "target",
        "external_store_id": "TGT-16TH",
        "address": "1600 California St",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80202",
        "latitude": 39.7454,
        "longitude": -104.9926,
    },
]


def seed_stores(apps, schema_editor):
    StoreLocation = apps.get_model("shopping", "StoreLocation")
    for s_data in STORES_DATA:
        ext_id = s_data.get("external_store_id")
        addr = s_data.get("address")
        existing = None
        if ext_id:
            existing = StoreLocation.objects.filter(external_store_id=ext_id).first()
        if not existing and addr:
            existing = StoreLocation.objects.filter(address__iexact=addr).first()
        if not existing:
            existing = StoreLocation.objects.filter(name__iexact=s_data["name"]).first()

        if existing:
            for k, v in s_data.items():
                setattr(existing, k, v)
            existing.save()
        else:
            StoreLocation.objects.create(**s_data)


def unseed_stores(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0011_shoppinglistitem_priority"),
    ]

    operations = [
        migrations.RunPython(seed_stores, reverse_code=unseed_stores),
    ]
