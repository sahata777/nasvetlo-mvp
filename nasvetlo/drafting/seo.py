"""SEO fields generation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("drafting.seo")


class SEOFields(BaseModel):
    seo_title: str = ""
    meta_description: str = ""
    slug: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = "общество"


def generate_seo(article_text: str, config: AppConfig) -> SEOFields:
    """Generate SEO fields for an article."""
    system_prompt = load_prompt("seo_fields_json.txt")

    try:
        result_dict = call_llm_json(system=system_prompt, user=article_text[:3000])
        seo = SEOFields(**result_dict)
    except (ValueError, Exception) as e:
        log.error("SEO generation failed: %s", e)
        # Fallback: extract title from first line
        lines = article_text.strip().split("\n")
        title = lines[0][:60] if lines else "Новина"
        from nasvetlo.utils.text import slugify
        seo = SEOFields(
            seo_title=title,
            meta_description=title[:155],
            slug=slugify(title),
            tags=[],
            category="общество",
        )

    # Map category to ID
    category_map = config.web.category_map
    if seo.category in category_map:
        seo_category_id = category_map[seo.category]
    else:
        seo_category_id = config.web.default_category_id

    # Store category_id on the SEO object as extra info
    # (will be used by the caller)
    log.info("SEO generated: title=%s, slug=%s, category=%s", seo.seo_title, seo.slug, seo.category)
    return seo
