"""
Tests for AWS Rekognition image content moderation across all photo upload flows:
- AWS SigV4 request signing & Rekognition label evaluation policy
- Fail-closed rejection on explicit/violent/hate/age-restricted imagery
- Fail-hold (pending moderator review) when AWS Rekognition is unreachable or unconfigured
- End-to-end coverage for made-dish rating photos, recipe detail user photos, and main recipe photos
"""

from __future__ import annotations

import base64
import datetime
import io
import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.core.services.image_moderation_service import (
    _sign_aws_v4_rekognition_headers,
    evaluate_rekognition_labels,
    moderate_image_bytes,
)
from apps.recipes.models import Recipe, RecipeRating, RecipeUserPhoto
from apps.recipes.services.recipe_service import create_or_update_recipe

AWS_MODERATION_SETTINGS = {
    "IMAGE_MODERATION_ENABLED": True,
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_SESSION_TOKEN": "",
    "AWS_REKOGNITION_REGION": "us-east-1",
    "IMAGE_MODERATION_MIN_CONFIDENCE": 60.0,
    "IMAGE_MODERATION_BLOCK_ALCOHOL": False,
}


def _make_test_jpeg_bytes(color: tuple[int, int, int] = (200, 120, 40)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (64, 64), color=color)
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_uploaded_photo(name: str = "dish.jpg", color: tuple[int, int, int] = (200, 120, 40)) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _make_test_jpeg_bytes(color=color), content_type="image/jpeg")


def _mock_rekognition_response(labels: list[dict], *, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"ModerationLabels": labels}
    resp.text = json.dumps({"ModerationLabels": labels})
    return resp


# ---------------------------------------------------------------------------
# Unit tests: SigV4 signing & label policy
# ---------------------------------------------------------------------------


def test_sigv4_headers_include_expected_auth_and_optional_session_token():
    fixed_time = datetime.datetime(2026, 11, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)
    payload = b'{"Image":{"Bytes":"AAAA"},"MinConfidence":60.0}'

    headers = _sign_aws_v4_rekognition_headers(
        payload=payload,
        region="us-west-2",
        access_key="AKIA_TEST",
        secret_key="SECRET_TEST",
        session_token="SESSION_TOK",
        now=fixed_time,
    )

    assert headers["Host"] == "rekognition.us-west-2.amazonaws.com"
    assert headers["X-Amz-Date"] == "20261127T120000Z"
    assert headers["X-Amz-Target"] == "RekognitionService.DetectModerationLabels"
    assert headers["X-Amz-Security-Token"] == "SESSION_TOK"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert headers["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIA_TEST/20261127/us-west-2/rekognition/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date;x-amz-security-token;x-amz-target, Signature="
    )


def test_evaluate_rekognition_labels_blocks_explicit_violence_hate_and_age_restricted():
    # Clean dish image
    assert evaluate_rekognition_labels([]).status == "approved"

    # Explicit nudity
    res_nudity = evaluate_rekognition_labels(
        [{"Name": "Explicit Nudity", "ParentName": "", "Confidence": 94.2}]
    )
    assert res_nudity.status == "rejected"
    assert len(res_nudity.matched_labels) == 1
    assert "explicit" in res_nudity.reason.lower()

    # Suggestive above 75% rejected; low-confidence suggestive allowed
    assert (
        evaluate_rekognition_labels(
            [{"Name": "Swimwear or Underwear", "ParentName": "Suggestive", "Confidence": 82.0}]
        ).status
        == "rejected"
    )
    assert (
        evaluate_rekognition_labels(
            [{"Name": "Suggestive", "ParentName": "", "Confidence": 64.0}]
        ).status
        == "approved"
    )

    # Graphic violence & hate symbols
    assert (
        evaluate_rekognition_labels(
            [{"Name": "Graphic Violence Or Gore", "ParentName": "Violence", "Confidence": 88.0}]
        ).status
        == "rejected"
    )
    assert (
        evaluate_rekognition_labels(
            [{"Name": "Hate Symbols", "ParentName": "", "Confidence": 91.0}]
        ).status
        == "rejected"
    )

    # Age-restricted drugs / tobacco / gambling
    for label_name in ("Drugs", "Tobacco Products", "Gambling"):
        res = evaluate_rekognition_labels(
            [{"Name": label_name, "ParentName": "", "Confidence": 78.0}]
        )
        assert res.status == "rejected", f"Expected {label_name} to be rejected"


