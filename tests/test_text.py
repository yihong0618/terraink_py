from __future__ import annotations


from terraink_py.text import (
    contains_cjk,
    format_city_label,
    infer_text_language,
    is_latin_script,
    CITY_FONT_BASE_PX,
    CITY_FONT_MIN_PX,
    DEFAULT_FONT_FAMILY,
    DEFAULT_MONO_FAMILY,
)


class TestIsLatinScript:
    def test_empty_string(self) -> None:
        assert is_latin_script("") is True

    def test_none_input(self) -> None:
        assert is_latin_script(None) is True

    def test_pure_latin(self) -> None:
        assert is_latin_script("Beijing") is True
        assert is_latin_script("New York") is True
        assert is_latin_script("Paris") is True

    def test_pure_cjk(self) -> None:
        assert is_latin_script("北京") is False
        assert is_latin_script("東京") is False
        assert is_latin_script("서울") is False  # Korean

    def test_mixed_scripts(self) -> None:
        # Mostly Latin with some CJK should be False
        assert is_latin_script("Beijing北京") is False

    def test_numbers_and_punctuation(self) -> None:
        assert is_latin_script("NYC-123") is True
        assert is_latin_script("Beijing, China") is True

    def test_various_languages(self) -> None:
        # European languages with Latin script
        assert is_latin_script("München") is True  # German
        assert is_latin_script("São Paulo") is True  # Portuguese
        assert is_latin_script("Île-de-France") is True  # French


class TestContainsCJK:
    def test_empty_string(self) -> None:
        assert contains_cjk("") is False

    def test_none_input(self) -> None:
        assert contains_cjk(None) is False

    def test_no_cjk(self) -> None:
        assert contains_cjk("Beijing") is False
        assert contains_cjk("New York 123") is False
        assert contains_cjk("São Paulo") is False

    def test_contains_cjk(self) -> None:
        assert contains_cjk("北京") is True
        assert contains_cjk("東京") is True
        assert contains_cjk("Beijing北京") is True

    def test_cjk_punctuation_not_counted(self) -> None:
        # CJK punctuation and symbols should not be counted
        assert contains_cjk("Hello。") is False  # 。is punctuation


class TestFormatCityLabel:
    def test_latin_script_spacing(self) -> None:
        # Latin script should have spaces between letters
        result = format_city_label("Beijing")
        assert result == "B  E  I  J  I  N  G"

    def test_cjk_no_spacing(self) -> None:
        # CJK should not have spacing
        result = format_city_label("北京")
        assert result == "北京"

    def test_multi_word_city(self) -> None:
        result = format_city_label("New York")
        assert "N" in result
        assert "Y" in result
        assert len(result) > len("New York")

    def test_empty_string(self) -> None:
        result = format_city_label("")
        assert result == ""


class TestInferTextLanguage:
    def test_prefers_english_for_latin_text(self) -> None:
        assert infer_text_language("Georges River Council") == "en"

    def test_prefers_chinese_for_cjk_text(self) -> None:
        assert infer_text_language("澳大利亚") == "zh"

    def test_uses_first_meaningful_text(self) -> None:
        assert infer_text_language("München", "中国") == "en"

    def test_defaults_to_english(self) -> None:
        assert infer_text_language(None, "", "12345") == "en"


class TestConstants:
    def test_font_constants(self) -> None:
        assert CITY_FONT_BASE_PX > CITY_FONT_MIN_PX
        assert CITY_FONT_BASE_PX > 0
        assert CITY_FONT_MIN_PX > 0

    def test_font_families(self) -> None:
        assert isinstance(DEFAULT_FONT_FAMILY, str)
        assert isinstance(DEFAULT_MONO_FAMILY, str)
        assert len(DEFAULT_FONT_FAMILY) > 0
        assert len(DEFAULT_MONO_FAMILY) > 0
