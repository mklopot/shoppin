"""
Automated security audit and exploit mitigation test suite.

Verifies:
1. Strict Authorization & Access Control:
   - Unauthenticated guests cannot view or mutate shopping lists, pantries, meal plans, or preset lists.
   - HTMX unauthenticated requests return 401 with HX-Redirect header.
   - Unauthenticated POST mutations are rejected with HTTP 403 Forbidden.
2. Tenant & Workspace Scoping:
   - Anonymous visitors receive active_workspace=None and user_workspaces=[] in context processor.
   - Read-only viewers cannot mutate items or meal plans.
3. Server-Side Request Forgery (SSRF) Mitigations:
   - Outbound recipe scraper strictly blocks loopback, RFC 1918 private ranges, and cloud metadata (169.254.169.254).
   - Non-HTTP(S) protocols (file://, ftp://) are rejected.
4. SQL Injection (SQLi) Protections:
   - Parameterized queries handle injection payloads safely without syntax errors or unescaped execution.
5. Static Security Analysis (Bandit SAST):
   - Automated Bandit security scan verifies zero medium or high severity security vulnerabilities.
"""

import subprocess
import sys
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from apps.core.context_processors import workspace_context
from apps.core.models import Workspace, WorkspaceMember, WorkspaceRole
from apps.core.services.workspace_service import get_active_workspace, get_user_workspaces
from apps.mealplans.models import Meal, MealPlan
from apps.recipes.models import Recipe
from apps.recipes.services.recipe_scraper import validate_safe_url
from apps.recipes.services.recipe_service import search_recipes
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem

User = get_user_model()


@pytest.fixture
def security_test_data(db):
    """Set up test workspace, users, and shopping items."""
    owner = User.objects.create_user(username="sec_owner", password="password123")
    viewer = User.objects.create_user(username="sec_viewer", password="password123")
    unrelated_user = User.objects.create_user(username="sec_stranger", password="password123")

    ws = Workspace.objects.create(name="Private Household", owner=owner)
    WorkspaceMember.objects.create(workspace=ws, user=viewer, role=WorkspaceRole.VIEWER)

    shopping_list = ShoppingList.objects.create(
        name="Household List",
        workspace=ws,
        owner=owner,
        is_preset=False,
    )
    item = ShoppingListItem.objects.create(
        shopping_list=shopping_list,
        name="Secret Ingredients",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
        order=1,
    )

    preset_list = ShoppingList.objects.create(
        name="Weekly Staples",
        workspace=ws,
        owner=owner,
        is_preset=True,
    )

    meal_plan = MealPlan.objects.create(
        name="Household Plan",
        workspace=ws,
        owner=owner,
    )
    meal = Meal.objects.create(
        meal_plan=meal_plan,
        name="Family Dinner",
        order=1,
    )

    recipe = Recipe.objects.create(
        name="Secret Pie",
        description="Private family recipe",
        directions="Bake it.",
        is_public=True,
        is_approved=True,
        created_by=owner,
    )

    return {
        "owner": owner,
        "viewer": viewer,
        "stranger": unrelated_user,
        "workspace": ws,
        "shopping_list": shopping_list,
        "item": item,
        "preset_list": preset_list,
        "meal_plan": meal_plan,
        "meal": meal,
        "recipe": recipe,
    }


# ===========================================================================
# 1. Authorization Boundaries: Unauthenticated Access Prohibited
# ===========================================================================


@pytest.mark.django_db
def test_unauthenticated_pantry_check_redirects_to_login(client: Client, security_test_data):
    """Pantry Check mode must never leak private lists to unauthenticated visitors."""
    url = reverse("shopping:pantry_check")
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"{reverse('core:login')}?next={url}"


@pytest.mark.django_db
def test_unauthenticated_shopping_list_redirects_to_login(client: Client, security_test_data):
    """Primary shopping list must redirect unauthenticated visitors to login."""
    url = reverse("shopping:list")
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"{reverse('core:login')}?next={url}"


@pytest.mark.django_db
def test_unauthenticated_meal_plans_redirects_to_login(client: Client, security_test_data):
    """Meal plan detail page must redirect unauthenticated visitors to login."""
    url = reverse("mealplans:detail")
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"{reverse('core:login')}?next={url}"


@pytest.mark.django_db
def test_unauthenticated_preset_lists_redirects_to_login(client: Client, security_test_data):
    """Preset list gallery must redirect unauthenticated visitors to login."""
    url = reverse("shopping:preset_list_index")
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"{reverse('core:login')}?next={url}"


