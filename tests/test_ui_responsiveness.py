"""
Unit, integration, and real headless Chromium browser tests validating extreme UI
responsiveness, zero initial grey-out, zero dropped rapid clicks, prefetching,
boosted navigation + SWR caching, actionable Undo toasts, offline queuing,
PWA service worker headers/purge, and keyboard shortcuts.
"""

import asyncio
import sys
import threading
import time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import Workspace
from apps.mealplans.models import Meal, MealDish, MealPlan, MealPlanRule
from apps.recipes.models import Recipe
from apps.shopping.models import (
    ItemStatus,
    ShoppingList,
    ShoppingListItem,
    StoreLocation,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# 1. Backend HTTP & Security Unit/Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_idempotency_middleware_deduplicates_retries(client, auth_user):
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    s_list = ShoppingList.objects.create(
        name="Groceries",
        is_preset=False,
        workspace=workspace,
        owner=user,
    )

    headers = {"HTTP_X_IDEMPOTENCY_KEY": "idem_add_milk_123"}
    url = reverse("shopping:add_item")

    resp1 = client.post(url, {"name": "Whole Milk", "amount": "1"}, **headers)
    assert resp1.status_code == 200
    assert resp1.headers.get("X-Created-Item-Id")
    assert "X-Idempotent-Replay" not in resp1.headers
    assert s_list.items.filter(name="Whole Milk").count() == 1

    # Simulated flaky mobile retry with identical X-Idempotency-Key
    resp2 = client.post(url, {"name": "Whole Milk", "amount": "1"}, **headers)
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Idempotent-Replay") == "1"
    assert resp2.headers.get("X-Created-Item-Id") == resp1.headers.get("X-Created-Item-Id")
    # Must NOT double-add or increment quantity to 2!
    milk = s_list.items.get(name="Whole Milk")
    assert milk.amount == Decimal("1.00")


@pytest.mark.django_db
def test_idempotency_middleware_isolates_users(client):
    user_a = User.objects.create_user(username="idem_a", password="pw")
    user_b = User.objects.create_user(username="idem_b", password="pw")
    ws_a = Workspace.objects.create(name="WS A", owner=user_a)
    ws_b = Workspace.objects.create(name="WS B", owner=user_b)
    list_a = ShoppingList.objects.create(name="List A", workspace=ws_a, owner=user_a)
    list_b = ShoppingList.objects.create(name="List B", workspace=ws_b, owner=user_b)

    shared_key = "shared_idem_key_001"
    url = reverse("shopping:add_item")

    client.force_login(user_a)
    sess = client.session
    sess["active_workspace_id"] = ws_a.id
    sess.save()
    r_a = client.post(url, {"name": "Apples", "amount": "2"}, HTTP_X_IDEMPOTENCY_KEY=shared_key)
    assert r_a.status_code == 200

    client.force_login(user_b)
    sess = client.session
    sess["active_workspace_id"] = ws_b.id
    sess.save()
    r_b = client.post(url, {"name": "Apples", "amount": "2"}, HTTP_X_IDEMPOTENCY_KEY=shared_key)
    assert r_b.status_code == 200
    assert "X-Idempotent-Replay" not in r_b.headers
    assert list_a.items.filter(name="Apples").count() == 1
    assert list_b.items.filter(name="Apples").count() == 1


@pytest.mark.django_db
def test_service_worker_headers_and_cache_purge_cookies(client, auth_user):
    user, workspace = auth_user
    sw_resp = client.get("/sw.js")
    assert sw_resp.status_code == 200
    assert "application/javascript" in sw_resp.headers["Content-Type"]
    assert sw_resp.headers.get("Service-Worker-Allowed") == "/"
    assert "no-store" in sw_resp.headers.get("Cache-Control", "")
    assert b"PURGE_USER_CACHES" in sw_resp.content

    client.force_login(user)
    ws_2 = Workspace.objects.create(name="Cabin", owner=user)
    switch_resp = client.get(reverse("core:switch_workspace", args=[ws_2.id]))
    assert switch_resp.status_code == 302
    assert switch_resp.cookies.get("shoppin_purge_cache") is not None

    logout_resp = client.get(reverse("core:logout"))
    assert logout_resp.status_code == 302
    assert logout_resp.cookies.get("shoppin_purge_cache") is not None


@pytest.mark.django_db
def test_base_template_removes_global_htmx_dim_and_blocking_head_libs(client, auth_user):
    user, workspace = auth_user
    ShoppingList.objects.create(name="Main", workspace=workspace, owner=user)
    client.force_login(user)
    resp = client.get(reverse("shopping:list"))
    html = resp.content.decode("utf-8")

    # Ensure coarse global dim and sticky row locks are eradicated
    assert ".htmx-request {\n            opacity: 0.6;" not in html
    assert ".htmx-request {\r\n            opacity: 0.6;" not in html
    assert "lazy_assets.js" in html
    assert "prefetcher.js" in html
    assert "mutation_queue.js" in html
    assert "app_shell.js" in html
    assert "shortcuts.js" in html
    assert "speculationrules" in html


@pytest.mark.django_db
def test_prefetch_does_not_override_pantry_mode_during_edit(client, auth_user):
    user, workspace = auth_user
    s_list = ShoppingList.objects.create(name="Pantry Safe List", workspace=workspace, owner=user)
    item = ShoppingListItem.objects.create(
        shopping_list=s_list, name="Flour", amount=Decimal("2.00"), category="baking", status=ItemStatus.NEED
    )
    client.force_login(user)

    # Enter Pantry Check mode explicitly
    pantry_resp = client.get(reverse("shopping:pantry_check"))
    assert pantry_resp.status_code == 200
    assert client.session.get("shopping_mode") == "pantry"

    # Passive hover/speculation prefetches targeting Shopping List must NOT overwrite active session mode
    prefetch_resp = client.get(f"{reverse('shopping:list')}?mode=shopping", HTTP_X_PREFETCH="1")
    assert prefetch_resp.status_code == 200
    assert client.session.get("shopping_mode") == "pantry"

    spec_resp = client.get(reverse("shopping:list"), HTTP_SEC_PURPOSE="prefetch")
    assert spec_resp.status_code == 200
    assert client.session.get("shopping_mode") == "pantry"

    # Edit GET & POST retain pantry mode cleanly via modal hidden input + query param
    modal_resp = client.get(f"{reverse('shopping:edit_item', args=[item.id])}?group_by=category&mode=pantry")
    assert modal_resp.status_code == 200
    modal_html = modal_resp.content.decode("utf-8")
    assert 'name="mode" value="pantry"' in modal_html

    save_resp = client.post(
        f"{reverse('shopping:edit_item', args=[item.id])}?mode=pantry",
        data={"name": "Whole Wheat Flour", "amount": "2", "group_by": "category", "mode": "pantry"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="shopping-list-content",
    )
    assert save_resp.status_code == 200
    saved_html = save_resp.content.decode("utf-8")
    assert 'data-mode="pantry"' in saved_html
    assert "Pantry Check Mode:" in saved_html


# ---------------------------------------------------------------------------
# 2. Real Headless Chromium Browser Validation Tests (Playwright)
# ---------------------------------------------------------------------------


def _run_in_thread(target):
    """Run sync_playwright cleanly on a worker thread so pytest-django stays isolated."""
    exc = []

    def wrapper():
        try:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            target()
        except BaseException as e:
            exc.append(e)

    t = threading.Thread(target=wrapper)
    t.start()
    t.join()
    if exc:
        raise exc[0]


def _launch_browser(p):
    """Launch system Chrome/Edge or Playwright Chromium for headless tests."""
    for kwargs in ({"channel": "chrome", "headless": True}, {"channel": "msedge", "headless": True}, {"headless": True}):
        try:
            return p.chromium.launch(**kwargs)
        except Exception:
            continue
    return p.chromium.launch(headless=True)


def _login_playwright_page(page, base_url, username, password):
    page.goto(f"{base_url}/login/", wait_until="domcontentloaded")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


@pytest.mark.django_db(transaction=True)
def test_browser_no_grey_load_no_dropped_clicks_optimistic_and_undo(live_server):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from apps.core.models import TermsOfServiceAcceptance

    user = User.objects.create_user(username="browser_ux_user", password="pw123456")
    ws = Workspace.objects.create(name="UX Kitchen", owner=user)
    TermsOfServiceAcceptance.objects.create(user=user, version=TermsOfServiceAcceptance.CURRENT_VERSION)
    s_list = ShoppingList.objects.create(name="UX List", workspace=ws, owner=user)

    items = [
        ShoppingListItem.objects.create(
            shopping_list=s_list, name=name, amount=Decimal("1.00"), category="produce", status=ItemStatus.NEED, locked=False, order=i
        )
        for i, name in enumerate(["Bananas", "Spinach", "Carrots", "Garlic"])
    ]

    # Seed MealPlan, Rule & Recipe for cross-tab/surface verification
    recipe = Recipe.objects.create(
        name="Fast Garlic Soup",
        directions="Boil garlic cleanly.",
        portions=4,
        is_public=True,
        is_approved=True,
        created_by=user,
    )
    mp = MealPlan.objects.create(workspace=ws, name="Weekly")
    meal = Meal.objects.create(meal_plan=mp, name="Monday Dinner")
    MealDish.objects.create(meal=meal, recipe=recipe, scale_factor=Decimal("1.00"))
    rule = MealPlanRule.objects.create(meal_plan=mp, rule_text="High fiber", is_active=True)

    # Create preset list & item for hold-to-undo test
    preset = ShoppingList.objects.create(name="Weekly Staples", is_preset=True, workspace=ws, owner=user)
    preset_item = ShoppingListItem.objects.create(
        shopping_list=preset, name="Oatmeal", amount=Decimal("1.00"), category="pantry", is_active=True
    )

    def _run_suite():
        base_url = live_server.url
        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            console_errors = []
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            _login_playwright_page(page, base_url, "browser_ux_user", "pw123456")

            # A. Verify NO greyed-out UI opacity on initial load or window focus
            page.goto(f"{base_url}/", wait_until="domcontentloaded")
            page.wait_for_selector("#shopping-list-content")
            initial_opacity = page.eval_on_selector(
                "#shopping-list-content",
                "el => parseFloat(getComputedStyle(el).opacity)"
            )
            assert initial_opacity == 1.0, f"Expected full opacity 1.0 on initial load, got {initial_opacity}"

            # Trigger focus event and ensure UI does NOT dim to 0.6 or drop clicks
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_timeout(80)
            after_focus_opacity = page.eval_on_selector(
                "#shopping-list-content",
                "el => parseFloat(getComputedStyle(el).opacity)"
            )
            assert after_focus_opacity == 1.0

            # B. Rapid Pantry Check Lock/Reset toggles must NEVER freeze row (no stuck pointer-events: none!)
            page.goto(f"{base_url}/pantry-check/", wait_until="networkidle")
            first_row_sel = f"#item-row-{items[0].id}"
            lock_btn_sel = f"{first_row_sel} form[hx-post*='/lock/'] button"
            page.click(lock_btn_sel)
            # Immediately click again (toggling Need -> Reset without waiting!)
            page.click(lock_btn_sel)
            page.click(lock_btn_sel)
            page.wait_for_timeout(100)
            row_pe = page.eval_on_selector(first_row_sel, "el => getComputedStyle(el).pointerEvents")
            row_op = page.eval_on_selector(first_row_sel, "el => parseFloat(getComputedStyle(el).opacity)")
            assert row_pe != "none", "Row stayed non-clickable (pointer-events: none) after lock clicks!"
            assert row_op > 0.9, f"Row stayed greyed out (opacity={row_op}) after lock toggle!"

            # B2. Hover Shopping List nav tab (triggers background prefetch) WITHOUT clicking, then edit & save item:
            # Must NOT kick user out of Pantry Check mode!
            nav_shopping = page.locator("nav[aria-label='Primary Navigation'] a[data-mode-switch='shopping']")
            nav_shopping.hover()
            page.wait_for_timeout(160)

            pantry_edit_btn = page.locator(f"#item-row-{items[1].id} button[hx-get*='/edit/']")
            pantry_edit_btn.click()
            page.wait_for_selector("#edit-item-modal-title")
            assert page.input_value("#modal-container input[name='mode']") == "pantry"
            page.fill("#edit-item-name", "Baby Spinach")
            page.click("#modal-container button[type='submit']")
            page.wait_for_function("() => window.ShoppinQueue.getQueue().length === 0", timeout=8000)
            page.wait_for_timeout(150)

            assert page.get_attribute("#shopping-list-content", "data-mode") == "pantry", (
                "Saving an item edit kicked user out of Pantry Check mode!"
            )
            assert "Pantry Check Mode:" in page.locator("#shopping-list-content").inner_text()
            assert "Baby Spinach" in page.locator(f"#item-row-{items[1].id} .item-title").inner_text()
            assert page.locator("nav[aria-label='Primary Navigation'] a[data-mode-switch='pantry']").get_attribute("aria-current") == "page"

            # C. Rapid shopping taps (zero dropped clicks across 3 different items!)
            page.goto(f"{base_url}/?mode=shopping", wait_until="networkidle")
            for idx in (1, 2, 3):
                btn = page.locator(f"#item-row-{items[idx].id} button:has-text('Got')")
                btn.click()
            # All 3 must immediately appear inside #got-items-list at 0ms
            for idx in (1, 2, 3):
                assert page.locator(f"#got-items-list #item-row-{items[idx].id}").count() == 1

            # Click actionable Undo button on latest toast -> moves Garlic right back to To Buy!
            undo_btn = page.locator("#toast-container button:has-text('Undo')").last
            assert undo_btn.count() == 1
            undo_btn.click()
            page.wait_for_timeout(80)
            assert page.locator(f"#section-groups-container #item-row-{items[3].id}").count() == 1

            # D. Priority 0ms Toggle & Live Quick Add Ghost Row + Rapid Consecutive Entry
            prio_btn = page.locator(f"#item-row-{items[0].id} .item-priority-toggle-btn")
            prio_btn.click()
            assert page.locator(f"#item-row-{items[0].id} button[title*='remove priority']").count() == 1

            # Type Quick Add with live syntax preview (!)
            page.fill("#add-item-amount", "2 lbs")
            page.fill("#add-item-name", "Tomatoes !")
            page.wait_for_selector("#quick-add-preview:not(.hidden)")
            preview_txt = page.locator("#quick-add-preview").inner_text().upper()
            assert "PRIORITY" in preview_txt
            assert "PRODUCE" in preview_txt
            page.press("#add-item-name", "Enter")
            # Focus should remain inside #add-item-name for rapid entry and input cleared at 0ms!
            assert page.evaluate("document.activeElement && document.activeElement.id") == "add-item-name"
            assert page.input_value("#add-item-name") == ""
            page.wait_for_timeout(450)
            assert "Tomatoes" in page.locator("#section-groups-container").inner_text()

            # E. Hover-Intent Prefetch -> Opening Edit Modal uses single network request + optimistic row edit
            modal_requests = []
            page.on("request", lambda req: modal_requests.append(req.url) if f"/item/{items[0].id}/edit/" in req.url and req.method == "GET" else None)
            edit_btn = page.locator(f"#item-row-{items[0].id} button[hx-get*='/edit/']")
            edit_btn.hover()
            page.wait_for_timeout(160)
            edit_btn.click()
            page.wait_for_selector("#edit-item-modal-title")
            assert len(modal_requests) == 1, f"Expected 1 prefetched request, saw {len(modal_requests)}"
            page.fill("#edit-item-name", "Organic Bananas")
            page.click("#modal-container button[type='submit']")
            page.wait_for_timeout(80)
            assert page.locator("#modal-container").count() == 0
            assert "Organic Bananas" in page.locator(f"#item-row-{items[0].id} .item-title").inner_text()

            # F. Offline Queue Serialization & Replay on Reconnect
            context.set_offline(True)
            page.wait_for_timeout(100)
            page.fill("#add-item-name", "Offline Olive Oil")
            page.press("#add-item-name", "Enter")
            page.click(f"#item-row-{items[0].id} button:has-text('Skip')")
            page.wait_for_timeout(100)
            # Verify offline indicator displays queued items
            assert "Offline" in page.locator("#offline-sync-indicator").inner_text()
            queued_len = page.evaluate("window.ShoppinQueue.getQueue().length")
            assert queued_len >= 2

            # Come back online -> queue flushes automatically and updates Synced state!
            context.set_offline(False)
            page.wait_for_function("() => window.ShoppinQueue.getQueue().length === 0", timeout=8000)

            # G. Boosted App-Shell Navigation & Keyboard Shortcuts (?, /, Alt+3..4)
            page.goto(f"{base_url}/", wait_until="networkidle")
            page.press("body", "Alt+3")  # Switch to Meal Plan via boosted/SWR nav
            page.wait_for_selector("#mealplan-content")

            # Toggle Meal Plan Rule optimistically (0ms) + Hold-to-Undo Delete Dish
            page.click("summary:has-text('Meal Plan Guidelines')")
            toggle_btn = page.locator("#mealplan-content form[hx-post*='/toggle/'] button")
            assert toggle_btn.inner_text().strip() == "Pause"
            toggle_btn.click()
            assert toggle_btn.inner_text().strip() == "Enable"

            # Open Shortcuts modal with `?`
            page.press("body", "Shift+Slash")
            page.wait_for_selector("#shortcuts-modal-title")
            page.press("body", "Escape")

            # Switch to Recipes (Alt+4) -> Detail -> 0ms Star Rating -> Instant SWR revisit to Meal Plan (Alt+3)
            page.press("body", "Alt+4")
            page.wait_for_selector("#recipe-search-input")
            # Focus shortcut `/` puts cursor in search bar
            page.press("body", "Slash")
            assert page.evaluate("document.activeElement && document.activeElement.id") == "recipe-search-input"

            page.click(f"a:has-text('{recipe.name}')")
            page.wait_for_selector(f"#recipe-rating-widget-{recipe.id}")
            # Click 4th star -> fills 4th star gold at 0ms
            star4 = page.locator(f"#recipe-rating-widget-{recipe.id} button[aria-label*='4 of 5 stars']")
            star4.click()
            assert "text-amber-500" in star4.locator("span").get_attribute("class")

            # Revisit Meal Plan via Alt+3 -> SWR snapshot renders immediately at full opacity 1.0
            page.press("body", "Alt+3")
            page.wait_for_selector("#mealplan-content")
            mp_opacity = page.eval_on_selector(
                "#mealplan-content",
                "el => parseFloat(getComputedStyle(el).opacity)"
            )
            assert mp_opacity == 1.0

            # H. Preset Item Hold-to-Undo delete test (click trash -> toast Undo -> item restored without deletion!)
            page.goto(f"{base_url}/preset-lists/{preset.id}/", wait_until="networkidle")
            del_btn = page.locator(f"#preset-item-{preset_item.id} button[aria-label*='Delete item']")
            del_btn.click()
            page.wait_for_timeout(120)
            preset_undo = page.locator("#toast-container button:has-text('Undo')").last
            assert preset_undo.count() == 1
            preset_undo.click()
            page.wait_for_timeout(150)
            assert page.locator(f"#preset-item-{preset_item.id}").is_visible()

            page.wait_for_function("() => window.ShoppinQueue.getQueue().length === 0", timeout=8000)
            assert not console_errors, f"Uncaught browser console/page errors: {console_errors}"
            browser.close()

    _run_in_thread(_run_suite)

    # Confirm DB persisted optimistic & queued operations cleanly!
    s_list.refresh_from_db()
    items[0].refresh_from_db()
    items[1].refresh_from_db()
    assert items[0].name == "Organic Bananas"
    assert items[1].name == "Baby Spinach"
    assert items[0].status == ItemStatus.DONT_NEED
    assert ShoppingListItem.objects.filter(shopping_list=s_list, name__icontains="Offline Olive Oil").exists()
    assert ShoppingListItem.objects.filter(shopping_list=s_list, name__icontains="Tomatoes", priority=True).exists()
    rule.refresh_from_db()
    assert rule.is_active is False
    assert ShoppingListItem.objects.filter(id=preset_item.id).exists()


@pytest.mark.django_db(transaction=True)
def test_browser_lazy_leaflet_store_picker_and_skeleton(live_server):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from apps.core.models import TermsOfServiceAcceptance

    user = User.objects.create_user(username="browser_map_user", password="pw123456")
    ws = Workspace.objects.create(name="Map WS", owner=user)
    TermsOfServiceAcceptance.objects.create(user=user, version=TermsOfServiceAcceptance.CURRENT_VERSION)
    ShoppingList.objects.create(name="Map List", workspace=ws, owner=user)
    StoreLocation.objects.create(
        name="King Soopers #123 - Capitol Hill",
        chain="kroger",
        address="1155 E 9th Ave",
        city="Denver",
        zip_code="80218",
        latitude=39.7305,
        longitude=-104.9725,
    )

    def _run_map_check():
        base_url = live_server.url
        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            _login_playwright_page(page, base_url, "browser_map_user", "pw123456")
            page.goto(f"{base_url}/", wait_until="domcontentloaded")

            # Verify Leaflet is NOT loaded synchronously in initial document head
            has_leaflet_initial = page.evaluate("Boolean(document.querySelector('head script[src*=\"leaflet\"]'))")
            assert not has_leaflet_initial, "Leaflet should load lazily on demand, not block <head>!"

            # Clicking Near Me / Map immediately opens skeleton modal & loads store picker cleanly
            page.click("button[aria-label*='Locate nearest store']")
            page.wait_for_selector("#store-picker-map", timeout=10000)
            assert page.locator("#nearest-stores-modal-title").is_visible()
            browser.close()

    _run_in_thread(_run_map_check)
    time.sleep(0.05)


@pytest.mark.django_db(transaction=True)
def test_browser_rapid_pantry_burst_never_drops_or_reverts_skip(live_server):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from apps.core.models import TermsOfServiceAcceptance

    user = User.objects.create_user(username="browser_burst_user", password="pw123456")
    ws = Workspace.objects.create(name="Burst WS", owner=user)
    TermsOfServiceAcceptance.objects.create(user=user, version=TermsOfServiceAcceptance.CURRENT_VERSION)
    s_list = ShoppingList.objects.create(name="Burst List", workspace=ws, owner=user)
    items = [
        ShoppingListItem.objects.create(
            shopping_list=s_list, name=name, amount=Decimal("1.00"), category="dairy", status=ItemStatus.NEED, locked=False, order=i
        )
        for i, name in enumerate(["Milk", "Eggs", "Cheese", "Yogurt"])
    ]

    def _run_burst():
        base_url = live_server.url
        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            console_errors = []
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            _login_playwright_page(page, base_url, "browser_burst_user", "pw123456")
            page.goto(f"{base_url}/pantry-check/", wait_until="networkidle")

            # Capture stale pre-skip HTML snapshot (with Cheese still in To Buy)
            stale_html = page.evaluate("document.getElementById('shopping-list-content').outerHTML")

            # Rapid multi-action burst without waiting between interactions:
            # 1) Three rapid lock toggles on Milk (Need -> Reset -> Need -> must end locked=True)
            milk_lock = page.locator(f"#item-row-{items[0].id} form[hx-post*='/lock/'] button")
            milk_lock.click()
            milk_lock.click()
            milk_lock.click()

            # 2) Quick Add triggers add_item response whose server HTML still predates Skip(Cheese)
            page.fill("#add-item-name", "Sourdough")
            page.press("#add-item-name", "Enter")

            # 3) Immediately click Skip(Cheese) and Have(Yogurt) while add/lock are in flight
            page.locator(f"#item-row-{items[2].id} button:has-text('Skip')").click()
            page.locator(f"#item-row-{items[3].id} button:has-text('Have')").click()

            # Verify immediate 0ms optimistic placement in Skipped/Have section
            assert page.locator(f"#pantry-items-list #item-row-{items[2].id}").count() == 1
            assert page.locator(f"#pantry-items-list #item-row-{items[3].id}").count() == 1

            # Simulate a stale Idiomorph swap arriving while rows remain protected in outbox
            if page.evaluate("() => window.ShoppinQueue.hasPendingWork()"):
                page.evaluate("(html) => window.ShoppinMorph.swapFromHtml('#shopping-list-content', html)", stale_html)
                assert page.locator(f"#pantry-items-list #item-row-{items[2].id}").count() == 1, (
                    "Idiomorph teleported protected Cheese back into To Buy during pending skip!"
                )

            # Wait for queue to drain completely + post-burst reconciliation
            page.wait_for_function("() => !window.ShoppinQueue.hasPendingWork()", timeout=8000)
            page.wait_for_timeout(150)

            assert page.get_attribute("#shopping-list-content", "data-mode") == "pantry"
            assert page.locator(f"#pantry-items-list #item-row-{items[2].id}").count() == 1, (
                "Cheese reverted back to To Buy after burst completed!"
            )
            assert page.locator(f"#section-groups-container #item-row-{items[2].id}").count() == 0
            assert page.locator(f"#pantry-items-list #item-row-{items[3].id}").count() == 1
            assert "Sourdough" in page.locator("#section-groups-container").inner_text()

            # Deterministic stale-morph & burst-protection check while queue holds Need -> Reset -> Skip on Eggs
            context.set_offline(True)
            eggs_lock = page.locator(f"#item-row-{items[1].id} form[hx-post*='/lock/'] button")
            eggs_lock.click()
            eggs_lock.click()
            page.locator(f"#item-row-{items[1].id} button:has-text('Skip')").click()
            assert page.evaluate("() => window.ShoppinQueue.hasPendingWork()") is True
            assert page.locator(f"#pantry-items-list #item-row-{items[1].id}").count() == 1
            page.evaluate("(html) => window.ShoppinMorph.swapFromHtml('#shopping-list-content', html)", stale_html)
            assert page.locator(f"#pantry-items-list #item-row-{items[1].id}").count() == 1, (
                "Stale Idiomorph swap moved queued Eggs back into To Buy!"
            )
            context.set_offline(False)
            page.wait_for_function("() => !window.ShoppinQueue.hasPendingWork()", timeout=8000)
            page.wait_for_timeout(120)
            assert page.locator(f"#pantry-items-list #item-row-{items[1].id}").count() == 1

            assert not console_errors, f"Uncaught browser console/page errors: {console_errors}"
            browser.close()

    _run_in_thread(_run_burst)

    items[0].refresh_from_db()
    items[1].refresh_from_db()
    items[2].refresh_from_db()
    items[3].refresh_from_db()
    assert items[0].locked is True
    assert items[1].status == ItemStatus.DONT_NEED
    assert items[2].status == ItemStatus.DONT_NEED
    assert items[3].status == ItemStatus.HAVE
    assert ShoppingListItem.objects.filter(shopping_list=s_list, name__icontains="Sourdough").exists()
