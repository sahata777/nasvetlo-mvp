"""Headline optimization — generate and score CTR-optimized headline variants.

For each drafted article, generates a configurable number of headline variants
scored on clarity, curiosity, SEO, and urgency.  The highest-scoring variant
replaces the original LLM-generated title.  All variants are stored in
``generated_article.headline_variants_json`` for future A/B testing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("drafting.headline_optimizer")


class HeadlineVariant(BaseModel):
    headline: str
    clarity: float = 0.0
    curiosity: float = 0.0
    seo: float = 0.0
    urgency: float = 0.0
    total: float = 0.0


class HeadlineOptimizerResult(BaseModel):
    variants: list[HeadlineVariant] = Field(default_factory=list)
    selected: int = 0

    @property
    def best_headline(self) -> str | None:
        if not self.variants:
            return None
        idx = max(0, min(self.selected, len(self.variants) - 1))
        return self.variants[idx].headline


def optimize_headline(
    article_title: str,
    article_text: str,
) -> HeadlineOptimizerResult:
    """Generate headline variants and return the best one.

    Returns a result with the original title as sole variant on failure,
    so the pipeline is never blocked.
    """
    system_prompt = load_prompt("headline_optimizer.txt")

    # Truncate body — first 1500 chars is enough context for headline generation
    truncated = article_text[:1500]
    user_prompt = (
        f"Original title: {article_title}\n\n"
        f"Article:\n{truncated}"
    )

    try:
        raw = call_llm_json(system=system_prompt, user=user_prompt)
        result = HeadlineOptimizerResult(**raw)

        if not result.variants:
            raise ValueError("No variants returned")

        # Recompute totals in case LLM miscalculated
        for v in result.variants:
            v.total = v.clarity + v.curiosity + v.seo + v.urgency

        # Re-select best by computed total
        best_idx = max(range(len(result.variants)), key=lambda i: result.variants[i].total)
        result.selected = best_idx

        log.info(
            "Headline optimized: '%s' → '%s' (score=%.1f)",
            article_title,
            result.best_headline,
            result.variants[best_idx].total,
        )
        return result

    except Exception as e:
        log.warning("Headline optimization failed for '%s': %s", article_title, e)
        # Fallback: return original title as sole variant
        fallback = HeadlineVariant(headline=article_title, total=0.0)
        return HeadlineOptimizerResult(variants=[fallback], selected=0)