@pytest.mark.django_db
def test_unauthenticated_preset_detail_redirects_to_login(client: Client, security_test_data):
    """Preset list template detail must redirect unauthenticated visitors to login."""
    preset_id = security_test_data["preset_list"].id
    url = reverse("shopping:preset_detail", args=[preset_id])
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"{reverse('core:login')}?next={url}"


@pytest.mark.django_db
def test_unauthenticated_htmx_requests_return_401_with_hx_redirect(client: Client, security_test_data):
    """HTMX requests from guests must receive 401 status with HX-Redirect header."""
    for url in [
        reverse("shopping:list"),
        reverse("shopping:pantry_check"),
        reverse("mealplans:detail"),
        reverse("shopping:preset_list_index"),
    ]:
        resp = client.get(url, HTTP_HX_REQUEST="true")
        assert resp.status_code == 401
        assert "HX-Redirect" in resp.headers
        assert reverse("core:login") in resp.headers["HX-Redirect"]


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_unauthenticated_mutations_rejected_with_forbidden(client: Client, security_test_data):
    """State-changing POST endpoints must reject unauthenticated requests with 403 Forbidden."""
    item = security_test_data["item"]
    meal = security_test_data["meal"]
    preset = security_test_data["preset_list"]

    mutation_endpoints = [
        (reverse("shopping:add_item"), {"name": "Hacked Item", "amount": "1"}),
        (reverse("shopping:set_status", args=[item.id, "GOT"]), {}),
        (reverse("shopping:delete_item", args=[item.id]), {}),
        (reverse("shopping:toggle_lock", args=[item.id]), {}),
        (reverse("shopping:toggle_priority", args=[item.id]), {}),
        (reverse("shopping:set_store"), {"store_id": "1"}),
        (reverse("shopping:reorder"), {"item_ids[]": [str(item.id)]}),
        (reverse("mealplans:add_meal"), {"meal": "Hacked Dinner"}),
        (reverse("mealplans:delete_meal", args=[meal.id]), {}),
        (reverse("shopping:preset_create"), {"name": "Hacked Preset"}),
        (reverse("shopping:preset_edit_name", args=[preset.id]), {"name": "Renamed"}),
        (reverse("shopping:preset_delete", args=[preset.id]), {}),
        (reverse("shopping:preset_add_item", args=[preset.id]), {"name": "Bread"}),
        (reverse("shopping:preset_run_schedule_now", args=[preset.id]), {}),
        (reverse("shopping:preset_load_items", args=[preset.id]), {"item_ids": ["1"]}),
        (reverse("shopping:preset_unload", args=[preset.id]), {}),
        (reverse("core:create_workspace"), {"name": "Rogue Workspace"}),
    ]

    for url, data in mutation_endpoints:
        resp = client.post(url, data)
        assert resp.status_code in (401, 403), f"Endpoint {url} permitted unauthenticated POST (status {resp.status_code})"

    # Ensure item and meal were not deleted or modified
    assert ShoppingListItem.objects.filter(id=item.id).exists()
    assert Meal.objects.filter(id=meal.id).exists()
    assert ShoppingList.objects.filter(id=preset.id).exists()


# ===========================================================================
# 2. Multi-Tenant Workspace Scoping & Read-Only Role Enforcement
# ===========================================================================


@pytest.mark.django_db
def test_get_active_workspace_returns_none_for_anonymous_requests(rf: RequestFactory):
    """Anonymous visitors must never be assigned an active workspace."""
    req = rf.get("/")
    from django.contrib.auth.models import AnonymousUser
    req.user = AnonymousUser()

    ws = get_active_workspace(req)
    assert ws is None

    workspaces = get_user_workspaces(req.user)
    assert workspaces == []


@pytest.mark.django_db
def test_guest_context_processor_does_not_leak_workspaces(rf: RequestFactory, security_test_data):
    """Context processor must expose active_workspace=None and can_write=False to guests."""
    req = rf.get("/recipes/")
    from django.contrib.auth.models import AnonymousUser
    req.user = AnonymousUser()

    ctx = workspace_context(req)
    assert ctx["active_workspace"] is None
    assert ctx["workspace_role"] == "guest"
    assert ctx["can_write_workspace"] is False
    assert ctx["is_workspace_owner"] is False
    assert ctx["user_workspaces"] == []


