"""
Content Moderation & Anti-Profanity Service.

Detects and blocks expletives, obscenities, slurs, and hurtful language
across all content creation and mutation flows in Shoppin.
"""

import re
import unicodedata
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

# ---------------------------------------------------------------------------
# Prohibited Patterns: Expletives, Vulgarities, Slurs & Hurtful Language
# ---------------------------------------------------------------------------

PROHIBITED_PATTERNS = [
    # Fuck and variants (including masks like f*ck, f**k, f.u.c.k)
    r"\bf+u+c+k+(e+r+|i+n+g+|e+d+|s+|o+f+f+)?\b",
    r"\bf+[\*\@\#\$\%\^\&\_\.\-]+k+\b",
    r"\bf+[\*\@\#\$\%\^\&\_\.\-]+c+k+\b",
    r"\bm+o+t+h+e+r+f+u+c+k+(e+r+|i+n+g+|s+)?\b",
    # Shit and variants (including sh*t, sh!t, sht)
    r"\bs+h+i+t+(s+|t+y+|t+i+n+g+|t+e+d+|h+e+a+d+|h+e+a+d+s+)?\b",
    r"\bs+h+[\*\@\#\$\%\^\&\_\.\-]+t+\b",
    r"\bs+h+t+\b",
    r"\bb+u+l+l+s+h+i+t+\b",
    r"\bd+i+p+s+h+i+t+\b",
    # Bitch and variants (including b*tch, b!tch, bitchin)
    r"\bb+i+t+c+h+(e+s+|i+n+g+|i+n+|y+|a+s+s+)?\b",
    r"\bb+[\*\@\#\$\%\^\&\_\.\-]+t+c+h+\b",
    # Ass and offensive compound variants
    r"\ba+s+s+h+o+l+e+(s+)?\b",
    r"\ba+[\*\@\#\$\%\^\&\_\.\-]+h+o+l+e+(s+)?\b",
    r"\bd+u+m+b+a+s+s+(e+s+)?\b",
    r"\bj+a+c+k+a+s+s+(e+s+)?\b",
    r"\ba+s+s+h+a+t+(s+)?\b",
    r"\ba+s+s+c+l+o+w+n+(s+)?\b",
    r"\bb+a+d+a+s+s+(e+s+)?\b",
    r"\ba+s+s+(e+s+)?\b",
    # Bastard, Cunt, Pussy, Twat, Wanker, Whore, Slut
    r"\bb+a+s+t+a+r+d+(s+)?\b",
    r"\bc+u+n+t+(s+)?\b",
    r"\bc+[\*\@\#\$\%\^\&\_\.\-]+n+t+(s+)?\b",
    r"\bp+u+s+s+y+|p+u+s+s+i+e+s+\b",
    r"\bt+w+a+t+(s+)?\b",
    r"\bw+a+n+k+e+r+(s+)?\b",
    r"\bw+h+o+r+e+(s+)?\b",
    r"\bs+l+u+t+(s+|t+y+)?\b",
    r"\bc+o+c+k+s+u+c+k+e+r+(s+)?\b",
    r"\bc+o+c+k+(s+)?\b",
    r"\bd+i+c+k+h+e+a+d+(s+)?\b",
    r"\bd+i+c+k+(s+)?\b",
    r"\bd+[\*\@\#\$\%\^\&\_\.\-]+c+k+(s+)?\b",
    r"\bp+i+s+s+(e+d+|i+n+g+|e+s+)?\b",
    # Slurs / Hate Speech / Hurtful & Degenerate Language
    r"\bn+i+g+g+(e+r+|a+|a+s+|e+r+s+)\b",
    r"\bn+[\*\@\#\$\%\^\&\_\.\-]+g+g+(e+r+|a+|a+s+|e+r+s+)\b",
    r"\bf+a+g+g+o+t+(s+)?\b",
    r"\bf+a+g+(s+)?\b",
    r"\bd+y+k+e+(s+)?\b",
    r"\bk+i+k+e+(s+)?\b",
    r"\bc+h+i+n+k+(s+)?\b",
    r"\bs+p+i+c+(s+)?\b",
    r"\bw+e+t+b+a+c+k+(s+)?\b",
    r"\bg+o+o+k+(s+)?\b",
    r"\bt+r+a+n+n+y+|t+r+a+n+n+i+e+s+\b",
    r"\br+e+t+a+r+d+(e+d+|s+)?\b",
    # Hurtful / Violent abusive expressions
    r"\bk+i+l+l+\s+y+o+u+r+s+e+l+f+\b",
    r"\bk+y+s+\b",
    r"\bg+o+\s+d+i+e+\b",
    r"\bb+u+r+n+\s+i+n+\s+h+e+l+l+\b",
]

COMPILED_PROHIBITED = [re.compile(p, re.IGNORECASE) for p in PROHIBITED_PATTERNS]

