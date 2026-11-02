"""
Unit and integration tests for recipe permissions, copy-on-write forking,
provenance chain tracking, related versions discovery, and meal plan workspace guards.
"""

from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from apps.core.models import Workspace, WorkspaceMember, WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import Meal, MealPlan
from apps.mealplans.services.mealplan_service import add_meal_to_plan, add_recipe_to_meal
from apps.recipes.models import Ingredient, Recipe
from apps.recipes.services.recipe_service import (
    create_or_update_recipe,
    fork_recipe,
    search_recipes,
)


@pytest.fixture
def permissions_setup(db):
    """
    Setup users (Alice, Bob, Charlie) and workspaces:
    - Alice's Kitchen (Alice is owner, Bob is editor)
    - Bob's Bachelor Pad (Bob is owner, Charlie is editor)
    """
    alice = User.objects.create_user(username="alice", first_name="Alice", password="password123")
    bob = User.objects.create_user(username="bob", first_name="Bob", password="password123")
    charlie = User.objects.create_user(username="charlie", first_name="Charlie", password="password123")

    ws_alice = create_workspace("Alice's Kitchen", alice)
    share_workspace(ws_alice, bob, WorkspaceRole.EDITOR)

    ws_bob = create_workspace("Bob's Bachelor Pad", bob)
    share_workspace(ws_bob, charlie, WorkspaceRole.EDITOR)

    # Base recipe created by Alice in Alice's Kitchen
    recipe_alice = Recipe.objects.create(
        name="Grandma's Secret Lasagna",
        description="Traditional layered lasagna",
        directions="Layer pasta, sauce, cheese and bake.",
        cuisine="Italian",
        created_by=alice,
        is_public=False,
        is_approved=False,
    )
    recipe_alice.shared_workspaces.add(ws_alice)
    recipe_alice.last_shared_by = alice
    recipe_alice.save()

    Ingredient.objects.create(
        recipe=recipe_alice,
        name="Lasagna Noodles",
        amount=Decimal("12.00"),
        amount_unit="sheets",
    )
    Ingredient.objects.create(
        recipe=recipe_alice,
        name="Ricotta Cheese",
        amount=Decimal("16.00"),
        amount_unit="oz",
    )

    return {
        "alice": alice,
        "bob": bob,
        "charlie": charlie,
        "ws_alice": ws_alice,
        "ws_bob": ws_bob,
        "recipe_alice": recipe_alice,
    }


@pytest.mark.django_db
def test_provenance_chain_creation(permissions_setup):
    """Verify that root recipes and forked recipes maintain complete provenance ancestry."""
    alice = permissions_setup["alice"]
    bob = permissions_setup["bob"]
    charlie = permissions_setup["charlie"]
    r_alice = permissions_setup["recipe_alice"]
    ws_bob = permissions_setup["ws_bob"]

    # 1. Root recipe provenance
    assert r_alice.original_author_display == "Alice"
    chain_alice = r_alice.get_provenance_chain()
    assert len(chain_alice) == 1
    assert chain_alice[0]["name"] == "Grandma's Secret Lasagna"
    assert chain_alice[0]["author"] == "Alice"
    assert chain_alice[0]["is_current"] is True

    # 2. Bob forks Alice's recipe into Bob's Bachelor Pad
    r_bob = fork_recipe(r_alice, bob, target_workspaces=[ws_bob])
    assert r_bob.name.startswith("Bob's version of Grandma's Secret Lasagna")
    assert r_bob.created_by == bob
    assert r_bob.forked_from == r_alice
    assert r_bob.root_recipe == r_alice
    assert r_bob.original_author == alice
    assert r_bob.original_author_display == "Alice"
    assert r_bob.ingredients.count() == 2

    chain_bob = r_bob.get_provenance_chain()
    assert len(chain_bob) == 2
    assert chain_bob[0]["name"] == r_bob.name
    assert chain_bob[0]["author"] == "Bob"
    assert chain_bob[0]["is_current"] is True
    assert chain_bob[1]["name"] == "Grandma's Secret Lasagna"
    assert chain_bob[1]["author"] == "Alice"
    assert chain_bob[1]["is_current"] is False

    # 3. Charlie forks Bob's recipe (multi-hop provenance)
    r_charlie = fork_recipe(r_bob, charlie, target_workspaces=[ws_bob], new_name="Charlie's Extra Cheesy Lasagna")
    assert r_charlie.forked_from == r_bob
    assert r_charlie.root_recipe == r_alice
    assert r_charlie.original_author == alice
    assert r_charlie.original_author_display == "Alice"

    chain_charlie = r_charlie.get_provenance_chain()
    assert len(chain_charlie) == 3
    assert chain_charlie[0]["name"] == "Charlie's Extra Cheesy Lasagna"
    assert chain_charlie[0]["author"] == "Charlie"
    assert chain_charlie[1]["name"] == r_bob.name
    assert chain_charlie[1]["author"] == "Bob"
    assert chain_charlie[2]["name"] == "Grandma's Secret Lasagna"
    assert chain_charlie[2]["author"] == "Alice"


