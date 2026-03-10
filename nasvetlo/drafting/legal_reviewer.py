"""Legal safety review — second-pass LLM review for defamation, privacy, and attribution risk.

Runs after the existing keyword + LLM safety gate, but only when the article
contains named entities or keyword flags (to avoid unnecessary LLM spend on
clearly safe articles).

Produces a structured issue list with per-issue redaction/rephrasing suggestions.
Results are stored in ``generated_article.legal_risk_json``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("drafting.legal_reviewer")

# Risk categories
LEGAL_CATEGORIES = frozenset(
    {"defamation", "privacy", "attribution", "misleading", "copyright"}
)


class LegalIssue(BaseModel):
    category: str = "attribution"
    severity: str = "low"
    excerpt: str = ""
    explanation: str = ""
    suggestion: str = ""


class LegalReviewResult(BaseModel):
    risk_level: str = "low"           # low | medium | high
    issues: list[LegalIssue] = Field(default_factory=list)
    recommended_action: str = "publish"   # publish | review | reject
    summary: str = ""

    @property
    def needs_review(self) -> bool:
        return self.recommended_action in ("review", "reject")


def _should_run(article_text: str, safety_flags: list[str], entity_names: list[str]) -> bool:
    """Determine if legal review is warranted.

    Triggers if:
    - The existing safety gate already flagged something, OR
    - The article mentions at least one named person/entity
    """
    if safety_flags:
        return True
    if entity_names:
        return True
    # Heuristic: presence of Bulgarian personal name patterns (capitalised words)
    words = article_text.split()
    capitalised = [w for w in words if w and w[0].isupper() and len(w) > 2]
    return len(capitalised) >= 3


def run_legal_review(
    article_text: str,
    safety_flags: list[str],
    entity_names: list[str] | None = None,
) -> LegalReviewResult | None:
    """Run LLM legal review if warranted. Returns None if skipped.

    Args:
        article_text: Full article text.
        safety_flags: Flags from the existing safety gate.
        entity_names: Named entities extracted in Phase 5 (people/orgs).

    Returns:
        LegalReviewResult or None (if skipped as unnecessary).
    """
    entity_names = entity_names or []

    if not _should_run(article_text, safety_flags, entity_names):
        log.debug("Legal review skipped — no triggering conditions.")
        return None

    system_prompt = load_prompt("legal_reviewer.txt")
    # Truncate to 3000 chars — enough for full legal assessment
    truncated = article_text[:3000]

    try:
        raw = call_llm_json(system=system_prompt, user=truncated)
        result = LegalReviewResult(**raw)

        log.info(
            "Legal review: risk=%s, issues=%d, action=%s",
            result.risk_level,
            len(result.issues),
            result.recommended_action,
        )
        return result

    except Exception as e:
        log.warning("Legal review failed: %s", e)
        # Conservative fallback — flag for human review
        return LegalReviewResult(
            risk_level="medium",
            issues=[],
            recommended_action="review",
            summary="Автоматичната правна проверка не успя — препоръчва се редакторски преглед.",
        )
