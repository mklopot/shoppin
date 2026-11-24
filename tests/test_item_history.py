"""
Tests for ShoppingListItem audit trail logging, merge preservation, recipe/list/meal links,
and the collapsed-by-default Advanced history section in item edit modals.
"""

import re
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import MealDish, MealPlan
from apps.mealplans.services.mealplan_service import (
    add_meal_to_plan,
    add_recipe_to_meal,
    scale_meal_dish,
)
from apps.recipes.models import Ingredient, Recipe
from apps.shopping.models import (
    ItemHistoryAction,
    ItemStatus,
    ShoppingList,
    ShoppingListItem,
    ShoppingListItemHistory,
)
from apps.shopping.services.preset_service import (
    add_preset_item,
    create_preset_list,
    load_preset_items_to_shopping_list,
    unload_preset_from_shopping_list,
)

User = get_user_model()


@pytest.fixture
def history_setup(db):
    """Provide shared workspace, two named collaborators, and primary shopping list."""
    owner = User.objects.create_user(username="maya_user", first_name="Maya", password="password")
    editor = User.objects.create_user(username="liam_user", first_name="Liam", password="password")
    ws = create_workspace("Family Kitchen", owner)
    share_workspace(ws, editor, WorkspaceRole.EDITOR)
    shopping_list = ws.get_primary_list()
    if not shopping_list:
        shopping_list = ShoppingList.objects.create(
            name="Main Shopping List",
            workspace=ws,
            owner=owner,
            is_preset=False,
        )
    return {
        "owner": owner,
        "editor": editor,
        "workspace": ws,
        "shopping_list": shopping_list,
    }


def _login_as(client, user, workspace_id: int) -> None:
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace_id
    session.save()


@pytest.mark.django_db
def test_manual_item_lifecycle_history_and_collapsed_advanced_modal(client, history_setup):
    """All manual item mutations log timestamped actor history rendered inside collapsed Advanced <details>."""
    owner = history_setup["owner"]
    editor = history_setup["editor"]
    ws = history_setup["workspace"]
    shopping_list = history_setup["shopping_list"]

    # 1. Owner adds item
    _login_as(client, owner, ws.id)
    resp_add = client.post(
        reverse("shopping:add_item"),
        {"name": "Avocados", "amount": "2", "purpose": "Tacos"},
    )
    assert resp_add.status_code == 200
    item = shopping_list.items.get(name="Avocados")

    # 2. Editor combines more, toggles priority, toggles lock, and checks status
    _login_as(client, editor, ws.id)
    client.post(
        reverse("shopping:add_item"),
        {"name": "Avocados", "amount": "1", "purpose": "Salad"},
    )
    client.post(reverse("shopping:toggle_priority", args=[item.id]))
    client.post(reverse("shopping:toggle_lock", args=[item.id]))

    # 3. Owner edits item fields
    _login_as(client, owner, ws.id)
    client.post(
        reverse("shopping:edit_item", args=[item.id]),
        {
            "name": "Avocados",
            "amount": "4",
            "category": "produce",
            "aisle": "Produce",
            "brand": "Organic",
            "vendor": "",
            "purpose": "Tacos, Salad",
            "priority": "true",
        },
    )

    # 4. Editor marks item GOT
    _login_as(client, editor, ws.id)
    client.post(reverse("shopping:set_status", args=[item.id, ItemStatus.GOT]))

    # 5. Open Edit modal -> Advanced section exists, collapsed by default (no 'open' attribute on <details>)
    modal_resp = client.get(reverse("shopping:edit_item", args=[item.id]))
    assert modal_resp.status_code == 200
    html = modal_resp.content.decode("utf-8")

    details_match = re.search(r"<details\b([^>]*)>", html)
    assert details_match is not None
    assert "open" not in details_match.group(1).split()
    assert "Advanced" in html
    assert f'href="{reverse("shopping:list")}"' not in html
    assert "Source Recipes" not in html
    assert "Status Changed" not in html

    # All recorded actions with actors and descriptions are present
    logs = list(item.history_logs.all())
    assert len(logs) == 6
    assert "Maya" in html
    assert "Liam" in html
    assert "Status changed: Need → Got" in html
    assert "Organic" in html
    assert "Produce" in html
    assert "Confirmed needed" in html or "Pantry Check lock" in html
    assert "Marked as High Priority" in html
    assert "Added +1" in html
    assert "Added 2" in html