@pytest.mark.django_db
def test_provenance_chain_resilient_to_ancestor_deletion(permissions_setup):
    """Verify that if an ancestor recipe is deleted, snapshot fields preserve the history."""
    bob = permissions_setup["bob"]
    r_alice = permissions_setup["recipe_alice"]
    ws_bob = permissions_setup["ws_bob"]

    r_bob = fork_recipe(r_alice, bob, target_workspaces=[ws_bob])
    r_alice_id = r_alice.id
    r_alice.delete()

    r_bob.refresh_from_db()
    assert r_bob.forked_from is None
    assert r_bob.forked_from_title == "Grandma's Secret Lasagna"
    assert r_bob.forked_from_author_name == "Alice"

    chain = r_bob.get_provenance_chain()
    assert len(chain) == 2
    assert chain[0]["name"] == r_bob.name
    assert chain[1]["name"] == "Grandma's Secret Lasagna"
    assert chain[1]["author"] == "Alice"


@pytest.mark.django_db
def test_related_workspace_versions(permissions_setup):
    """Verify sibling versions sharing the same root are discoverable in the workspace."""
    alice = permissions_setup["alice"]
    bob = permissions_setup["bob"]
    r_alice = permissions_setup["recipe_alice"]
    ws_alice = permissions_setup["ws_alice"]
    ws_bob = permissions_setup["ws_bob"]

    # Bob forks Alice's recipe into Alice's Kitchen
    r_bob_shared = fork_recipe(
        r_alice,
        bob,
        target_workspaces=[ws_alice],
        new_name="Bob's Spicy Lasagna",
    )

    # Bob also forks another version into Bob's Bachelor Pad
    r_bob_other = fork_recipe(
        r_alice,
        bob,
        target_workspaces=[ws_bob],
        new_name="Bob's Solo Lasagna",
    )

    # Check related versions from Alice's Kitchen
    related_to_alice = r_alice.get_related_workspace_versions(ws_alice)
    assert related_to_alice.count() == 1
    assert r_bob_shared in related_to_alice
    assert r_bob_other not in related_to_alice

    # Check related versions when viewing Bob's version in Alice's Kitchen
    related_to_bob = r_bob_shared.get_related_workspace_versions(ws_alice)
    assert related_to_bob.count() == 1
    assert r_alice in related_to_bob


@pytest.mark.django_db
def test_copy_on_write_when_editing_unowned_recipe(permissions_setup):
    """Modifying a recipe not owned by the user automatically creates a copy with default naming."""
    bob = permissions_setup["bob"]
    r_alice = permissions_setup["recipe_alice"]
    ws_alice = permissions_setup["ws_alice"]

    data = {
        "name": r_alice.name,  # User didn't change the name
        "description": "Bob's spicy modification",
        "directions": "Add chili flakes then bake.",
        "cuisine": "Italian-American",
        "portions": 6,
        "sharing_destination": "original",
    }

    # Bob submits edit for Alice's recipe
    saved_recipe = create_or_update_recipe(
        data=data,
        recipe_id=r_alice.id,
        user=bob,
        workspace=ws_alice,
    )

    # Original remains untouched!
    r_alice.refresh_from_db()
    assert r_alice.name == "Grandma's Secret Lasagna"
    assert r_alice.portions == 4
    assert r_alice.created_by.username == "alice"

    # New fork created!
    assert saved_recipe.id != r_alice.id
    assert saved_recipe.name == "Bob's version of Grandma's Secret Lasagna"
    assert saved_recipe.created_by == bob
    assert saved_recipe.forked_from == r_alice
    assert saved_recipe.portions == 6
    assert saved_recipe.shared_workspaces.filter(id=ws_alice.id).exists()


