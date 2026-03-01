"""Text normalization, hashing, slugification."""

from __future__ import annotations

import hashlib
import re
import unicodedata


# Bulgarian Cyrillic to Latin transliteration map
_BG_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sht", "ъ": "a", "ь": "", "ю": "yu", "я": "ya",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E",
    "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L",
    "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S",
    "Т": "T", "У": "U", "Ф": "F", "Х": "H", "Ц": "Ts", "Ч": "Ch",
    "Ш": "Sh", "Щ": "Sht", "Ъ": "A", "Ь": "", "Ю": "Yu", "Я": "Ya",
}


def normalize_text(text: str) -> str:
    """Normalize whitespace and strip HTML tags."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def content_hash(title: str, summary: str) -> str:
    """SHA-256 hash of normalized title + summary."""
    combined = normalize_text(title).lower() + "|" + normalize_text(summary).lower()
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def transliterate_bg(text: str) -> str:
    """Transliterate Bulgarian Cyrillic to ASCII Latin."""
    result: list[str] = []
    for ch in text:
        result.append(_BG_TRANSLIT.get(ch, ch))
    return "".join(result)


def slugify(text: str, max_length: int = 200) -> str:
    """Create a URL-safe slug from text (supports Bulgarian)."""
    text = transliterate_bg(text.lower())
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:max_length]


def extract_domain(url: str) -> str:
    """Extract domain from URL (e.g., 'dnevnik.bg' from 'https://www.dnevnik.bg/path')."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or ""
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.lower()
