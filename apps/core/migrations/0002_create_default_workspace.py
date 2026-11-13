"""
Data migration to create default workspace and associate existing lists and plans.
"""

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations


def link_default_workspace(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Workspace = apps.get_model("core", "Workspace")
    ShoppingList = apps.get_model("shopping", "ShoppingList")
    MealPlan = apps.get_model("mealplans", "MealPlan")

    # Ensure an admin or primary user exists
    user = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if not user:
        user = User.objects.create(
            username="admin",
            password=make_password("admin123"),
            is_staff=True,
            is_superuser=True,
        )

    # Get or create primary workspace
    default_ws, _ = Workspace.objects.get_or_create(
        name="Home",
        defaults={"owner": user},
    )

    # Link existing lists
    ShoppingList.objects.filter(workspace__isnull=True).update(workspace=default_ws)

    # Ensure default meal plan exists for default workspace
    if not MealPlan.objects.filter(workspace=default_ws).exists():
        MealPlan.objects.create(
            name="Weekly Meal Plan",
            workspace=default_ws,
            owner=user,
        )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("shopping", "0007_shoppinglist_workspace_alter_shoppinglistitem_locked"),
        ("mealplans", "0002_mealplan_workspace"),
    ]

    operations = [
        migrations.RunPython(link_default_workspace, reverse_noop),
    ]