@pytest.mark.django_db
def test_sharing_destination_choices(permissions_setup):
    """Verify options: share to original workspace, current workspace, or keep private."""
    bob = permissions_setup["bob"]
    r_alice = permissions_setup["recipe_alice"]
    ws_alice = permissions_setup["ws_alice"]
    ws_bob = permissions_setup["ws_bob"]

    # Option A: Keep private
    data_private = {
        "name": "Bob's Secret Recipe",
        "sharing_destination": "private",
    }
    r_priv = create_or_update_recipe(data_private, recipe_id=r_alice.id, user=bob, workspace=ws_bob)
    assert r_priv.shared_workspaces.count() == 0

    # Option B: Share with current workspace (Bob's Bachelor Pad)
    data_current = {
        "name": "Bob's Bachelor Lasagna",
        "sharing_destination": "current",
    }
    r_curr = create_or_update_recipe(data_current, recipe_id=r_alice.id, user=bob, workspace=ws_bob)
    assert r_curr.shared_workspaces.filter(id=ws_bob.id).exists()
    assert not r_curr.shared_workspaces.filter(id=ws_alice.id).exists()


@pytest.mark.django_db
def test_meal_plan_workspace_guard(permissions_setup):
    """Enforce that recipes can only be added to a meal plan in the same workspace."""
    alice = permissions_setup["alice"]
    bob = permissions_setup["bob"]
    r_alice = permissions_setup["recipe_alice"]
    ws_alice = permissions_setup["ws_alice"]
    ws_bob = permissions_setup["ws_bob"]

    # Alice's meal plan
    meal_plan_alice = ws_alice.get_meal_plan()
    meal_alice = add_meal_to_plan(meal_plan_alice, "Sunday Dinner")
    list_alice = ws_alice.get_primary_list()

    # Bob's meal plan
    meal_plan_bob = ws_bob.get_meal_plan()
    meal_bob = add_meal_to_plan(meal_plan_bob, "Monday Night")
    list_bob = ws_bob.get_primary_list()

    # Adding Alice's recipe to Alice's meal plan succeeds (recipe is in ws_alice)
    desc = add_recipe_to_meal(meal_alice, r_alice, list_alice)
    assert len(desc) > 0
    assert meal_alice.recipes.filter(id=r_alice.id).exists()

    # Attempting to add Alice's recipe to Bob's meal plan fails validation!
    # (r_alice is not in ws_bob)
    with pytest.raises(ValidationError) as exc_info:
        add_recipe_to_meal(meal_bob, r_alice, list_bob)
    assert "must be associated with or copied into workspace" in str(exc_info.value)


@pytest.mark.django_db
def test_recipe_search_workspace_visibility(permissions_setup):
    """Verify that private/unapproved recipes are visible to workspace members but hidden from outsiders."""
    alice = permissions_setup["alice"]
    bob = permissions_setup["bob"]
    charlie = permissions_setup["charlie"]
    r_alice = permissions_setup["recipe_alice"]

    # r_alice is private & unapproved, shared only in Alice's Kitchen
    # Alice is owner -> can see
    results_alice = search_recipes({}, user=alice)
    assert r_alice in results_alice

    # Bob is member of Alice's Kitchen -> can see
    results_bob = search_recipes({}, user=bob)
    assert r_alice in results_bob

    # Charlie is NOT in Alice's Kitchen -> cannot see
    results_charlie = search_recipes({}, user=charlie)
    assert r_alice not in results_charlie

    # Unauthenticated guest -> cannot see
    results_guest = search_recipes({}, user=None)
    assert r_alice not in results_guest


@pytest.mark.django_db
def test_copy_to_workspace_view(permissions_setup):
    """Verify 1-click copy to workspace HTTP endpoint."""
    charlie = permissions_setup["charlie"]
    r_alice = permissions_setup["recipe_alice"]
    ws_bob = permissions_setup["ws_bob"]

    client = Client()
    client.force_login(charlie)

    # Set active workspace session to ws_bob
    session = client.session
    session["active_workspace_id"] = ws_bob.id
    session.save()

    url = reverse("recipes:copy_to_workspace", kwargs={"recipe_id": r_alice.id})
    response = client.post(url, follow=True)
    assert response.status_code == 200

    # Charlie now has a copy in ws_bob
    fork = Recipe.objects.filter(created_by=charlie, forked_from=r_alice).first()
    assert fork is not None
    assert fork.shared_workspaces.filter(id=ws_bob.id).exists()