@pytest.mark.django_db
def test_recipe_meal_and_preset_links_scaling_and_deduction_history(client, history_setup):
    """Combined recipe + preset items record scale/deduct events and link to recipe, preset list, and meal."""
    owner = history_setup["owner"]
    ws = history_setup["workspace"]
    shopping_list = history_setup["shopping_list"]

    recipe = Recipe.objects.create(name="Tomato Soup", directions="Simmer tomatoes.", created_by=owner)
    Ingredient.objects.create(recipe=recipe, name="Tomatoes", amount=Decimal("2.00"), amount_unit="cups")

    meal_plan, _ = MealPlan.objects.get_or_create(workspace=ws, defaults={"name": "Plan"})
    meal = add_meal_to_plan(meal_plan, "Cozy Dinner")
    req = client.request().wsgi_request
    req.user = owner
    add_recipe_to_meal(meal, recipe, shopping_list, request=req)
    dish = MealDish.objects.get(meal=meal, recipe=recipe)

    preset = create_preset_list(ws, "Weekly Produce")
    preset_item = add_preset_item(preset, "Tomatoes", amount="1 cup", user=owner)
    assert preset_item.history_logs.filter(action=ItemHistoryAction.CREATED).exists()

    load_preset_items_to_shopping_list(preset, shopping_list, user=owner)

    shop_item = shopping_list.items.get(name="Tomatoes")
    _login_as(client, owner, ws.id)
    recipe_url = reverse("recipes:detail", args=[recipe.id])
    preset_url = reverse("shopping:preset_detail", args=[preset.id])

    # Before unloading preset, both originating recipe and preset list appear in Source Recipes & Lists
    combined_modal = client.get(reverse("shopping:edit_item", args=[shop_item.id]))
    assert combined_modal.status_code == 200
    combined_html = combined_modal.content.decode("utf-8")
    assert "Source Recipes &amp; Lists" in combined_html
    assert f'href="{recipe_url}"' in combined_html
    assert f'href="{preset_url}"' in combined_html
    assert f'href="{reverse("shopping:list")}"' not in combined_html
    assert f'href="{reverse("mealplans:detail")}"' not in combined_html

    scale_meal_dish(dish, Decimal("2.00"), shopping_list, request=req)
    unload_preset_from_shopping_list(preset, shopping_list, request=req)

    modal_resp = client.get(reverse("shopping:edit_item", args=[shop_item.id]))
    assert modal_resp.status_code == 200
    html = modal_resp.content.decode("utf-8")

    assert modal_resp.context["associated_recipes"] == [recipe]
    assert modal_resp.context["associated_lists"] == []
    assert f'href="{recipe_url}"' in html
    assert f'href="{preset_url}"' in html
    assert f'href="{reverse("shopping:list")}"' not in html
    assert "Recipe: Tomato Soup" in html
    assert "Weekly Produce" in html
    assert "Scaled" in html
    assert "Unloaded preset" in html

    # Preset item edit modal also shows collapsed Advanced history linking to the preset list
    client.post(
        reverse("shopping:preset_item_toggle_active", args=[preset.id, preset_item.id]),
    )
    preset_modal = client.get(
        reverse("shopping:preset_edit_item", args=[preset.id, preset_item.id]),
    )
    assert preset_modal.status_code == 200
    preset_html = preset_modal.content.decode("utf-8")
    assert "Advanced" in preset_html
    assert f'href="{preset_url}"' in preset_html
    assert "Paused from recurring schedule" in preset_html


@pytest.mark.django_db
def test_merge_preserves_history_and_legacy_fallback_works(client, history_setup):
    """Merging duplicate items preserves all prior logs; direct ORM items render baseline history."""
    owner = history_setup["owner"]
    editor = history_setup["editor"]
    ws = history_setup["workspace"]
    shopping_list = history_setup["shopping_list"]

    # 1. Status move merge: item A (Carrots, GOT) moved back to NEED combines into existing Carrots item B
    _login_as(client, owner, ws.id)
    client.post(reverse("shopping:add_item"), {"name": "Carrots", "amount": "1 lb"})
    carrot_a = shopping_list.items.get(name="Carrots")
    client.post(reverse("shopping:set_status", args=[carrot_a.id, ItemStatus.GOT]))

    _login_as(client, editor, ws.id)
    client.post(reverse("shopping:add_item"), {"name": "Carrots", "amount": "2 lbs"})
    carrot_b = shopping_list.items.get(name="Carrots", status=ItemStatus.NEED)

    client.post(reverse("shopping:set_status", args=[carrot_a.id, ItemStatus.NEED]))
    assert not ShoppingListItem.objects.filter(id=carrot_a.id).exists()
    carrot_b.refresh_from_db()
    assert carrot_b.amount == Decimal("3.00")
    # carrot_b inherits carrot_a's prior GOT/CREATE logs + its own CREATE + MERGED event
    assert carrot_b.history_logs.filter(action=ItemHistoryAction.MERGED).exists()
    assert carrot_b.history_logs.count() == 4

    # 2. Edit merge: create Oat Milk, edit name to Milk -> merges into Milk and keeps history
    client.post(reverse("shopping:add_item"), {"name": "Milk", "amount": "1"})
    milk_item = shopping_list.items.get(name="Milk")
    _login_as(client, owner, ws.id)
    client.post(reverse("shopping:add_item"), {"name": "Oat Milk", "amount": "2"})
    oat_item = shopping_list.items.get(name="Oat Milk")
    client.post(
        reverse("shopping:edit_item", args=[oat_item.id]),
        {"name": "Milk", "amount": "2", "purpose": "Cereal"},
    )
    assert not ShoppingListItem.objects.filter(id=oat_item.id).exists()
    assert milk_item.history_logs.filter(action=ItemHistoryAction.MERGED).exists()
    assert milk_item.history_logs.count() >= 3

    # 3. Direct ORM item with zero ShoppingListItemHistory rows renders synthesized fallback history cleanly
    orm_item = ShoppingListItem.objects.create(
        shopping_list=shopping_list,
        name="Butter",
        amount=Decimal("2.00"),
        amount_unit="sticks",
        purpose="Baking",
    )
    assert not ShoppingListItemHistory.objects.filter(item=orm_item).exists()
    resp_orm = client.get(reverse("shopping:edit_item", args=[orm_item.id]))
    assert resp_orm.status_code == 200
    orm_html = resp_orm.content.decode("utf-8")
    assert "Advanced" in orm_html
    assert "Added 2 sticks (Baking)" in orm_html