@pytest.mark.django_db
def test_viewer_role_cannot_mutate_workspace_data(client: Client, security_test_data):
    """Workspace members with 'viewer' role must receive 403 Forbidden on write attempts."""
    viewer = security_test_data["viewer"]
    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = security_test_data["workspace"].id
    session.save()

    item = security_test_data["item"]
    meal = security_test_data["meal"]
    preset = security_test_data["preset_list"]

    viewer_mutations = [
        (reverse("shopping:add_item"), {"name": "Viewer Item"}),
        (reverse("shopping:set_status", args=[item.id, "GOT"]), {}),
        (reverse("shopping:delete_item", args=[item.id]), {}),
        (reverse("shopping:toggle_lock", args=[item.id]), {}),
        (reverse("mealplans:add_meal"), {"meal": "Viewer Meal"}),
        (reverse("mealplans:delete_meal", args=[meal.id]), {}),
        (reverse("shopping:preset_create"), {"name": "Viewer Preset"}),
        (reverse("shopping:preset_delete", args=[preset.id]), {}),
        (reverse("shopping:preset_add_item", args=[preset.id]), {"name": "Viewer Milk"}),
        (reverse("shopping:preset_run_schedule_now", args=[preset.id]), {}),
    ]

    for url, data in viewer_mutations:
        resp = client.post(url, data)
        assert resp.status_code == 403, f"Viewer was permitted write access to {url} (status {resp.status_code})"


# ===========================================================================
# 3. Server-Side Request Forgery (SSRF) Mitigations
# ===========================================================================


def test_ssrf_prohibits_cloud_metadata_endpoints():
    """Attempts to scrape AWS/cloud metadata (169.254.169.254) must be blocked."""
    prohibited_urls = [
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/latest/api/token",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ]
    for url in prohibited_urls:
        with pytest.raises(ValueError) as excinfo:
            validate_safe_url(url)
        assert "prohibited" in str(excinfo.value).lower()


def test_ssrf_prohibits_loopback_and_internal_ip_ranges():
    """Attempts to scrape loopback or private RFC 1918 subnets must be blocked."""
    local_urls = [
        "http://127.0.0.1:8000/admin/",
        "http://localhost:8000/",
        "http://0.0.0.0:8000/",
        "http://[::1]:8000/",
        "http://10.0.0.1/internal",
        "http://172.16.0.1/dashboard",
        "http://192.168.1.1/router",
    ]
    for url in local_urls:
        with pytest.raises(ValueError) as excinfo:
            validate_safe_url(url)
        assert "prohibited" in str(excinfo.value).lower()


def test_ssrf_prohibits_non_http_protocols():
    """Non-HTTP(S) schemes (file://, ftp://, gopher://) must be rejected."""
    bad_schemes = [
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://example.com/file",
        "gopher://example.com/",
    ]
    for url in bad_schemes:
        with pytest.raises(ValueError) as excinfo:
            validate_safe_url(url)
        assert "prohibited protocol scheme" in str(excinfo.value).lower()


# ===========================================================================
# 4. SQL Injection (SQLi) Protections
# ===========================================================================


@pytest.mark.django_db
def test_recipe_search_sql_injection_payloads_handled_safely(security_test_data):
    """SQL injection payloads in search queries must not trigger SQL syntax errors or exploit ORM."""
    malicious_inputs = [
        "' OR '1'='1",
        "admin'--",
        "'; DROP TABLE apps_recipes_recipe; --",
        "UNION SELECT 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20--",
        "' OR 1=1 UNION ALL SELECT * FROM auth_user--",
    ]

    for payload in malicious_inputs:
        params = {
            "q": payload,
            "cuisine": payload,
            "sort": payload,  # Invalid sort key must safely fallback to 'name'
        }
        # search_recipes must execute parameterized queries cleanly without throwing DatabaseError
        results = search_recipes(params, user=None)
        # Results should be an evaluated QuerySet, not executing raw SQL injection
        count = results.count()
        assert isinstance(count, int)


# ===========================================================================
# 5. Static Security Analysis (Bandit SAST Scanner in Testing)
# ===========================================================================


def test_bandit_security_scan_passes_with_zero_medium_or_high_issues():
    """
    Execute standard Bandit security linter across the application code.
    Ensures zero high or medium severity security vulnerabilities exist.
    """
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        "apps/",
        "-ll",  # Report only Medium and High severity issues
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"Bandit security scanner detected security issues in apps/:\n"
        f"{res.stdout}\n{res.stderr}"
    )