def test_evaluate_rekognition_labels_avoids_kitchen_false_positives():
    # Bare "Weapons" (e.g., chef knife next to chopping board) is NOT blocked
    res_knife = evaluate_rekognition_labels(
        [{"Name": "Weapons", "ParentName": "", "Confidence": 95.0}]
    )
    assert res_knife.status == "approved"

    # Alcohol allowed by default (cooking wine, dinner pairing) unless explicitly blocked
    wine_labels = [{"Name": "Wine", "ParentName": "Alcohol", "Confidence": 96.0}]
    assert evaluate_rekognition_labels(wine_labels, block_alcohol=False).status == "approved"
    assert evaluate_rekognition_labels(wine_labels, block_alcohol=True).status == "rejected"


@override_settings(IMAGE_MODERATION_ENABLED=False)
def test_moderate_image_bytes_skips_api_when_disabled():
    with patch("apps.core.services.image_moderation_service.requests.post") as mock_post:
        res = moderate_image_bytes(_make_test_jpeg_bytes())
    assert res.status == "approved"
    mock_post.assert_not_called()


@override_settings(
    IMAGE_MODERATION_ENABLED=True,
    AWS_ACCESS_KEY_ID="",
    AWS_SECRET_ACCESS_KEY="",
)
def test_moderate_image_bytes_holds_when_credentials_missing():
    with patch("apps.core.services.image_moderation_service.requests.post") as mock_post:
        res = moderate_image_bytes(_make_test_jpeg_bytes())
    assert res.status == "pending_review"
    mock_post.assert_not_called()


@override_settings(**{**AWS_MODERATION_SETTINGS, "AWS_REKOGNITION_REGION": "us-west-2"})
def test_moderate_image_bytes_sends_signed_rekognition_request():
    jpeg = _make_test_jpeg_bytes()
    with patch(
        "apps.core.services.image_moderation_service.requests.post",
        return_value=_mock_rekognition_response([]),
    ) as mock_post:
        res = moderate_image_bytes(jpeg)

    assert res.status == "approved"
    mock_post.assert_called_once()
    call_args, call_kwargs = mock_post.call_args
    assert call_args[0] == "https://rekognition.us-west-2.amazonaws.com/"
    assert call_kwargs["headers"]["X-Amz-Target"] == "RekognitionService.DetectModerationLabels"
    body = json.loads(call_kwargs["data"].decode("utf-8"))
    assert body["Image"]["Bytes"] == base64.b64encode(jpeg).decode("ascii")
    assert body["MinConfidence"] == 60.0


@override_settings(**AWS_MODERATION_SETTINGS)
def test_moderate_image_bytes_holds_on_timeout_http_error_or_bad_json():
    jpeg = _make_test_jpeg_bytes()

    with patch(
        "apps.core.services.image_moderation_service.requests.post",
        side_effect=requests.Timeout("timed out"),
    ):
        assert moderate_image_bytes(jpeg).status == "pending_review"

    with patch(
        "apps.core.services.image_moderation_service.requests.post",
        return_value=_mock_rekognition_response([], status_code=500),
    ):
        assert moderate_image_bytes(jpeg).status == "pending_review"

    bad_json_resp = MagicMock()
    bad_json_resp.status_code = 200
    bad_json_resp.json.side_effect = ValueError("not json")
    with patch(
        "apps.core.services.image_moderation_service.requests.post",
        return_value=bad_json_resp,
    ):
        assert moderate_image_bytes(jpeg).status == "pending_review"


# ---------------------------------------------------------------------------
# End-to-end integration tests: Made-dish rating photos & Recipe user photos
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_made_rating_explicit_photo_rejected_while_rating_still_saved(client, auth_user, tmp_path):
    user, _ = auth_user
    client.force_login(user)
    recipe = Recipe.objects.create(
        name="Spicy Tacos",
        cuisine="Mexican",
        is_public=True,
        is_approved=True,
        created_by=user,
    )

    explicit_resp = _mock_rekognition_response(
        [{"Name": "Explicit Nudity", "ParentName": "", "Confidence": 98.5}]
    )
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch("apps.core.services.image_moderation_service.requests.post", return_value=explicit_resp),
    ):
        resp = client.post(
            reverse("mealplans:submit_made_ratings"),
            {
                "recipe_id": [str(recipe.id)],
                f"stars_{recipe.id}": "5",
                f"thumbs_up_{recipe.id}": "true",
                f"photos_{recipe.id}": _make_uploaded_photo("bad.jpg"),
            },
        )

    assert resp.status_code == 200
    # Rating is still preserved, but explicit photo was NOT saved
    assert RecipeRating.objects.filter(recipe=recipe, user=user, stars=5).exists()
    assert RecipeUserPhoto.objects.filter(recipe=recipe).count() == 0
    html = resp.content.decode()
    assert "rejected" in html.lower()


