"""Tests for text normalization and hashing."""

from nasvetlo.utils.text import normalize_text, content_hash, slugify, transliterate_bg, extract_domain


class TestNormalizeText:
    def test_strips_html(self):
        assert normalize_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        assert normalize_text("  hello   world  ") == "hello world"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_preserves_cyrillic(self):
        assert normalize_text("Привет мир") == "Привет мир"

    def test_strips_nested_html(self):
        assert normalize_text("<div><p>text</p></div>") == "text"


class TestContentHash:
    def test_deterministic(self):
        h1 = content_hash("Title", "Summary")
        h2 = content_hash("Title", "Summary")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = content_hash("Title", "Summary")
        h2 = content_hash("TITLE", "SUMMARY")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = content_hash("Title A", "Summary A")
        h2 = content_hash("Title B", "Summary B")
        assert h1 != h2

    def test_sha256_length(self):
        h = content_hash("test", "test")
        assert len(h) == 64

    def test_whitespace_normalization(self):
        h1 = content_hash("Title  with  spaces", "Summary")
        h2 = content_hash("Title with spaces", "Summary")
        assert h1 == h2


class TestSlugify:
    def test_basic_latin(self):
        assert slugify("Hello World") == "hello-world"

    def test_bulgarian(self):
        slug = slugify("Привет мир")
        assert slug == "privet-mir"

    def test_max_length(self):
        long = "a" * 300
        assert len(slugify(long)) <= 200

    def test_special_chars(self):
        assert slugify("hello@world!") == "helloworld"

    def test_multiple_hyphens(self):
        assert slugify("hello - - world") == "hello-world"


class TestTransliterateBg:
    def test_basic(self):
        assert transliterate_bg("България") == "Balgariya"

    def test_mixed(self):
        assert transliterate_bg("Hello Свят") == "Hello Svyat"

    def test_special_combos(self):
        assert transliterate_bg("щ") == "sht"
        assert transliterate_bg("ю") == "yu"
        assert transliterate_bg("я") == "ya"


class TestExtractDomain:
    def test_simple(self):
        assert extract_domain("https://dnevnik.bg/article/123") == "dnevnik.bg"

    def test_www_prefix(self):
        assert extract_domain("https://www.capital.bg/rss") == "capital.bg"

    def test_no_scheme(self):
        assert extract_domain("dnevnik.bg") == ""

    def test_subdomain(self):
        assert extract_domain("https://news.example.com/path") == "news.example.com"
