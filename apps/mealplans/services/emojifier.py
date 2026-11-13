"""
Emojifier service for automatically decorating meal names with relevant culinary emojis.

Matches meal name keywords against culinary emoji patterns, reproducing legacy behavior.
"""

import re

# Keyword regex patterns mapped to Unicode food emojis
EMOJI_PATTERNS = [
    (r"(?i)\bspicy\b", "🌶️"),
    (r"(?i)\bhot\s?dog(s)?\b", "🌭"),
    (r"(?i)\btaco(s)?\b", "🌮"),
    (r"(?i)\bburrito(s)?\b", "🌯"),
    (r"(?i)\bchipotle\b", "🌯"),
    (r"(?i)\bburger(s)?\b", "🍔"),
    (r"(r?i)\bveggieburger(s)?\b", "🍔"),
    (r"(?i)\bsloppy\s?joe(s)?\b", "🍔"),
    (r"(?i)\btofu\s?joe(s)?\b", "🍔"),
    (r"(?i)\bpizza(s)?\b", "🍕"),
    (r"(?i)\bchicken(s)?\b", "🍗"),
    (r"(?i)\bstir( )?fry(s)?\b", "🍜"),
    (r"(?i)\bspaghetti\b", "🍝"),
    (r"(?i)\bnoodle(s)?\b", "🍝"),
    (r"(?i)\bsushi\b", "🍣"),
    (r"(?i)\bshrimp\b", "🍤"),
    (r"(?i)\bfried\s?egg(s)?\b", "🍳"),
    (r"(?i)\bbacon\b", "🥓"),
    (r"(?i)\bsalad(s)?\b", "🥗"),
    (r"(?i)\bpancake(s)?\b", "🥞"),
    (r"(?i)\bwaffle(s)?\b", "🧇"),
    (r"(?i)\bsoup(s)?\b", "🍲"),
    (r"(?i)\bkharcho\b", "🍲"),
    (r"(?i)\bminestrone\b", "🍲"),
    (r"(?i)\bpie(s)?\b", "🥧"),
    (r"(?i)\bsteak(s)?\b", "🥩"),
    (r"(?i)\bmeatloaf(s)?\b", "🥩"),
    (r"(?i)\bsandwich(es)?\b", "🥪"),
    (r"(?i)\bcheese(s)?\b", "🧀"),
    (r"(?i)\bcorn\b", "🌽"),
    (r"(?i)\besquites\b", "🌽"),
    (r"(?i)\bmushroom(s)?\b", "🍄"),
    (r"(?i)\btomato(es)?\b", "🍅"),
    (r"(?i)\baubergine(s)?\b", "🍆"),
    (r"(?i)\beggplant(s)?\b", "🍆"),
    (r"(?i)\bavocado(s)?\b", "🥑"),
    (r"(?i)\bguacamole\b", "🥑"),
    (r"(?i)\bcucumber(s)?\b", "🥒"),
    (r"(?i)\bpotato(es)?\b", "🥔"),
    (r"(?i)\bgnocci\b", "🥔"),
    (r"(?i)\bhashbrown(s)?\b", "🥔"),
    (r"(?i)\bcarrot(s)?\b", "🥕"),
    (r"(?i)\bbroccoli\b", "🥦"),
    (r"(?i)\bgarlic\b", "🧄"),
    (r"(?i)\bonion(s)?\b", "🧅"),
    (r"(?i)\bkale\b", "🥬"),
    (r"(?i)\bbanana(s)?\b", "🍌"),
    (r"(?i)\bbread(s)?\b", "🍞"),
    (r"(?i)\bfish\b", "🐟"),
    (r"(?i)\bsardine(s)?\b", "🐟"),
    (r"(?i)\btuna\b", "🐟"),
    (r"(?i)\bbrisket\b", "🍖"),
    (r"(?i)\bpork\b", "🍖"),
    (r"(?i)\bbean(s)?\b", "🫘"),
    (r"(?i)\bcasserole(s)?\b", "🥘"),
    (r"(?i)\btake( )?out\b", "👨‍🍳"),
    (r"(?i)\bbreakfast(s)?\b", "🍳"),
    (r"(?i)\bbirthday\b", "🎂"),
    (r"(?i)\bcookie(s)?\b", "🍪"),
    (r"(?i)\bcamping\b", "🏕️"),
]


def get_meal_emoji(name: str) -> str:
    """
    Generate matched emoji string for a given meal or dish name.

    Args:
        name: Name of the meal or recipe (e.g. 'Monday Taco Night', 'Veggie Soup').

    Returns:
        String of matched emojis (e.g. '🌮') or empty string if no keywords match.
    """
    if not name:
        return ""

    matched = []
    for pattern, emoji in EMOJI_PATTERNS:
        if re.search(pattern, name):
            if emoji not in matched:
                matched.append(emoji)

    return " ".join(matched)
