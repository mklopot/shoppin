"""
Tests for Recipe Creation from Cookbook / Handwritten Recipe Card Photographs
(Amazon Bedrock Converse API + SigV4 signing + copyright source-type rules + UI views).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import io
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.core.models import UserDMCAProfile, Workspace, WorkspaceMember, WorkspaceRole
from apps.recipes.models import Recipe
from apps.recipes.services.recipe_photo_ocr import (
    _sign_aws_v4_bedrock_headers,
    extract_recipe_from_photos,
    parse_extracted_recipe_json,
)

BEDROCK_TEST_SETTINGS = {
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_SESSION_TOKEN": "",
    "AWS_BEDROCK_REGION": "us-east-2",
    "AWS_BEDROCK_RECIPE_OCR_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "AWS_BEDROCK_RECIPE_OCR_FALLBACK_MODEL_ID": "us.amazon.nova-pro-v1:0",
    "RECIPE_PHOTO_OCR_MAX_PAGES": 4,
    "IMAGE_MODERATION_ENABLED": False,
}

SAMPLE_RECIPE_JSON = {
    "is_recipe": True,
    "name": "Grandma's Apple Crisp",
    "description": "Warm spiced apples baked beneath a buttery oat streusel topping.",
    "cuisine": "American",
    "dish_type": "Dessert",
    "difficulty_level": "easy",
    "portions": 6,
    "prep_time_minutes": 20,
    "cook_time_minutes": 45,
    "meal_type": ["dessert", "UnknownIgnored"],
    "dietary_restrictions": ["Vegetarian"],
    "occasions": ["autumn", "Thanksgiving"],
    "special_equipment": ["Oven", "casserole dish"],
    "ingredients": [
        {"name": "Granny Smith apples", "amount": 6, "amount_unit": "", "brand": "", "optional": False},
        {"name": "rolled oats", "amount": "1 1/2", "amount_unit": "cups", "brand": "Quaker", "optional": False},
        {"name": "ground cinnamon", "amount": "½", "amount_unit": "tsp", "brand": "", "optional": False},
        {"name": "chopped walnuts", "amount": "1/2", "amount_unit": "cup", "brand": "", "optional": True},
    ],
    "directions": [
        "Preheat oven to 350°F and grease an 8x8 baking dish.",
        "Peel, core, and slice the apples and toss with cinnamon.",
        "Mix oats, butter, flour, and sugar into crumbs, sprinkle over apples, and bake 45 minutes.",
    ],
    "storage_instructions": "Cover and refrigerate up to 4 days.",
    "reheating_instructions": "Warm in a 325°F oven for 12 minutes.",
    "source_citation": "Grandma's Recipe Box",
    "ocr_notes": "Handwritten baking temperature looked slightly smudged; confirmed 350°F.",
}


def _make_jpeg_upload(name: str = "recipe_card.jpg", color: tuple[int, int, int] = (245, 240, 220)) -> SimpleUploadedFile:
    buf = io.BytesIO()
    img = Image.new("RGB", (120, 90), color=color)
    img.save(buf, format="JPEG", quality=85)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def _mock_bedrock_converse_response(text_payload: str, *, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    body = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text_payload}],
            }
        }
    }
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


# ---------------------------------------------------------------------------
# Unit tests: SigV4 Bedrock signing & JSON normalization
# ---------------------------------------------------------------------------


def test_sign_aws_v4_bedrock_headers_double_encodes_model_uri():
    fixed_time = datetime.datetime(2026, 11, 27, 16, 49, 1, tzinfo=datetime.timezone.utc)
    payload = b'{"messages":[{"role":"user","content":[{"text":"hi"}]}]}'
    model_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    endpoint, headers = _sign_aws_v4_bedrock_headers(
        model_id=model_id,
        payload=payload,
        region="us-east-2",
        access_key="AKIA_TEST",
        secret_key="SECRET_TEST",
        session_token="TOK_123",
        now=fixed_time,
    )

    assert endpoint == (
        "https://bedrock-runtime.us-east-2.amazonaws.com"
        "/model/us.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse"
    )
    assert headers["Host"] == "bedrock-runtime.us-east-2.amazonaws.com"
    assert headers["X-Amz-Date"] == "20261127T164901Z"
    assert headers["X-Amz-Security-Token"] == "TOK_123"
    assert headers["Content-Type"] == "application/json"

    # Independently recompute SigV4 signature with double-encoded canonical URI (%253A)
    canonical_headers = (
        "content-type:application/json\n"
        "host:bedrock-runtime.us-east-2.amazonaws.com\n"
        "x-amz-date:20261127T164901Z\n"
        "x-amz-security-token:TOK_123\n"
    )
    signed_headers = "content-type;host;x-amz-date;x-amz-security-token"
    canonical_request = "\n".join(
        [
            "POST",
            "/model/us.anthropic.claude-haiku-4-5-20251001-v1%253A0/converse",
            "",
            canonical_headers,
            signed_headers,
            hashlib.sha256(payload).hexdigest(),
        ]
    )
    scope = "20261127/us-east-2/bedrock/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            "20261127T164901Z",
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    def _h(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_signing = _h(_h(_h(_h(b"AWS4SECRET_TEST", "20261127"), "us-east-2"), "bedrock"), "aws4_request")
    expected_sig = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    assert headers["Authorization"] == (
        f"AWS4-HMAC-SHA256 Credential=AKIA_TEST/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={expected_sig}"
    )


def test_parse_extracted_recipe_json_normalizes_all_fields():
    fenced = f"```json\n{json.dumps(SAMPLE_RECIPE_JSON)}\n```"
    parsed = parse_extracted_recipe_json(fenced, extra_source_citation="Family Cookbook, p. 12")

    assert parsed["name"] == "Grandma's Apple Crisp"
    assert parsed["cuisine"] == "American"
    assert parsed["dish_type"] == "Dessert"
    assert parsed["difficulty_level"] == "easy"
    assert parsed["portions"] == 6
    assert parsed["prep_time_minutes"] == 20
    assert parsed["cook_time_minutes"] == 45
    assert parsed["meal_type"] == ["Dessert"]
    assert parsed["dietary_restrictions"] == ["Vegetarian"]
    assert parsed["occasions"] == ["Autumn", "Thanksgiving"]
    assert parsed["special_equipment"] == ["Oven", "Casserole Dish"]
    assert parsed["storage_instructions"] == "Cover and refrigerate up to 4 days."
    assert parsed["reheating_instructions"] == "Warm in a 325°F oven for 12 minutes."
    assert parsed["bibliography"] == ["Family Cookbook, p. 12", "Grandma's Recipe Box"]
    assert "350°F" in parsed["ocr_notes"]

    assert len(parsed["ingredients"]) == 4
    assert parsed["ingredients"][1]["name"] == "rolled oats"
    assert parsed["ingredients"][1]["amount"] == Decimal("1.50")
    assert parsed["ingredients"][1]["amount_unit"] == "cups"
    assert parsed["ingredients"][1]["brand"] == "Quaker"
    assert parsed["ingredients"][2]["amount"] == Decimal("0.50")
    assert parsed["ingredients"][3]["optional"] is True


def test_parse_extracted_recipe_json_rejects_non_recipe_photos():
    non_recipe = json.dumps({"is_recipe": False, "error": "Photo shows a kitchen table with no recipe text."})
    with pytest.raises(ValidationError, match="no recipe text"):
        parse_extracted_recipe_json(non_recipe)

    with pytest.raises(ValidationError, match="Could not parse"):
        parse_extracted_recipe_json("not valid json at all")


# ---------------------------------------------------------------------------
# Service tests: Multi-page OCR, fallback model, moderation, validation
# ---------------------------------------------------------------------------


@override_settings(**BEDROCK_TEST_SETTINGS)
def test_extract_recipe_from_photos_multi_page_and_fallback_to_nova():
    # First call (Claude Haiku 4.5) returns 404 use-case error -> falls back cleanly to Nova Pro
    not_found_resp = MagicMock()
    not_found_resp.status_code = 404
    not_found_resp.text = '{"message":"Model use case details have not been submitted"}'
    not_found_resp.json.return_value = {"message": "Model use case details have not been submitted"}

    ok_resp = _mock_bedrock_converse_response(json.dumps(SAMPLE_RECIPE_JSON))

    with patch(
        "apps.recipes.services.recipe_photo_ocr.requests.post",
        side_effect=[not_found_resp, ok_resp],
    ) as mock_post:
        result = extract_recipe_from_photos(
            [_make_jpeg_upload("front.jpg"), _make_jpeg_upload("back.jpg")],
            source_citation="Card #42",
        )

    assert result["name"] == "Grandma's Apple Crisp"
    assert result["ocr_model"] == "us.amazon.nova-pro-v1:0"
    assert mock_post.call_count == 2

    # First call targeted Claude Haiku 4.5, second targeted Nova Pro
    assert "claude-haiku-4-5" in mock_post.call_args_list[0][0][0]
    assert "nova-pro" in mock_post.call_args_list[1][0][0]

    # Verify both pages were sent in order as JPEG blocks
    sent_body = json.loads(mock_post.call_args_list[0][1]["data"].decode("utf-8"))
    content_blocks = sent_body["messages"][0]["content"]
    image_blocks = [b for b in content_blocks if "image" in b]
    text_blocks = [b["text"] for b in content_blocks if "text" in b]
    assert len(image_blocks) == 2
    assert any("Page 1 of 2" in t for t in text_blocks)
    assert any("Page 2 of 2" in t for t in text_blocks)


@override_settings(**{**BEDROCK_TEST_SETTINGS, "IMAGE_MODERATION_ENABLED": True})
def test_extract_recipe_from_photos_rejects_explicit_image_before_bedrock():
    explicit_rekognition = MagicMock()
    explicit_rekognition.status_code = 200
    explicit_rekognition.json.return_value = {
        "ModerationLabels": [{"Name": "Explicit Nudity", "ParentName": "", "Confidence": 98.0}]
    }
    explicit_rekognition.text = "{}"

    with (
        patch(
            "apps.core.services.image_moderation_service.requests.post",
            return_value=explicit_rekognition,
        ),
        patch("apps.recipes.services.recipe_photo_ocr._invoke_bedrock_converse") as mock_bedrock,
    ):
        with pytest.raises(ValidationError, match="rejected"):
            extract_recipe_from_photos([_make_jpeg_upload("bad.jpg")])

    mock_bedrock.assert_not_called()


@override_settings(**BEDROCK_TEST_SETTINGS)
def test_extract_recipe_from_photos_validates_inputs_credentials_and_timeouts():
    with pytest.raises(ValidationError, match="at least one photo"):
        extract_recipe_from_photos([])

    with pytest.raises(ValidationError, match="at most 4 photos"):
        extract_recipe_from_photos([_make_jpeg_upload(f"p{i}.jpg") for i in range(5)])

    with pytest.raises(ValidationError, match="valid image"):
        extract_recipe_from_photos([SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")])

    with override_settings(AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY=""):
        with pytest.raises(ValidationError, match="missing AWS credentials"):
            extract_recipe_from_photos([_make_jpeg_upload()])

    with patch(
        "apps.recipes.services.recipe_photo_ocr.requests.post",
        side_effect=requests.Timeout("timed out"),
    ):
        with pytest.raises(ValidationError, match="timed out"):
            extract_recipe_from_photos([_make_jpeg_upload()])


# ---------------------------------------------------------------------------
# End-to-end view tests: recipes:import_photo, copyright rules, UI presence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_recipe_import_photo_view_handwritten_vs_cookbook_copyright_rules(client, auth_user):
    user, workspace = auth_user
    client.force_login(user)

    ok_resp = _mock_bedrock_converse_response(json.dumps(SAMPLE_RECIPE_JSON))

    # 1. Personal / Handwritten card -> pre-fills all fields, NOT locked from public
    with (
        override_settings(**BEDROCK_TEST_SETTINGS),
        patch("apps.recipes.services.recipe_photo_ocr.requests.post", return_value=ok_resp),
    ):
        resp_handwritten = client.post(
            reverse("recipes:import_photo"),
            {
                "source_type": "handwritten",
                "source_citation": "Mom's Card",
                "recipe_photos": [_make_jpeg_upload("card_front.jpg")],
            },
        )

    assert resp_handwritten.status_code == 200
    html = resp_handwritten.content.decode()
    assert "Grandma&#x27;s Apple Crisp" in html or "Grandma's Apple Crisp" in html
    assert "Granny Smith apples" in html
    assert "rolled oats" in html
    assert "Cover and refrigerate up to 4 days." in html
    assert "Warm in a 325°F oven for 12 minutes." in html
    assert 'name="is_web_imported"' not in html
    assert "Admin Review Required" not in html
    assert "Note from photo scan:" in html

    # 2. Cookbook / Magazine page -> locks public toggle & sets is_web_imported hidden input
    with (
        override_settings(**BEDROCK_TEST_SETTINGS),
        patch("apps.recipes.services.recipe_photo_ocr.requests.post", return_value=ok_resp),
    ):
        resp_cookbook = client.post(
            reverse("recipes:import_photo"),
            {
                "source_type": "cookbook",
                "source_citation": "The Joy of Cooking, p. 240",
                "recipe_photos": [_make_jpeg_upload("cookbook_p1.jpg")],
            },
        )

    assert resp_cookbook.status_code == 200
    html_cb = resp_cookbook.content.decode()
    assert 'name="is_web_imported" value="1"' in html_cb
    assert "Admin Review Required" in html_cb
    assert "The Joy of Cooking, p. 240" in html_cb

    # Saving the pre-filled cookbook recipe preserves copyright lock (private & is_web_imported=True)
    save_resp = client.post(
        reverse("recipes:create"),
        {
            "name": "Joy Apple Crisp",
            "cuisine": "American",
            "dish_type": "Dessert",
            "portions": "6",
            "has_public_toggle": "1",
            "is_web_imported": "1",
            "ingredient_name[]": ["Granny Smith apples"],
            "ingredient_amount[]": ["6"],
            "ingredient_unit[]": [""],
            "ingredient_row_id[]": ["row-0"],
        },
    )
    assert save_resp.status_code == 302
    saved = Recipe.objects.get(name="Joy Apple Crisp")
    assert saved.is_web_imported is True
    assert saved.copyright_cleared is False
    assert saved.is_public is False


@pytest.mark.django_db
def test_recipe_import_photo_view_access_control_and_ui_buttons(client, auth_user):
    user, workspace = auth_user

    # Anonymous user redirects to login
    anon_resp = client.post(reverse("recipes:import_photo"), {})
    assert anon_resp.status_code == 302
    assert "/login/" in anon_resp.url

    # Read-only workspace viewer gets 403 Forbidden
    viewer = User.objects.create_user(username="readonly_viewer", password="pw")
    other_ws = Workspace.objects.create(name="Other Kitchen", owner=user)
    WorkspaceMember.objects.create(workspace=other_ws, user=viewer, role=WorkspaceRole.VIEWER)
    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = other_ws.id
    session.save()
    ro_resp = client.post(reverse("recipes:import_photo"), {})
    assert ro_resp.status_code == 403

    # Banned DMCA user is redirected to recipes:list
    client.force_login(user)
    UserDMCAProfile.objects.update_or_create(
        user=user,
        defaults={"is_banned": True, "strikes": 3},
    )
    banned_resp = client.post(reverse("recipes:import_photo"), {})
    assert banned_resp.status_code == 302
    assert banned_resp.url == reverse("recipes:list")
    UserDMCAProfile.objects.filter(user=user).update(is_banned=False, strikes=0)

    # Writable user sees Scan from Photo button on recipes:list and panel on recipes:create
    list_html = client.get(reverse("recipes:list")).content.decode()
    assert "Scan from Photo" in list_html
    assert 'id="import-photo-modal"' in list_html

    create_html = client.get(reverse("recipes:create")).content.decode()
    assert "Scan Cookbook or Handwritten Card" in create_html
    assert reverse("recipes:import_photo") in create_html