# Whitelist allowed phrases (culinary terms, classical literature) to prevent Scunthorpe issues
ALLOWED_PHRASES = [
    r"\bspotted\s+dick\b",
    r"\bmoby\s+dick\b",
    r"\bdickens\b",
]
COMPILED_ALLOWED = [re.compile(p, re.IGNORECASE) for p in ALLOWED_PHRASES]

# Translation table for leetspeak and common character substitution evasion
LEET_TABLE = str.maketrans({
    "@": "a",
    "4": "a",
    "$": "s",
    "5": "s",
    "0": "o",
    "1": "i",
    "!": "i",
    "|": "i",
    "3": "e",
    "+": "t",
    "8": "b",
})


def normalize_text_for_moderation(text: str) -> str:
    """
    Normalize text by stripping unicode diacritics and translating leetspeak.
    Protects standalone numbers, decimals, currencies, times, and percentages from leetspeak
    translation to prevent innocent numerical ratings (e.g. '4.55') from being falsely flagged.
    """
    tokens = []
    for token in text.split(" "):
        if re.match(r"^[\$€£]?\d+([.,:\/\-]\d+)*[%]?$", token):
            tokens.append(token)
        else:
            normalized = unicodedata.normalize("NFKD", token)
            tokens.append(normalized.translate(LEET_TABLE))
    return " ".join(tokens)


def contains_obscene_language(text: str | None) -> tuple[bool, str | None]:
    """
    Check if a string contains any expletives, obscene terms, or hurtful language.

    Args:
        text: The string to inspect.

    Returns:
        A tuple of (is_obscene: bool, matched_token: str | None).
    """
    if not text or not isinstance(text, str):
        return False, None

    cleaned = text.strip()
    if not cleaned:
        return False, None

    # Blank out whitelisted phrases first so they don't trigger false positives
    for allowed_pat in COMPILED_ALLOWED:
        if allowed_pat.search(cleaned):
            cleaned = allowed_pat.sub(" ", cleaned)

    norm = normalize_text_for_moderation(cleaned)

    # 1. Direct regex scan against raw and normalized text
    for pat in COMPILED_PROHIBITED:
        match = pat.search(cleaned) or pat.search(norm)
        if match:
            return True, match.group(0)

    # 2. Check tokens stripped of internal punctuation (e.g. "f.u.c.k", "s-h-i-t")
    for token in cleaned.split():
        token_norm = normalize_text_for_moderation(token)
        stripped = re.sub(r"[^a-zA-Z]", "", token_norm)
        if stripped and len(stripped) > 2:
            for pat in COMPILED_PROHIBITED:
                match = pat.search(stripped)
                if match and match.group(0) == stripped:
                    return True, token

    return False, None


def validate_content_clean(text: str | None, field_label: str = "Content") -> None:
    """
    Validate that text does not contain obscene or hurtful language.

    Raises:
        ValidationError if prohibited language is detected.
    """
    is_obscene, word = contains_obscene_language(text)
    if is_obscene:
        raise ValidationError(
            f"{field_label} contains prohibited obscene or hurtful language. "
            f"Please revise your text to maintain a friendly, welcoming kitchen environment."
        )


# ---------------------------------------------------------------------------
# Model Field Inspection Registry
# ---------------------------------------------------------------------------

MONITORED_MODEL_FIELDS: dict[str, list[str]] = {
    "recipes.recipe": [
        "name",
        "description",
        "directions",
        "storage_instructions",
        "reheating_instructions",
        "cuisine",
        "dish_type",
    ],
    "recipes.ingredient": [
        "name",
        "brand",
        "vendor",
        "purpose",
    ],
    "recipes.recipecomment": [
        "comment",
    ],
    "recipes.recipemadelog": [
        "notes",
    ],
    "mealplans.mealplan": [
        "name",
    ],
    "mealplans.meal": [
        "name",
    ],
    "mealplans.mealplanrule": [
        "rule_text",
    ],
    "shopping.shoppinglist": [
        "name",
    ],
    "shopping.shoppinglistitem": [
        "name",
        "brand",
        "vendor",
        "purpose",
        "aisle",
    ],
    "core.workspace": [
        "name",
    ],
}


def check_model_instance_for_moderation(instance: Any) -> None:
    """
    Inspect registered text fields on a model instance and raise ValidationError
    if any field contains prohibited obscene or hurtful language.
    """
    if not isinstance(instance, models.Model):
        return

    model_label = instance._meta.label_lower
    fields_to_check = MONITORED_MODEL_FIELDS.get(model_label)
    if not fields_to_check:
        return

    for field_name in fields_to_check:
        val = getattr(instance, field_name, None)
        if isinstance(val, str) and val.strip():
            verbose_name = instance._meta.get_field(field_name).verbose_name or field_name
            validate_content_clean(
                val,
                field_label=f"{instance._meta.verbose_name.capitalize()} {verbose_name}",
            )
