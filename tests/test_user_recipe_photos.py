"""
Unit, integration, security/moderation, and real headless Chromium browser tests
for user-submitted dish photos uploaded when rating made dishes or from recipe pages.
"""

import io
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.core.models import TermsOfServiceAcceptance, WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.services.mealplan_service import (
    add_meal_to_plan,
    add_recipe_to_meal,
    get_active_meal_plan,
)
from apps.recipes.models import Ingredient, Recipe, RecipeRating, RecipeUserPhoto
from tests.test_ui_responsiveness import _launch_browser, _login_playwright_page, _run_in_thread

User = get_user_model()


def _make_test_image_bytes(
    width: int = 320,
    height: int = 240,
    color: tuple[int, int, int] = (210, 95, 45),
    fmt: str = "PNG",
) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=color)
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def photo_setup(db):
    owner = User.objects.create_user(username="photo_owner", first_name="Maya", password="password123")
    other = User.objects.create_user(username="photo_other", first_name="Liam", password="password123")
    staff = User.objects.create_user(
        username="photo_staff",
        first_name="Admin",
        password="password123",
        is_staff=True,
    )
    ws = create_workspace("Maya's Kitchen", owner)
    other_ws = create_workspace("Liam's Kitchen", other)
    share_workspace(ws, other, WorkspaceRole.VIEWER)

    tacos = Recipe.objects.create(
        name="Fiesta Tacos",
        directions="Cook filling and serve warm.",
        portions=4,
        is_public=True,
        is_approved=True,
        created_by=owner,
    )
    tacos.shared_workspaces.add(ws)
    Ingredient.objects.create(recipe=tacos, name="Tortillas", amount=Decimal("8.00"), amount_unit="count")

    rice = Recipe.objects.create(
        name="Cilantro Lime Rice",
        directions="Simmer rice with lime.",
        portions=4,
        is_public=True,
        is_approved=True,
        created_by=owner,
    )
    rice.shared_workspaces.add(ws)
    Ingredient.objects.create(recipe=rice, name="Jasmine Rice", amount=Decimal("2.00"), amount_unit="cups")

    plan = get_active_meal_plan(workspace=ws)
    shopping_list = ws.get_primary_list()

    return {
        "owner": owner,
        "other": other,
        "staff": staff,
        "ws": ws,
        "other_ws": other_ws,
        "tacos": tacos,
        "rice": rice,
        "plan": plan,
        "shopping_list": shopping_list,
    }


def _login_ws(client, user, ws_id: int) -> None:
    client.force_login(user)
    sess = client.session
    sess["active_workspace_id"] = ws_id
    sess.save()