@pytest.mark.django_db
def test_made_rating_unreachable_rekognition_holds_photo_until_approved(client, auth_user, tmp_path):
    user, _ = auth_user
    client.force_login(user)
    recipe = Recipe.objects.create(
        name="Creamy Risotto",
        cuisine="Italian",
        is_public=True,
        is_approved=True,
        created_by=user,
    )

    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch(
            "apps.core.services.image_moderation_service.requests.post",
            side_effect=requests.ConnectionError("network down"),
        ),
    ):
        resp = client.post(
            reverse("mealplans:submit_made_ratings"),
            {
                "recipe_id": [str(recipe.id)],
                f"stars_{recipe.id}": "4",
                f"photo_caption_{recipe.id}": "Turned out super creamy!",
                f"photos_{recipe.id}": _make_uploaded_photo("risotto.jpg"),
            },
        )

    assert resp.status_code == 200
    html = resp.content.decode()
    assert "pending moderator review" in html.lower()

    photo = RecipeUserPhoto.objects.get(recipe=recipe)
    assert photo.is_approved is False

    # Unapproved photo must NOT appear on public recipe detail page yet
    detail_resp = client.get(recipe.get_absolute_url())
    assert "Turned out super creamy!" not in detail_resp.content.decode()

    # Once moderator approves, photo becomes visible immediately
    photo.is_approved = True
    photo.save(update_fields=["is_approved"])
    detail_resp_after = client.get(recipe.get_absolute_url())
    assert "Turned out super creamy!" in detail_resp_after.content.decode()


@pytest.mark.django_db
def test_recipe_detail_user_photo_upload_approved_rejected_and_held(client, auth_user, tmp_path):
    user, _ = auth_user
    client.force_login(user)
    recipe = Recipe.objects.create(
        name="Berry Pancakes",
        cuisine="American",
        is_public=True,
        is_approved=True,
        created_by=user,
    )
    upload_url = reverse("recipes:upload_user_photo", args=[recipe.id])

    # 1. Flagged photo -> rejected, zero DB rows
    flagged = _mock_rekognition_response(
        [{"Name": "Smoking", "ParentName": "Drugs & Tobacco", "Confidence": 91.0}]
    )
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch("apps.core.services.image_moderation_service.requests.post", return_value=flagged),
    ):
        resp = client.post(
            upload_url,
            {"photos": _make_uploaded_photo("smoke.jpg"), "caption": "Rejected caption"},
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    assert RecipeUserPhoto.objects.filter(recipe=recipe).count() == 0
    assert "rejected" in resp.content.decode().lower()

    # 2. API outage -> saved with is_approved=False and hidden from partial
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch(
            "apps.core.services.image_moderation_service.requests.post",
            return_value=_mock_rekognition_response([], status_code=503),
        ),
    ):
        resp = client.post(
            upload_url,
            {"photos": _make_uploaded_photo("held.jpg"), "caption": "Held caption"},
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    held_photo = RecipeUserPhoto.objects.get(recipe=recipe, caption="Held caption")
    assert held_photo.is_approved is False
    body = resp.content.decode()
    assert "pending moderator review" in body.lower()
    assert "Held caption" not in body

    # 3. Clean photo -> approved and rendered immediately
    clean = _mock_rekognition_response([])
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch("apps.core.services.image_moderation_service.requests.post", return_value=clean),
    ):
        resp = client.post(
            upload_url,
            {"photos": _make_uploaded_photo("clean.jpg"), "caption": "Fluffy stack!"},
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    approved_photo = RecipeUserPhoto.objects.get(recipe=recipe, caption="Fluffy stack!")
    assert approved_photo.is_approved is True
    assert "Fluffy stack!" in resp.content.decode()


# ---------------------------------------------------------------------------
# End-to-end integration tests: Main Recipe.photo_file (create, edit, fork)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_recipe_create_rejects_explicit_main_photo(client, auth_user, tmp_path):
    user, _ = auth_user
    client.force_login(user)
    explicit_resp = _mock_rekognition_response(
        [{"Name": "Sexual Activity", "ParentName": "Explicit Nudity", "Confidence": 97.0}]
    )
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch("apps.core.services.image_moderation_service.requests.post", return_value=explicit_resp),
    ):
        resp = client.post(
            reverse("recipes:create"),
            {
                "name": "Blocked Photo Pasta",
                "cuisine": "Italian",
                "dish_type": "Main",
                "portions": "4",
                "photo_file": _make_uploaded_photo("explicit.jpg"),
            },
        )

    # Form re-renders with error message; recipe is NOT created
    assert resp.status_code == 200
    assert not Recipe.objects.filter(name="Blocked Photo Pasta").exists()
    assert "rejected" in resp.content.decode().lower()


