"""
Image Content Moderation Service (AWS Rekognition DetectModerationLabels).

Screens uploaded recipe and dish photographs for explicit, violent, hate, or
age-restricted imagery using Amazon Rekognition via lightweight stdlib AWS SigV4
signing (zero extra runtime dependencies or local ML memory footprint).

Behavior policy:
- Flagged explicit/age-restricted image -> status="rejected" (caller rejects upload).
- Clean image -> status="approved" (published immediately).
- Transient API error / timeout / missing credentials while moderation is enabled
  -> status="pending_review" (saved with is_approved=False / photo_approved=False
  so unscreened images are never published automatically).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

MAX_UPLOADED_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB raw upload cap
MAX_PROCESSED_IMAGE_DIMENSION = 1600
REKOGNITION_MAX_BYTES = 5 * 1024 * 1024  # AWS Rekognition DetectModerationLabels 5 MB byte limit
REKOGNITION_TIMEOUT_SECONDS = 5

# ---------------------------------------------------------------------------
# Curated AWS Rekognition Moderation Label Taxonomy Thresholds
# ---------------------------------------------------------------------------
# Deliberately excludes bare "Weapons" (kitchen/chef knives next to cutting boards)
# and excludes "Alcohol" by default (cooking wine, beer-battered dishes, dinner glass)
# unless IMAGE_MODERATION_BLOCK_ALCOHOL=True is configured.

EXPLICIT_NUDITY_LABELS: frozenset[str] = frozenset(
    {
        "explicit",
        "explicit nudity",
        "nudity",
        "graphic male nudity",
        "graphic female nudity",
        "sexual activity",
        "explicit sexual activity",
        "illustrated explicit nudity",
        "adult toys",
        "non-explicit nudity",
        "explicit non-sexual nudity",
        "non-explicit nudity of intimate parts and kissing",
        "partial nudity",
        "sexual situations",
        "exposed male nipple",
    }
)

SUGGESTIVE_LABELS: frozenset[str] = frozenset(
    {
        "suggestive",
        "sexually suggestive",
        "female swimwear or underwear",
        "male swimwear or underwear",
        "swimwear or underwear",
        "revealing clothes",
        "barechested male",
    }
)

VIOLENCE_AND_HATE_LABELS: frozenset[str] = frozenset(
    {
        "violence",
        "graphic violence",
        "graphic violence or gore",
        "physical violence",
        "weapon violence",
        "visually disturbing",
        "emaciated bodies",
        "corpses",
        "hanging",
        "air crash",
        "explosions and blasts",
        "self-harm",
        "self injury",
        "hate symbols",
        "nazi party",
        "white supremacy",
        "extremist",
    }
)

AGE_RESTRICTED_LABELS: frozenset[str] = frozenset(
    {
        "drugs & tobacco",
        "drugs",
        "drug products",
        "drug use",
        "drug paraphernalia",
        "pills",
        "tobacco",
        "tobacco products",
        "smoking",
        "gambling",
    }
)

ALCOHOL_LABELS: frozenset[str] = frozenset(
    {
        "alcohol",
        "alcoholic beverages",
        "drinking",
        "beer",
        "wine",
    }
)

REJECTION_USER_MESSAGE = (
    "This photo was rejected because it appears to contain explicit, violent, "
    "or age-restricted content that is not permitted on Shoppin."
)


@dataclass
class ImageModerationResult:
    """Outcome of screening an uploaded image."""

    status: Literal["approved", "rejected", "pending_review"]
    matched_labels: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def prepare_uploaded_image_jpeg(
    uploaded_file: Any,
    *,
    max_bytes: int = MAX_UPLOADED_IMAGE_BYTES,
    max_dimension: int = MAX_PROCESSED_IMAGE_DIMENSION,
) -> bytes:
    """
    Validate an uploaded file is a genuine image, apply EXIF orientation, resize down
    to `max_dimension`, strip EXIF GPS/device metadata, and return clean JPEG bytes.

    Raises:
        ValidationError: If file is missing, too large, or not a valid image.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not uploaded_file:
        raise ValidationError("No photo file was provided.")

    file_size = getattr(uploaded_file, "size", None)
    if file_size is not None and file_size > max_bytes:
        raise ValidationError("Photo is too large (maximum size is 12 MB).")

    try:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        raw_bytes = uploaded_file.read()
    except Exception as exc:
        raise ValidationError("Could not read uploaded photo file.") from exc

    if not raw_bytes or len(raw_bytes) > max_bytes:
        raise ValidationError("Photo is empty or exceeds the 12 MB size limit.")

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "PA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                alpha = img.split()[-1]
                background.paste(img.convert("RGBA"), mask=alpha)
                processed = background
            elif img.mode == "P":
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                processed = background
            elif img.mode != "RGB":
                processed = img.convert("RGB")
            else:
                processed = img.copy()

            processed.thumbnail(
                (max_dimension, max_dimension),
                Image.Resampling.LANCZOS,
            )
            out_buf = io.BytesIO()
            processed.save(out_buf, format="JPEG", quality=85, optimize=True)
            jpeg_bytes = out_buf.getvalue()

            # Guarantee encoded bytes stay well under AWS Rekognition's 5 MB raw payload cap
            if len(jpeg_bytes) > REKOGNITION_MAX_BYTES:
                processed.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                out_buf = io.BytesIO()
                processed.save(out_buf, format="JPEG", quality=75, optimize=True)
                jpeg_bytes = out_buf.getvalue()
            return jpeg_bytes
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("Please upload a valid image file (JPG, PNG, or WebP).") from exc


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sign_aws_v4_rekognition_headers(
    *,
    payload: bytes,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str = "",
    target: str = "RekognitionService.DetectModerationLabels",
    now: datetime.datetime | None = None,
) -> dict[str, str]:
    """Build AWS Signature Version 4 headers for an Amazon Rekognition JSON-RPC POST request."""
    service = "rekognition"
    host = f"{service}.{region}.amazonaws.com"
    content_type = "application/x-amz-json-1.1"
    utc_now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = utc_now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = utc_now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(payload).hexdigest()

    headers_to_sign: dict[str, str] = {
        "content-type": content_type,
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-target": target,
    }
    if session_token:
        headers_to_sign["x-amz-security-token"] = session_token

    sorted_keys = sorted(headers_to_sign.keys())
    canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)

    canonical_request = "\n".join(
        [
            "POST",
            "/",
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
        "X-Amz-Target": target,
        "Authorization": authorization,
    }
    if session_token:
        request_headers["X-Amz-Security-Token"] = session_token
    return request_headers


def evaluate_rekognition_labels(
    moderation_labels: list[dict[str, Any]],
    *,
    min_confidence: float = 60.0,
    block_alcohol: bool = False,
) -> ImageModerationResult:
    """
    Evaluate raw AWS Rekognition ModerationLabels against Shoppin's food-safe policy.

    Returns:
        ImageModerationResult with status="rejected" if any prohibited label meets its
        category threshold, else status="approved".
    """
    flagged: list[dict[str, Any]] = []
    explicit_threshold = min_confidence
    violence_threshold = max(65.0, min_confidence)
    age_threshold = max(70.0, min_confidence)
    suggestive_threshold = max(75.0, min_confidence)

    for label in moderation_labels or []:
        name = str(label.get("Name") or "").strip()
        parent = str(label.get("ParentName") or "").strip()
        try:
            confidence = float(label.get("Confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        name_l = name.lower()
        parent_l = parent.lower()

        is_match = False
        if (name_l in EXPLICIT_NUDITY_LABELS or parent_l in EXPLICIT_NUDITY_LABELS) and confidence >= explicit_threshold:
            is_match = True
        elif (name_l in SUGGESTIVE_LABELS or parent_l in SUGGESTIVE_LABELS) and confidence >= suggestive_threshold:
            is_match = True
        elif (name_l in VIOLENCE_AND_HATE_LABELS or parent_l in VIOLENCE_AND_HATE_LABELS) and confidence >= violence_threshold:
            is_match = True
        elif (name_l in AGE_RESTRICTED_LABELS or parent_l in AGE_RESTRICTED_LABELS) and confidence >= age_threshold:
            is_match = True
        elif block_alcohol and (name_l in ALCOHOL_LABELS or parent_l in ALCOHOL_LABELS) and confidence >= age_threshold:
            is_match = True

        if is_match:
            flagged.append({"name": name, "parent": parent, "confidence": round(confidence, 1)})

    if flagged:
        return ImageModerationResult(
            status="rejected",
            matched_labels=flagged,
            reason=REJECTION_USER_MESSAGE,
        )

    return ImageModerationResult(status="approved")


def moderate_image_bytes(image_bytes: bytes) -> ImageModerationResult:
    """
    Screen raw JPEG/PNG image bytes using Amazon Rekognition DetectModerationLabels.

    Returns:
        - status="approved": Image passed Rekognition moderation (or moderation disabled in dev/tests).
        - status="rejected": Image triggered explicit/violent/age-restricted moderation labels.
        - status="pending_review": Moderation enabled, but AWS credentials are missing or Rekognition
          could not be reached; caller should hold image as unapproved for moderator review.
    """
    if not getattr(settings, "IMAGE_MODERATION_ENABLED", False):
        return ImageModerationResult(status="approved")

    access_key = (getattr(settings, "AWS_ACCESS_KEY_ID", "") or "").strip()
    secret_key = (getattr(settings, "AWS_SECRET_ACCESS_KEY", "") or "").strip()
    session_token = (getattr(settings, "AWS_SESSION_TOKEN", "") or "").strip()
    region = (getattr(settings, "AWS_REKOGNITION_REGION", "") or "us-east-1").strip()
    min_confidence = float(getattr(settings, "IMAGE_MODERATION_MIN_CONFIDENCE", 60.0))
    block_alcohol = bool(getattr(settings, "IMAGE_MODERATION_BLOCK_ALCOHOL", False))

    if not access_key or not secret_key:
        logger.warning(
            "Image moderation is enabled but AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are not configured; "
            "holding uploaded photo for manual moderator review."
        )
        return ImageModerationResult(
            status="pending_review",
            reason="Automated image screening is temporarily unavailable; photo held for moderator review.",
        )

    payload_dict = {
        "Image": {"Bytes": base64.b64encode(image_bytes).decode("ascii")},
        "MinConfidence": min_confidence,
    }
    payload = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    headers = _sign_aws_v4_rekognition_headers(
        payload=payload,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
    )
    endpoint = f"https://rekognition.{region}.amazonaws.com/"

    try:
        resp = requests.post(
            endpoint,
            data=payload,
            headers=headers,
            timeout=REKOGNITION_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("AWS Rekognition request failed (%s); holding photo for moderator review.", exc)
        return ImageModerationResult(
            status="pending_review",
            reason="Automated image screening is temporarily unavailable; photo held for moderator review.",
        )

    if resp.status_code != 200:
        logger.warning(
            "AWS Rekognition returned HTTP %s (%s); holding photo for moderator review.",
            resp.status_code,
            (resp.text or "")[:300],
        )
        return ImageModerationResult(
            status="pending_review",
            reason="Automated image screening is temporarily unavailable; photo held for moderator review.",
        )

    try:
        data = resp.json()
    except ValueError:
        logger.warning("AWS Rekognition returned invalid JSON; holding photo for moderator review.")
        return ImageModerationResult(
            status="pending_review",
            reason="Automated image screening is temporarily unavailable; photo held for moderator review.",
        )

    labels = data.get("ModerationLabels", [])
    result = evaluate_rekognition_labels(
        labels,
        min_confidence=min_confidence,
        block_alcohol=block_alcohol,
    )
    if result.status == "rejected":
        logger.warning(
            "Rejected uploaded image via AWS Rekognition moderation labels: %s",
            result.matched_labels,
        )
    return result