@pytest.mark.django_db
def test_submit_made_dish_rating_with_uploaded_and_camera_photos(client, photo_setup, tmp_path):
    """Rating a made dish accepts uploaded & camera photos, resizes large photos, and displays them on recipe detail."""
    owner = photo_setup["owner"]
    ws = photo_setup["ws"]
    tacos = photo_setup["tacos"]
    plan = photo_setup["plan"]
    shopping_list = photo_setup["shopping_list"]

    meal = add_meal_to_plan(plan, "Taco Tuesday")
    add_recipe_to_meal(meal, tacos, shopping_list)
    dish = meal.dishes.get(recipe=tacos)

    _login_ws(client, owner, ws.id)

    with override_settings(MEDIA_ROOT=tmp_path):
        # 1. Mark dish made -> rating modal renders multipart upload & camera capture controls
        made_resp = client.post(
            reverse("mealplans:mark_dish_made", kwargs={"meal_id": meal.id, "dish_id": dish.id}),
            HTTP_HX_REQUEST="true",
        )
        assert made_resp.status_code == 200
        made_html = made_resp.content.decode("utf-8")
        assert 'hx-encoding="multipart/form-data"' in made_html
        assert 'capture="environment"' in made_html
        assert "Take Photo" in made_html
        assert "Upload Photo" in made_html

        # 2. Submit rating + oversized upload photo (2400x1800) + camera photo + caption
        large_upload = SimpleUploadedFile(
            "tacos_big.png",
            _make_test_image_bytes(width=2400, height=1800, color=(200, 110, 40)),
            content_type="image/png",
        )
        camera_snap = SimpleUploadedFile(
            "camera_snap.jpg",
            _make_test_image_bytes(width=640, height=480, color=(90, 170, 80), fmt="JPEG"),
            content_type="image/jpeg",
        )

        submit_resp = client.post(
            reverse("mealplans:submit_made_ratings"),
            {
                "recipe_id": [str(tacos.id)],
                f"stars_{tacos.id}": "4",
                f"thumbs_up_{tacos.id}": "true",
                f"photo_caption_{tacos.id}": "Super tasty with pickled onions!",
                f"photos_{tacos.id}": [large_upload],
                f"camera_photo_{tacos.id}": [camera_snap],
            },
            HTTP_HX_REQUEST="true",
        )
        assert submit_resp.status_code == 200
        submit_html = submit_resp.content.decode("utf-8")
        assert "Saved 4★ rating" in submit_html
        assert "Added 2 photos" in submit_html

        # Rating saved
        rating = RecipeRating.objects.get(recipe=tacos, user=owner)
        assert rating.stars == 4
        assert rating.thumbs_up is True

        # Photos saved, compressed to <= 1600px JPEG, and persisted under MEDIA_ROOT
        photos = list(RecipeUserPhoto.objects.filter(recipe=tacos))
        assert len(photos) == 2
        for p in photos:
            assert p.user == owner
            assert p.workspace == ws
            assert p.caption == "Super tasty with pickled onions!"
            assert p.submitter_display == "Maya"
            saved_path = Path(p.image.path)
            assert saved_path.exists()
            with Image.open(saved_path) as saved_img:
                assert saved_img.format == "JPEG"
                assert max(saved_img.size) <= 1600

        # 3. Recipe detail display shows "User-Submitted Photos" section with both photos & caption
        detail_resp = client.get(tacos.get_absolute_url())
        assert detail_resp.status_code == 200
        detail_html = detail_resp.content.decode("utf-8")
        assert "User-Submitted Photos" in detail_html
        assert "Super tasty with pickled onions!" in detail_html
        assert "Maya" in detail_html
        for p in photos:
            assert p.image.url in detail_html

        # 4. Mealplan quick-view recipe modal also includes User-Submitted Photos preview
        modal_resp = client.get(reverse("mealplans:recipe_modal", kwargs={"recipe_id": tacos.id}))
        assert modal_resp.status_code == 200
        assert "User-Submitted Photos" in modal_resp.content.decode("utf-8")


