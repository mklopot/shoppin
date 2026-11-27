"""
Recipe Photo OCR & Handwriting Recognition Service (Amazon Bedrock Converse API).

Extracts structured recipes from photographs of cookbook pages, magazine clippings,
or handwritten / cursive recipe cards using multimodal vision models on Amazon Bedrock
via lightweight stdlib AWS SigV4 signing (zero extra Python dependencies or local RAM).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import io
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

from apps.core.services.image_moderation_service import (
    moderate_image_bytes,
    prepare_uploaded_image_jpeg,
)
from apps.recipes.services.recipe_scraper import UNICODE_FRACTIONS, parse_ingredient_line
from apps.recipes.services.recipe_service import (
    POPULAR_CUISINES,
    POPULAR_DIETARY,
    POPULAR_DISH_TYPES,
    POPULAR_EQUIPMENT,
    POPULAR_MEAL_TYPES,
    POPULAR_OCCASIONS,
)

logger = logging.getLogger(__name__)

MAX_OCR_RAW_BYTES = 12 * 1024 * 1024  # 12 MB raw upload cap per page
MAX_OCR_IMAGE_DIMENSION = 2048  # High enough for small print and cursive handwriting
BEDROCK_MAX_IMAGE_BYTES = 3_500_000  # Safely under Bedrock Converse 3.75 MB per-image cap
BEDROCK_TIMEOUT_SECONDS = 45
DEFAULT_MAX_SCAN_PAGES = 4


def _build_system_prompt() -> str:
    """Build the structured extraction system prompt aligned with Shoppin's recipe schema."""
    return (
        "You are an expert culinary archivist and OCR transcriptionist specializing in "
        "printed cookbook pages, magazine clippings, and handwritten or cursive family recipe cards.\n\n"
        "Analyze ALL provided photograph page(s) in order (for example, front and back of a recipe card "
        "or a multi-page cookbook spread) and transcribe the recipe into a single JSON object.\n\n"
        "Rules:\n"
        "1. Return ONLY valid JSON (no markdown code fences, no prose before or after).\n"
        "2. If the image(s) do NOT contain a recipe or are completely unreadable/blank, return:\n"
        '   {"is_recipe": false, "error": "Brief helpful explanation for the user."}\n'
        "3. Transcribe handwritten and cursive text carefully. Expand unambiguous recipe-card shorthand "
        "(e.g., c. -> cups, T. / Tbsp. -> tbsp, t. -> tsp, # -> lb, pkg. -> pkg, doz. -> dozen, "
        "350° -> 350°F). Preserve authentic measurements and steps.\n"
        "4. Shopping-list-friendly ingredients: keep each ingredient's `name` concise and store-buyable "
        '(e.g., "yellow onion", "unsalted butter", "all-purpose flour") and place preparation details '
        '("finely chopped", "melted", "divided") into the `directions` steps instead.\n'
        "5. For every ingredient, provide numeric `amount` (decimal or fraction string, default 1 if "
        'unspecified such as "to taste"), `amount_unit` (short kitchen unit like "cups", "tbsp", "tsp", '
        '"oz", "lb", "g", "ml", "cloves", "cans", or "" for counted items like eggs), `name`, `brand` '
        '(only if explicitly specified on the card, else ""), and `optional` (boolean).\n'
        "6. Choose classification fields using Shoppin's preferred labels when they clearly apply:\n"
        f"   - cuisine (string, e.g. {', '.join(POPULAR_CUISINES)})\n"
        f"   - dish_type (string, e.g. {', '.join(POPULAR_DISH_TYPES)})\n"
        "   - difficulty_level: one of \"easy\", \"medium\", \"hard\"\n"
        f"   - meal_type (array subset of: {', '.join(POPULAR_MEAL_TYPES)})\n"
        f"   - dietary_restrictions (array subset ONLY if clearly true of: {', '.join(POPULAR_DIETARY)})\n"
        f"   - occasions (array subset ONLY if mentioned/obvious of: {', '.join(POPULAR_OCCASIONS)})\n"
        f"   - special_equipment (array subset ONLY if needed of: {', '.join(POPULAR_EQUIPMENT)})\n"
        "7. If any handwritten word or quantity is smudged, faded, or uncertain, give your best reading "
        "AND summarize what the user should double-check in `ocr_notes` (else empty string).\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "is_recipe": true,\n'
        '  "name": "Recipe Title",\n'
        '  "description": "Short 1-2 sentence overview or headnote if present, else empty string",\n'
        '  "cuisine": "",\n'
        '  "dish_type": "",\n'
        '  "difficulty_level": "medium",\n'
        '  "portions": 4,\n'
        '  "prep_time_minutes": 15,\n'
        '  "cook_time_minutes": 30,\n'
        '  "meal_type": [],\n'
        '  "dietary_restrictions": [],\n'
        '  "occasions": [],\n'
        '  "special_equipment": [],\n'
        '  "ingredients": [\n'
        '    {"name": "all-purpose flour", "amount": 2, "amount_unit": "cups", "brand": "", "optional": false}\n'
        "  ],\n"
        '  "directions": ["Step 1 text...", "Step 2 text..."],\n'
        '  "storage_instructions": "",\n'
        '  "reheating_instructions": "",\n'
        '  "source_citation": "Book title, page number, or family attribution visible on the photo, else empty string",\n'
        '  "ocr_notes": ""\n'
        "}"
    )


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sign_aws_v4_bedrock_headers(
    *,
    model_id: str,
    payload: bytes,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str = "",
    now: datetime.datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """
    Build the endpoint URL and AWS Signature Version 4 headers for an Amazon Bedrock
    Runtime Converse POST request (`service="bedrock"`).

    Note: Bedrock SigV4 double-encodes path segments in the Canonical URI (e.g. `:` -> `%3A`
    in the HTTP request path, and `%253A` in the SigV4 CanonicalRequest).
    """
    service = "bedrock"
    host = f"bedrock-runtime.{region}.amazonaws.com"
    content_type = "application/json"

    encoded_model = quote(model_id, safe="")
    request_path = f"/model/{encoded_model}/converse"
    canonical_uri = quote(request_path, safe="/")

    utc_now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = utc_now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = utc_now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(payload).hexdigest()

    headers_to_sign: dict[str, str] = {
        "content-type": content_type,
        "host": host,
        "x-amz-date": amz_date,
    }
    if session_token:
        headers_to_sign["x-amz-security-token"] = session_token

    sorted_keys = sorted(headers_to_sign.keys())
    canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)

    canonical_request = "\n".join(
        [
            "POST",
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            algorithm,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    request_headers = {
        "Content-Type": content_type,
        "Host": host,
        "X-Amz-Date": amz_date,
        "Authorization": authorization,
    }
    if session_token:
        request_headers["X-Amz-Security-Token"] = session_token

    endpoint = f"https://{host}{request_path}"
    return endpoint, request_headers


def _prepare_ocr_jpeg_bytes(uploaded_file: Any) -> bytes:
    """
    Validate, EXIF-orient, resize, moderate, and ensure JPEG payload fits under
    Bedrock Converse's 3.75 MB per-image cap.
    """
    from PIL import Image

    jpeg_bytes = prepare_uploaded_image_jpeg(
        uploaded_file,
        max_bytes=MAX_OCR_RAW_BYTES,
        max_dimension=MAX_OCR_IMAGE_DIMENSION,
    )

    if len(jpeg_bytes) > BEDROCK_MAX_IMAGE_BYTES:
        with Image.open(io.BytesIO(jpeg_bytes)) as img:
            img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            jpeg_bytes = buf.getvalue()

    mod_result = moderate_image_bytes(jpeg_bytes)
    if mod_result.status == "rejected":
        raise ValidationError(mod_result.reason)

    return jpeg_bytes


def _parse_amount_decimal(raw_amount: Any) -> Decimal:
    """Convert numeric/fraction/unicode-fraction ingredient amount into a clean Decimal."""
    if raw_amount is None or raw_amount == "":
        return Decimal("1.00")

    if isinstance(raw_amount, (int, float, Decimal)):
        try:
            val = Decimal(str(raw_amount))
            if val > 0:
                return val.quantize(Decimal("0.01"))
        except InvalidOperation:
            return Decimal("1.00")
        return Decimal("1.00")

    text = str(raw_amount).strip()
    for uf, ascii_f in UNICODE_FRACTIONS.items():
        text = text.replace(uf, f" {ascii_f}")
    text = re.sub(r"\s+", " ", text).strip()

    # Handle ranges like "1-2" or "1 to 2" by taking the upper/average or first sensible number
    range_match = re.match(r"^(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)$", text, re.IGNORECASE)
    if range_match:
        text = range_match.group(1)

    try:
        parts = text.split()
        total = Fraction(0)
        matched_any = False
        for part in parts:
            if "/" in part:
                total += Fraction(part)
                matched_any = True
            else:
                try:
                    total += Fraction(Decimal(part))
                    matched_any = True
                except InvalidOperation:
                    break
        if matched_any and total > 0:
            return Decimal(float(total)).quantize(Decimal("0.01"))
    except (ValueError, ZeroDivisionError, InvalidOperation):
        pass

    return Decimal("1.00")


def _safe_int(value: Any, *, default: int, min_val: int, max_val: int) -> int:
    """Safely parse an integer within [min_val, max_val]."""
    if value is None or value == "":
        return default
    try:
        parsed = int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        m = re.search(r"\d+", str(value))
        if not m:
            return default
        parsed = int(m.group(0))
    return max(min_val, min(max_val, parsed))


def _filter_canonical_options(raw_list: Any, allowed: list[str]) -> list[str]:
    """Match extracted tag names case-insensitively against Shoppin's canonical option lists."""
    if not isinstance(raw_list, list):
        return []
    lookup = {opt.lower(): opt for opt in allowed}
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_list:
        key = str(item or "").strip().lower()
        canonical = lookup.get(key)
        if canonical and canonical not in seen:
            result.append(canonical)
            seen.add(canonical)
    return result


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Extract and parse the JSON object from model response text (tolerating markdown fences)."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValidationError("Could not read recipe details from the photo. Please try a clearer photo.")

    # Strip ```json ... ``` wrapper if present
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    elif not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        parsed = json.loads(cleaned)
    except ValueError as exc:
        logger.warning("Bedrock recipe OCR returned non-JSON text: %s", cleaned[:300])
        raise ValidationError(
            "Could not parse the scanned recipe clearly. Please try a sharper, well-lit photo."
        ) from exc

    if not isinstance(parsed, dict):
        raise ValidationError("Could not parse the scanned recipe clearly. Please try another photo.")
    return parsed


def parse_extracted_recipe_json(
    raw_text: str,
    *,
    extra_source_citation: str = "",
) -> dict[str, Any]:
    """
    Validate and normalize the raw JSON response from Bedrock Converse into a dict
    ready to pre-fill Shoppin's recipe creation form.
    """
    payload = _extract_json_object(raw_text)

    if payload.get("is_recipe") is False:
        reason = str(payload.get("error") or "").strip()
        raise ValidationError(
            reason or "No recipe was detected in the uploaded photo. Please try a clearer photo of the recipe."
        )

    name = str(payload.get("name") or "").strip()[:255]
    description = str(payload.get("description") or "").strip()
    cuisine = str(payload.get("cuisine") or "").strip()[:100]
    dish_type = str(payload.get("dish_type") or "").strip()[:100]

    difficulty_raw = str(payload.get("difficulty_level") or "medium").strip().lower()
    difficulty_level = difficulty_raw if difficulty_raw in ("easy", "medium", "hard") else "medium"

    portions = _safe_int(payload.get("portions"), default=4, min_val=1, max_val=200)
    prep_time_minutes = _safe_int(payload.get("prep_time_minutes"), default=0, min_val=0, max_val=10080)
    cook_time_minutes = _safe_int(payload.get("cook_time_minutes"), default=0, min_val=0, max_val=10080)

    meal_type = _filter_canonical_options(payload.get("meal_type"), POPULAR_MEAL_TYPES)
    dietary_restrictions = _filter_canonical_options(payload.get("dietary_restrictions"), POPULAR_DIETARY)
    occasions = _filter_canonical_options(payload.get("occasions"), POPULAR_OCCASIONS)
    special_equipment = _filter_canonical_options(payload.get("special_equipment"), POPULAR_EQUIPMENT)

    storage_instructions = str(payload.get("storage_instructions") or "").strip()
    reheating_instructions = str(payload.get("reheating_instructions") or "").strip()
    ocr_notes = str(payload.get("ocr_notes") or "").strip()

    # Normalize ingredients list
    raw_ingredients = payload.get("ingredients") or []
    ingredients: list[dict[str, Any]] = []
    if isinstance(raw_ingredients, list):
        for entry in raw_ingredients:
            if isinstance(entry, str):
                line = entry.strip()
                if not line:
                    continue
                parsed_ing = parse_ingredient_line(line)
                ingredients.append(
                    {
                        "name": str(parsed_ing.get("name") or line).strip()[:255],
                        "amount": _parse_amount_decimal(parsed_ing.get("amount")),
                        "amount_unit": str(parsed_ing.get("amount_unit") or "").strip()[:50],
                        "brand": "",
                        "vendor": "",
                        "optional": False,
                    }
                )
            elif isinstance(entry, dict):
                ing_name = str(entry.get("name") or "").strip()[:255]
                if not ing_name:
                    continue
                ingredients.append(
                    {
                        "name": ing_name,
                        "amount": _parse_amount_decimal(entry.get("amount")),
                        "amount_unit": str(entry.get("amount_unit") or entry.get("unit") or "").strip()[:50],
                        "brand": str(entry.get("brand") or "").strip()[:100],
                        "vendor": "",
                        "optional": bool(entry.get("optional", False)),
                    }
                )

    # Normalize directions
    raw_directions = payload.get("directions")
    steps: list[str] = []
    if isinstance(raw_directions, list):
        for step in raw_directions:
            s = str(step or "").strip()
            if s:
                steps.append(s)
    elif isinstance(raw_directions, str):
        for line in raw_directions.splitlines():
            s = line.strip()
            if s:
                steps.append(s)
    directions = "\n".join(steps)

    if not name and not ingredients and not directions:
        raise ValidationError(
            "No recipe text could be extracted from the uploaded photo. Please try a clearer, well-lit photo."
        )
    if not name:
        name = "Scanned Recipe"

    bibliography: list[str] = []
    for candidate in (extra_source_citation, payload.get("source_citation")):
        text = str(candidate or "").strip()
        if text and text not in bibliography:
            bibliography.append(text)

    return {
        "name": name,
        "description": description,
        "directions": directions,
        "portions": portions,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "cuisine": cuisine,
        "dish_type": dish_type,
        "difficulty_level": difficulty_level,
        "meal_type": meal_type,
        "dietary_restrictions": dietary_restrictions,
        "occasions": occasions,
        "special_equipment": special_equipment,
        "storage_instructions": storage_instructions,
        "reheating_instructions": reheating_instructions,
        "bibliography": bibliography,
        "ingredients": ingredients,
        "ocr_notes": ocr_notes,
    }


def _invoke_bedrock_converse(
    *,
    image_bytes_list: list[bytes],
    region: str,
    model_id: str,
    access_key: str,
    secret_key: str,
    session_token: str = "",
) -> tuple[int, str, dict[str, Any] | None]:
    """
    Send a multi-image Converse request to Amazon Bedrock Runtime.

    Returns:
        (http_status_code, raw_response_text, parsed_json_or_none)
    """
    content_blocks: list[dict[str, Any]] = []
    total_pages = len(image_bytes_list)
    for idx, jpeg_bytes in enumerate(image_bytes_list, start=1):
        if total_pages > 1:
            content_blocks.append({"text": f"Page {idx} of {total_pages}:"})
        content_blocks.append(
            {
                "image": {
                    "format": "jpeg",
                    "source": {"bytes": base64.b64encode(jpeg_bytes).decode("ascii")},
                }
            }
        )
    content_blocks.append(
        {
            "text": (
                "Extract the recipe from the provided photo(s) into the required JSON schema. "
                "Return ONLY valid JSON."
            )
        }
    )

    payload_dict = {
        "system": [{"text": _build_system_prompt()}],
        "messages": [{"role": "user", "content": content_blocks}],
        "inferenceConfig": {"maxTokens": 4096, "temperature": 0.0},
    }
    payload = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")

    endpoint, headers = _sign_aws_v4_bedrock_headers(
        model_id=model_id,
        payload=payload,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
    )

    try:
        resp = requests.post(
            endpoint,
            data=payload,
            headers=headers,
            timeout=BEDROCK_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        logger.warning("Amazon Bedrock Converse timed out for model %s: %s", model_id, exc)
        raise ValidationError(
            "Scanning the recipe photo timed out. Please try again or upload fewer/clearer photos."
        ) from exc
    except requests.RequestException as exc:
        logger.warning("Amazon Bedrock Converse network error for model %s: %s", model_id, exc)
        raise ValidationError(
            "Could not reach the recipe photo scanning service right now. Please try again in a moment."
        ) from exc

    parsed_json: dict[str, Any] | None = None
    try:
        parsed_json = resp.json()
    except ValueError:
        parsed_json = None

    return resp.status_code, (resp.text or ""), parsed_json


def _extract_text_from_converse_response(response_data: dict[str, Any]) -> str:
    """Pull concatenated assistant text content out of a Bedrock Converse JSON payload."""
    message = (response_data.get("output") or {}).get("message") or {}
    blocks = message.get("content") or []
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def extract_recipe_from_photos(
    uploaded_files: list[Any],
    *,
    source_citation: str = "",
) -> dict[str, Any]:
    """
    Transcribe one or more uploaded cookbook / handwritten recipe card photographs
    into a structured recipe dictionary via Amazon Bedrock Converse API.

    Raises:
        ValidationError: If files are invalid, flagged by moderation, not configured,
            or cannot be parsed as a recipe.
    """
    max_pages = int(getattr(settings, "RECIPE_PHOTO_OCR_MAX_PAGES", DEFAULT_MAX_SCAN_PAGES))
    files = [f for f in (uploaded_files or []) if f]
    if not files:
        raise ValidationError("Please upload or take at least one photo of a recipe.")
    if len(files) > max_pages:
        raise ValidationError(f"Please upload at most {max_pages} photos per recipe scan.")

    prepared_pages = [_prepare_ocr_jpeg_bytes(f) for f in files]

    access_key = (getattr(settings, "AWS_ACCESS_KEY_ID", "") or "").strip()
    secret_key = (getattr(settings, "AWS_SECRET_ACCESS_KEY", "") or "").strip()
    session_token = (getattr(settings, "AWS_SESSION_TOKEN", "") or "").strip()
    region = (getattr(settings, "AWS_BEDROCK_REGION", "") or "us-east-2").strip()
    primary_model = (
        getattr(settings, "AWS_BEDROCK_RECIPE_OCR_MODEL_ID", "")
        or "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    ).strip()
    fallback_model = (getattr(settings, "AWS_BEDROCK_RECIPE_OCR_FALLBACK_MODEL_ID", "") or "").strip()

    if not access_key or not secret_key:
        logger.warning("Recipe photo OCR requested but AWS credentials are not configured.")
        raise ValidationError(
            "Recipe photo scanning is not configured on this server (missing AWS credentials)."
        )

    models_to_try = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models_to_try.append(fallback_model)

    last_error_text = ""
    response_data: dict[str, Any] | None = None
    used_model = primary_model

    for idx, model_id in enumerate(models_to_try):
        status_code, raw_body, parsed = _invoke_bedrock_converse(
            image_bytes_list=prepared_pages,
            region=region,
            model_id=model_id,
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token,
        )
        if status_code == 200 and isinstance(parsed, dict):
            response_data = parsed
            used_model = model_id
            break

        last_error_text = raw_body[:300]
        logger.warning(
            "Amazon Bedrock Converse failed for model %s (HTTP %s): %s",
            model_id,
            status_code,
            last_error_text,
        )
        # Retry against fallback model on model-access/throttling/transient errors
        if idx + 1 < len(models_to_try) and status_code in (403, 404, 429, 500, 502, 503, 504):
            continue
        break

    if not response_data:
        raise ValidationError(
            "Could not scan the recipe photo right now. Please try again in a moment or enter the recipe manually."
        )

    raw_text = _extract_text_from_converse_response(response_data)
    result = parse_extracted_recipe_json(raw_text, extra_source_citation=source_citation)
    result["ocr_model"] = used_model
    return result
