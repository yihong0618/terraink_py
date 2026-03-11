from __future__ import annotations

TEXT_DIMENSION_REFERENCE_PX = 3600
TEXT_CITY_Y_RATIO = 0.845
TEXT_DIVIDER_Y_RATIO = 0.875
TEXT_COUNTRY_Y_RATIO = 0.9
TEXT_COORDS_Y_RATIO = 0.93
TEXT_EDGE_MARGIN_RATIO = 0.02
CITY_TEXT_SHRINK_THRESHOLD = 10
CITY_FONT_BASE_PX = 250
CITY_FONT_MIN_PX = 110
COUNTRY_FONT_BASE_PX = 92
COORDS_FONT_BASE_PX = 58
ATTRIBUTION_FONT_BASE_PX = 30
DEFAULT_FONT_FAMILY = "Space Grotesk"
DEFAULT_MONO_FAMILY = "IBM Plex Mono"
CREATOR_CREDIT = "created with terraink.app"


def is_latin_script(text: str | None) -> bool:
    if not text:
        return True
    latin_count = 0
    alpha_count = 0
    for char in text:
        if char.isascii() and char.isalpha():
            latin_count += 1
            alpha_count += 1
        elif char.isalpha():
            alpha_count += 1
    if alpha_count == 0:
        return True
    return latin_count / alpha_count > 0.8


def contains_cjk(text: str | None) -> bool:
    if not text:
        return False
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def format_city_label(city: str) -> str:
    if is_latin_script(city):
        return "  ".join(city.upper())
    return city


def infer_text_language(*values: str | None) -> str:
    for value in values:
        if not value:
            continue
        if contains_cjk(value):
            return "zh"
        if is_latin_script(value):
            return "en"
    return "en"