@pytest.mark.django_db
def test_mark_meal_made_rating_modal_multi_dish_photo_upload(client, photo_setup, tmp_path):
    """Marking an entire multi-dish meal made lets the user attach separate photos per dish."""
    owner = photo_setup["owner"]
    ws = photo_setup["ws"]
    tacos = photo_setup["tacos"]
    rice = photo_setup["rice"]
    plan = photo_setup["plan"]
    shopping_list = photo_setup["shopping_list"]

    meal = add_meal_to_plan(plan, "Fiesta Dinner")
    add_recipe_to_meal(meal, tacos, shopping_list)
    add_recipe_to_meal(meal, rice, shopping_list)

    _login_ws(client, owner, ws.id)

    with override_settings(MEDIA_ROOT=tmp_path):
        made_resp = client.post(
            reverse("mealplans:mark_meal_made", kwargs={"meal_id": meal.id}),
            HTTP_HX_REQUEST="true",
        )
        assert made_resp.status_code == 200
        html = made_resp.content.decode("utf-8")
        assert f'name="photos_{tacos.id}"' in html
        assert f'name="photos_{rice.id}"' in html

        taco_photo = SimpleUploadedFile("taco.png", _make_test_image_bytes(), content_type="image/png")
        rice_photo = SimpleUploadedFile("rice.png", _make_test_image_bytes(color=(120, 200, 120)), content_type="image/png")

        resp = client.post(
            reverse("mealplans:submit_made_ratings"),
            {
                "recipe_id": [str(tacos.id), str(rice.id)],
                f"stars_{tacos.id}": "5",
                f"stars_{rice.id}": "4",
                f"photo_caption_{tacos.id}": "Tacos turned out awesome",
                f"photo_caption_{rice.id}": "Fluffy lime rice",
                f"photos_{tacos.id}": [taco_photo],
                f"camera_photo_{rice.id}": [rice_photo],
            },
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert RecipeUserPhoto.objects.filter(recipe=tacos, caption="Tacos turned out awesome").count() == 1
        assert RecipeUserPhoto.objects.filter(recipe=rice, caption="Fluffy lime rice").count() == 1


@pytest.mark.django_db
def test_user_photo_validation_rejects_non_image_and_profane_caption(client, photo_setup, tmp_path):
    """Invalid non-image uploads and profane captions are rejected safely without breaking rating submission."""
    owner = photo_setup["owner"]
    ws = photo_setup["ws"]
    tacos = photo_setup["tacos"]

    _login_ws(client, owner, ws.id)

    with override_settings(MEDIA_ROOT=tmp_path):
        fake_img = SimpleUploadedFile("not_an_image.jpg", b"<html>not really an image</html>", content_type="image/jpeg")
        resp = client.post(
            reverse("mealplans:submit_made_ratings"),
            {
                "recipe_id": [str(tacos.id)],
                f"stars_{tacos.id}": "5",
                f"photos_{tacos.id}": [fake_img],
            },
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert RecipeRating.objects.filter(recipe=tacos, user=owner, stars=5).exists()
        assert RecipeUserPhoto.objects.filter(recipe=tacos).count() == 0
        assert "valid image" in resp.content.decode("utf-8").lower()

        # Profane caption rejected cleanly
        valid_img = SimpleUploadedFile("good.png", _make_test_image_bytes(), content_type="image/png")
        bad_cap_resp = client.post(
            reverse("recipes:upload_user_photo", kwargs={"recipe_id": tacos.id}),
            {"photos": [valid_img], "caption": "what the fuck is this"},
            HTTP_HX_REQUEST="true",
        )
        assert bad_cap_resp.status_code == 200
        assert RecipeUserPhoto.objects.filter(recipe=tacos).count() == 0


@pytest.mark.django_db
def test_direct_recipe_detail_photo_upload_delete_permissions_and_moderation(client, photo_setup, tmp_path):
    """Upload & delete endpoints enforce authentication, ownership/staff permissions, and is_approved filtering."""
    owner = photo_setup["owner"]
    other = photo_setup["other"]
    staff = photo_setup["staff"]
    ws = photo_setup["ws"]
    other_ws = photo_setup["other_ws"]
    tacos = photo_setup["tacos"]

    with override_settings(MEDIA_ROOT=tmp_path):
        # Anonymous cannot upload
        anon_img = SimpleUploadedFile("anon.png", _make_test_image_bytes(), content_type="image/png")
        assert client.post(reverse("recipes:upload_user_photo", kwargs={"recipe_id": tacos.id}), {"photos": [anon_img]}).status_code == 403

        # Owner uploads directly from recipe detail page
        _login_ws(client, owner, ws.id)
        img1 = SimpleUploadedFile("plate1.png", _make_test_image_bytes(), content_type="image/png")
        up_resp = client.post(
            reverse("recipes:upload_user_photo", kwargs={"recipe_id": tacos.id}),
            {"photos": [img1], "caption": "Direct upload test"},
            HTTP_HX_REQUEST="true",
        )
        assert up_resp.status_code == 200
        assert "Direct upload test" in up_resp.content.decode("utf-8")
        photo = RecipeUserPhoto.objects.get(recipe=tacos)
        saved_path = Path(photo.image.path)
        assert saved_path.exists()

        # Unapproved photo is hidden from recipe display
        photo.is_approved = False
        photo.save(update_fields=["is_approved"])
        hidden_html = client.get(tacos.get_absolute_url()).content.decode("utf-8")
        assert "Direct upload test" not in hidden_html
        photo.is_approved = True
        photo.save(update_fields=["is_approved"])

        # Unrelated user cannot delete owner's photo (403)
        _login_ws(client, other, other_ws.id)
        assert client.post(reverse("recipes:delete_user_photo", kwargs={"photo_id": photo.id})).status_code == 403
        assert RecipeUserPhoto.objects.filter(id=photo.id).exists()

        # Staff CAN delete any user photo and cleans up file on disk
        _login_ws(client, staff, other_ws.id)
        del_resp = client.post(
            reverse("recipes:delete_user_photo", kwargs={"photo_id": photo.id}),
            HTTP_HX_REQUEST="true",
        )
        assert del_resp.status_code == 200
        assert not RecipeUserPhoto.objects.filter(id=photo.id).exists()
        assert not saved_path.exists()


@pytest.mark.django_db(transaction=True)
def test_browser_rate_made_dish_with_photo_and_view_on_recipe_display(live_server, tmp_path):
    """
    Headless Chromium end-to-end test:
    1. Mark a dish as made on /mealplans/ -> rating modal opens with Take Photo & Upload Photo options.
    2. Select a dish photo -> live thumbnail preview & caption input appear.
    3. Save rating -> toast confirms photo uploaded.
    4. Visit recipe detail page -> User-Submitted Photos section renders photo, caption, submitter, and lightbox.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    sample_photo_path = tmp_path / "crispy_tacos.png"
    sample_photo_path.write_bytes(_make_test_image_bytes(width=400, height=300, color=(225, 130, 50)))
    media_dir = tmp_path / "media_root"
    media_dir.mkdir(parents=True, exist_ok=True)

    user = User.objects.create_user(username="browser_photo_user", first_name="Elena", password="pw123456")
    ws = create_workspace("Elena's Kitchen", user)
    TermsOfServiceAcceptance.objects.create(user=user, version=TermsOfServiceAcceptance.CURRENT_VERSION)

    tacos = Recipe.objects.create(
        name="Crispy Street Tacos",
        directions="Crisp shells and load toppings.",
        portions=4,
        is_public=True,
        is_approved=True,
        created_by=user,
    )
    tacos.shared_workspaces.add(ws)
    Ingredient.objects.create(recipe=tacos, name="Corn Tortillas", amount=Decimal("6.00"), amount_unit="count")

    plan = ws.get_meal_plan()
    s_list = ws.get_primary_list()
    meal = add_meal_to_plan(plan, "Friday Tacos")
    add_recipe_to_meal(meal, tacos, s_list)

    with override_settings(MEDIA_ROOT=media_dir):
        def _run_photo_flow():
            base_url = live_server.url
            with sync_playwright() as p:
                browser = _launch_browser(p)
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                console_errors = []
                page.on("pageerror", lambda err: console_errors.append(str(err)))

                _login_playwright_page(page, base_url, "browser_photo_user", "pw123456")
                page.goto(f"{base_url}/mealplans/", wait_until="networkidle")

                # 1. Mark dish made -> opens rating modal with camera + upload controls
                page.locator("form[hx-post*='/dish/'][hx-post*='/made/'] button").first.click()
                page.wait_for_selector("#recipe-rating-modal", timeout=5000)

                assert page.locator(f"#dish-photo-camera-{tacos.id}[capture='environment']").count() == 1
                assert page.locator(f"button[aria-label='Take photo of {tacos.name}']").is_visible()
                assert page.locator(f"button[aria-label='Upload photo of {tacos.name}']").is_visible()

                # 2. Attach photo via Upload input -> live preview thumbnail & caption input appear
                page.set_input_files(f"#dish-photo-upload-{tacos.id}", str(sample_photo_path))
                page.wait_for_selector(f"#dish-photo-thumbs-{tacos.id} img", timeout=3000)
                assert "1 photo selected" in page.locator(f"#dish-photo-count-{tacos.id}").inner_text()

                page.fill(f"#dish-photo-caption-{tacos.id}", "Extra crispy golden shells!")
                page.locator(f"button[aria-label='Rate 4 stars for {tacos.name}']").click()

                # 3. Submit rating & photo -> modal closes and toast confirms upload
                page.locator("#recipe-rating-modal button[type='submit']").click()
                page.wait_for_function("() => !document.getElementById('recipe-rating-modal')", timeout=15000)
                page.wait_for_function(
                    "() => document.getElementById('toast-container')?.innerText.includes('Added 1 photo')",
                    timeout=15000,
                )

                # 4. Open recipe detail page -> User-Submitted Photos gallery displays photo, caption & lightbox
                page.goto(f"{base_url}{tacos.get_absolute_url()}", wait_until="networkidle")
                section = page.locator("#user-submitted-photos-section")
                assert section.is_visible()
                section_text = section.inner_text()
                assert "USER-SUBMITTED PHOTOS" in section_text.upper()
                assert "Extra crispy golden shells!" in section_text
                assert "Elena" in section_text
                assert section.locator(".user-photo-card img").count() == 1

                # Click thumbnail -> full-size lightbox opens cleanly, Escape closes it
                section.locator(".user-photo-card button[data-photo-src]").first.click()
                page.wait_for_selector("#user-photo-lightbox", timeout=3000)
                assert "Extra crispy golden shells!" in page.locator("#user-photo-lightbox").inner_text()
                page.keyboard.press("Escape")
                page.wait_for_function("() => !document.getElementById('user-photo-lightbox')", timeout=3000)

                assert not console_errors, f"Uncaught browser console/page errors: {console_errors}"
                browser.close()

        _run_in_thread(_run_photo_flow)

        # Verify DB & media file persisted cleanly
        saved_photo = RecipeUserPhoto.objects.get(recipe=tacos, user=user)
        assert saved_photo.caption == "Extra crispy golden shells!"
        assert Path(saved_photo.image.path).exists()
        rating = RecipeRating.objects.get(recipe=tacos, user=user)
        assert rating.stars == 4


@pytest.mark.django_db(transaction=True)
def test_browser_desktop_webcam_capture_and_nocam_hiding(live_server, tmp_path):
    """
    Headless Chromium test for desktop webcam capture:
    1. On desktop with a webcam: clicking Take Photo opens live #dish-webcam-modal (via getUserMedia),
       Escape closes only the webcam modal (keeping Rating Modal open), and Snap Photo captures a JPEG
       into the form, releases tracks, previews, uploads, and renders in User-Submitted Photos.
    2. On desktop with zero videoinput cameras: Take Photo button is hidden cleanly.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    media_dir = tmp_path / "webcam_media"
    media_dir.mkdir(parents=True, exist_ok=True)

    user = User.objects.create_user(username="browser_webcam_user", first_name="Noah", password="pw123456")
    ws = create_workspace("Noah's Kitchen", user)
    TermsOfServiceAcceptance.objects.create(user=user, version=TermsOfServiceAcceptance.CURRENT_VERSION)

    soup = Recipe.objects.create(
        name="Golden Squash Soup",
        directions="Roast squash and blend smooth.",
        portions=4,
        is_public=True,
        is_approved=True,
        created_by=user,
    )
    soup.shared_workspaces.add(ws)
    Ingredient.objects.create(recipe=soup, name="Butternut Squash", amount=Decimal("1.00"), amount_unit="")

    plan = ws.get_meal_plan()
    s_list = ws.get_primary_list()
    meal = add_meal_to_plan(plan, "Cozy Soup Night")
    add_recipe_to_meal(meal, soup, s_list)

    with override_settings(MEDIA_ROOT=media_dir):
        def _run_webcam_flow():
            base_url = live_server.url
            with sync_playwright() as p:
                browser = _launch_browser(p)
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                console_errors = []
                page.on("pageerror", lambda err: console_errors.append(str(err)))

                _login_playwright_page(page, base_url, "browser_webcam_user", "pw123456")

                # Provide a real canvas-backed MediaStream mock for desktop webcam testing
                page.add_init_script("""
                    (() => {
                        window.__mockTracks = [];
                        window.__mockNoCamera = false;
                        const fakeMediaDevices = {
                            enumerateDevices: async () => {
                                if (window.__mockNoCamera) {
                                    return [{ kind: 'audioinput', deviceId: 'mic-1', label: 'Mic' }];
                                }
                                return [
                                    { kind: 'videoinput', deviceId: 'cam-1', label: 'Laptop Camera' }
                                ];
                            },
                            getUserMedia: async () => {
                                const c = document.createElement('canvas');
                                c.width = 320;
                                c.height = 240;
                                const ctx = c.getContext('2d');
                                ctx.fillStyle = '#d97706';
                                ctx.fillRect(0, 0, 320, 240);
                                ctx.fillStyle = '#ffffff';
                                ctx.fillRect(80, 60, 160, 120);
                                const stream = c.captureStream(15);
                                stream.getTracks().forEach((t) => window.__mockTracks.push(t));
                                return stream;
                            }
                        };
                        Object.defineProperty(navigator, 'mediaDevices', {
                            configurable: true,
                            value: fakeMediaDevices
                        });
                    })();
                """)

                page.goto(f"{base_url}/mealplans/", wait_until="networkidle")
                page.locator("form[hx-post*='/dish/'][hx-post*='/made/'] button").first.click()
                page.wait_for_selector("#recipe-rating-modal", timeout=5000)

                take_btn = page.locator(f"button[aria-label='Take photo of {soup.name}']")
                assert take_btn.is_visible()

                # Click Take Photo -> opens live webcam dialog
                take_btn.click()
                page.wait_for_selector("#dish-webcam-modal #dish-webcam-snap-btn:not([disabled])", timeout=5000)

                # Escape closes ONLY #dish-webcam-modal (stopping camera tracks) while keeping rating modal open!
                page.keyboard.press("Escape")
                page.wait_for_function("() => !document.getElementById('dish-webcam-modal')", timeout=3000)
                assert page.locator("#recipe-rating-modal").is_visible()
                assert page.evaluate("() => window.__mockTracks.length > 0 && window.__mockTracks.every(t => t.readyState === 'ended')")

                # Open webcam again and Snap Photo -> attaches JPEG, shows thumbnail, stops tracks
                take_btn.click()
                page.wait_for_selector("#dish-webcam-modal #dish-webcam-snap-btn:not([disabled])", timeout=5000)
                page.locator("#dish-webcam-snap-btn").click()
                page.wait_for_function("() => !document.getElementById('dish-webcam-modal')", timeout=5000)
                page.wait_for_selector(f"#dish-photo-thumbs-{soup.id} img", timeout=3000)
                assert "1 photo selected" in page.locator(f"#dish-photo-count-{soup.id}").inner_text()
                assert page.evaluate("() => window.__mockTracks.every(t => t.readyState === 'ended')")

                # Submit rating with snapped webcam photo
                page.fill(f"#dish-photo-caption-{soup.id}", "Snapped right off the stove!")
                page.locator("#recipe-rating-modal button[type='submit']").click()
                page.wait_for_function("() => !document.getElementById('recipe-rating-modal')", timeout=15000)
                page.wait_for_function(
                    "() => document.getElementById('toast-container')?.innerText.includes('Added 1 photo')",
                    timeout=15000,
                )

                # Verify rendered on recipe detail page
                page.goto(f"{base_url}{soup.get_absolute_url()}", wait_until="networkidle")
                section = page.locator("#user-submitted-photos-section")
                assert "Snapped right off the stove!" in section.inner_text()
                assert section.locator(".user-photo-card img").count() == 1

                # Verify Take Photo hides cleanly when a desktop has zero videoinput cameras
                page.evaluate("() => { window.__mockNoCamera = true; window.ShoppinDishCamera.syncCameraButtonsVisibility(document); }")
                page.wait_for_timeout(80)
                page.locator("#user-submitted-photos-section button:has-text('Add Photo')").click()
                assert page.locator("#detail-photo-upload-drawer [data-camera-trigger]").is_hidden()
                assert page.locator("#detail-photo-upload-drawer button:has-text('Upload Photo')").is_visible()

                assert not console_errors, f"Uncaught browser console/page errors: {console_errors}"
                browser.close()

        _run_in_thread(_run_webcam_flow)

        saved_photo = RecipeUserPhoto.objects.get(recipe=soup, user=user)
        assert saved_photo.caption == "Snapped right off the stove!"
        assert Path(saved_photo.image.path).exists()

