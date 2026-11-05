"""
Data migration to backfill openly licensed Wikimedia Commons photos and CC attributions
for recipes that previously lacked photography.
"""

from django.db import migrations

LICENSED_RECIPE_PHOTOS = {
    "Bellringer's Reward (Roast Roots and Baked Spuds)": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b4/Neon_root_veggies_%28roasted_beets%2C_turnips%2C_rutabaga%2C_carrots_and_onions%29_%286893015819%29.jpg/1280px-Neon_root_veggies_%28roasted_beets%2C_turnips%2C_rutabaga%2C_carrots_and_onions%29_%286893015819%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Neon root veggies (roasted beets, turnips, rutabaga, carrots and onions) (6893015819).jpg by Gloria Cabada-Leman, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:Neon_root_veggies_(roasted_beets,_turnips,_rutabaga,_carrots_and_onions)_(6893015819).jpg",
    },
    "Charoset": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/ce/Charoset%26ingredients.jpg/1280px-Charoset%26ingredients.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Charoset&ingredients.jpg by Yoninah, licensed under CC BY 2.5. Source: https://commons.wikimedia.org/wiki/File:Charoset%26ingredients.jpg",
    },
    "Chile Rellenos": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/c9/Algunos_Chiles_rellenos.jpg/1280px-Algunos_Chiles_rellenos.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Algunos Chiles rellenos.jpg by Koffermejia, licensed under CC BY-SA 4.0. Source: https://commons.wikimedia.org/wiki/File:Algunos_Chiles_rellenos.jpg",
    },
    "Green Bean Casserole": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/65/Green_Bean_Casserole_Pie_%2825619788693%29.jpg/1280px-Green_Bean_Casserole_Pie_%2825619788693%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Green Bean Casserole Pie (25619788693).jpg by Stephanie Clifford from Arlington, VA, USA, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:Green_Bean_Casserole_Pie_(25619788693).jpg",
    },
    "Lomo Saltado": {
        "photo_url": "https://upload.wikimedia.org/wikipedia/commons/c/ca/Lomo-saltado-perudelights.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled",
        "attribution": "Photo: File:Lomo-saltado-perudelights.jpg by WikiHes, licensed under CC BY-SA 4.0. Source: https://commons.wikimedia.org/wiki/File:Lomo-saltado-perudelights.jpg",
    },
    "Matzo ball soup": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/18/A_cup_of_matzoh_ball_soup._New_York%2C_NY._%2838787361302%29.jpg/1280px-A_cup_of_matzoh_ball_soup._New_York%2C_NY._%2838787361302%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:A cup of matzoh ball soup. New York, NY. (38787361302).jpg by Kathy Drasky from San Francisco, United States, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:A_cup_of_matzoh_ball_soup._New_York,_NY._(38787361302).jpg",
    },
    "Peruvian garlic rice": {
        "photo_url": "https://upload.wikimedia.org/wikipedia/commons/3/33/Chanfainita-palto_t%C3%ADpico_peruano.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled",
        "attribution": "Photo: File:Chanfainita-palto típico peruano.jpg by Unknown, licensed under CC BY-SA 3.0. Source: https://commons.wikimedia.org/wiki/File:Chanfainita-palto_t%C3%ADpico_peruano.jpg",
    },
    "Seder plate": {
        "photo_url": "https://upload.wikimedia.org/wikipedia/commons/a/ad/Passover_Seder_Plate.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled",
        "attribution": "Photo: File:Passover Seder Plate.jpg by Unknown, licensed under CC BY-SA 3.0. Source: https://commons.wikimedia.org/wiki/File:Passover_Seder_Plate.jpg",
    },
    "Spinach Lasagna": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5b/Spinach_lasagna_%2842460175134%29.jpg/1280px-Spinach_lasagna_%2842460175134%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Spinach lasagna (42460175134).jpg by Joey Doll, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:Spinach_lasagna_(42460175134).jpg",
    },
    "Star crossed garlic parsley baked potatoes": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/00/An_ovenfull_%28295711235%29.jpg/1280px-An_ovenfull_%28295711235%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:An ovenfull (295711235).jpg by Andy / Andrew Fogg from near Cambridge, UK, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:An_ovenfull_(295711235).jpg",
    },
    "Vegetarian Borscht": {
        "photo_url": "https://upload.wikimedia.org/wikipedia/commons/5/50/Borscht.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled",
        "attribution": "Photo: File:Borscht.jpg by Karmosin, licensed under CC BY-SA 3.0. Source: https://commons.wikimedia.org/wiki/File:Borscht.jpg",
    },
    "Warm seasoned soba noodles": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/d7/Soba_in_Torrance%2C_CA_by_LWY.jpg/1280px-Soba_in_Torrance%2C_CA_by_LWY.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Soba in Torrance, CA by LWY.jpg by LWY from Torrance, California, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:Soba_in_Torrance,_CA_by_LWY.jpg",
    },
    "White chocolate cake": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/96/A_slice_of_white_chocolate_cake%2C_January_2009.jpg/1280px-A_slice_of_white_chocolate_cake%2C_January_2009.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:A slice of white chocolate cake, January 2009.jpg by boo lee, licensed under CC BY 2.0. Source: https://commons.wikimedia.org/wiki/File:A_slice_of_white_chocolate_cake,_January_2009.jpg",
    },
    "pork chops": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Apple_sauce_pork_chops1.jpg/1280px-Apple_sauce_pork_chops1.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Apple sauce pork chops1.jpg, licensed under CC BY-SA 4.0. Source: https://commons.wikimedia.org/wiki/File:Apple_sauce_pork_chops1.jpg",
    },
    "tomato cucumber and onion salad": {
        "photo_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e7/Cattlemens_Petaluma_-_June_2022_-_Sarah_Stierch_07.jpg/1280px-Cattlemens_Petaluma_-_June_2022_-_Sarah_Stierch_07.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "attribution": "Photo: File:Cattlemens Petaluma - June 2022 - Sarah Stierch 07.jpg by Missvain, licensed under CC BY 4.0. Source: https://commons.wikimedia.org/wiki/File:Cattlemens_Petaluma_-_June_2022_-_Sarah_Stierch_07.jpg",
    },
}


def link_licensed_photos(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    for name, data in LICENSED_RECIPE_PHOTOS.items():
        recipe = Recipe.objects.filter(name=name).first()
        if not recipe:
            continue

        # Set external photo URL
        recipe.photo_urls = [data["photo_url"]]

        # Append attribution to bibliography if not already present
        bib = list(recipe.bibliography or [])
        attribution = data["attribution"]
        if not any("Photo:" in str(entry) for entry in bib):
            bib.append(attribution)
            recipe.bibliography = bib

        recipe.save(update_fields=["photo_urls", "bibliography"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0008_recipe_is_web_imported_and_copyright_cleared"),
    ]

    operations = [
        migrations.RunPython(link_licensed_photos, migrations.RunPython.noop),
    ]