@pytest.mark.django_db
def test_recipe_create_and_edit_hold_main_photo_when_rekognition_unavailable(client, auth_user, tmp_path):
    user, _ = auth_user
    client.force_login(user)
    # Create recipe when AWS Rekognition times out -> saved with photo_approved=False
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch(
            "apps.core.services.image_moderation_service.requests.post",
            side_effect=requests.Timeout("timeout"),
        ),
    ):
        resp = client.post(
            reverse("recipes:create"),
            {
                "name": "Pending Photo Stew",
                "cuisine": "American",
                "dish_type": "Soup",
                "portions": "4",
                "photo_file": _make_uploaded_photo("stew.jpg"),
            },
            follow=True,
        )

    assert resp.status_code == 200
    recipe = Recipe.objects.get(name="Pending Photo Stew")
    assert bool(recipe.photo_file) is True
    assert recipe.photo_approved is False
    assert recipe.primary_photo_url == ""
    assert "pending moderator review" in resp.content.decode().lower()

    # Moderator approves photo -> primary_photo_url now serves it
    recipe.photo_approved = True
    recipe.save(update_fields=["photo_approved"])
    assert recipe.primary_photo_url.startswith(recipe.photo_file.url)

    # Editing recipe with an explicit replacement photo rejects edit and keeps existing approved photo
    original_photo_name = recipe.photo_file.name
    explicit_resp = _mock_rekognition_response(
        [{"Name": "Graphic Violence Or Gore", "ParentName": "Violence", "Confidence": 95.0}]
    )
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch("apps.core.services.image_moderation_service.requests.post", return_value=explicit_resp),
    ):
        edit_resp = client.post(
            reverse("recipes:edit", args=[recipe.id]),
            {
                "name": "Pending Photo Stew",
                "cuisine": "American",
                "dish_type": "Soup",
                "portions": "4",
                "photo_file": _make_uploaded_photo("gore.jpg"),
            },
        )

    assert edit_resp.status_code == 200
    recipe.refresh_from_db()
    assert recipe.photo_file.name == original_photo_name
    assert recipe.photo_approved is True

    # Clearing photo resets photo_approved to True
    recipe.photo_approved = False
    recipe.save(update_fields=["photo_approved"])
    updated = create_or_update_recipe(
        {"name": "Pending Photo Stew", "clear_photo": "1"},
        recipe_id=recipe.id,
        user=auth_user[0],
    )
    assert bool(updated.photo_file) is False
    assert updated.photo_approved is True


@pytest.mark.django_db
def test_recipe_fork_screens_new_main_photo(client, auth_user, tmp_path):
    user, _ = auth_user
    client.force_login(user)
    other_author = User.objects.create_user(username="chef_other", password="pw")
    original = Recipe.objects.create(
        name="Chef Special Curry",
        cuisine="Indian",
        is_public=True,
        is_approved=True,
        created_by=other_author,
    )

    # Forking with explicit photo -> rejected, no forked recipe created
    explicit_resp = _mock_rekognition_response(
        [{"Name": "Explicit Nudity", "ParentName": "", "Confidence": 92.0}]
    )
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch("apps.core.services.image_moderation_service.requests.post", return_value=explicit_resp),
    ):
        resp = client.post(
            reverse("recipes:edit", args=[original.id]),
            {
                "name": "My Forked Curry",
                "cuisine": "Indian",
                "portions": "4",
                "photo_file": _make_uploaded_photo("bad_fork.jpg"),
            },
        )
    assert resp.status_code == 200
    assert not Recipe.objects.filter(forked_from=original).exists()

    # Forking when Rekognition is down -> fork saved with photo_approved=False
    with (
        override_settings(**AWS_MODERATION_SETTINGS, MEDIA_ROOT=tmp_path),
        patch(
            "apps.core.services.image_moderation_service.requests.post",
            return_value=_mock_rekognition_response([], status_code=500),
        ),
    ):
        resp_held = client.post(
            reverse("recipes:edit", args=[original.id]),
            {
                "name": "My Held Fork Curry",
                "cuisine": "Indian",
                "portions": "4",
                "photo_file": _make_uploaded_photo("held_fork.jpg"),
            },
            follow=True,
        )
    assert resp_held.status_code == 200
    forked = Recipe.objects.get(forked_from=original, created_by=user)
    assert bool(forked.photo_file) is True
    assert forked.photo_approved is False
    assert forked.primary_photo_url == ""
    assert "pending moderator review" in resp_held.content.decode().lower()
