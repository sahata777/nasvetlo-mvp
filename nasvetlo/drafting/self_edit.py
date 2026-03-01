"""Self-edit pass on article drafts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("drafting.self_edit")


class EditChecklist(BaseModel):
    accuracy: bool = True
    word_count_ok: bool = True
    balanced: bool = True
    attributed: bool = True
    language_ok: bool = True
    structure_ok: bool = True
    no_defamation: bool = True
    no_clickbait: bool = True


class EditResult(BaseModel):
    revised_article: str
    checklist: EditChecklist = Field(default_factory=EditChecklist)
    changes_made: list[str] = Field(default_factory=list)


def self_edit(article_text: str, source_facts_summary: str = "") -> EditResult:
    """Run self-edit pass on an article draft."""
    system_prompt = load_prompt("self_edit.txt")
    user_prompt = f"=== ARTICLE DRAFT ===\n{article_text}"
    if source_facts_summary:
        user_prompt += f"\n\n=== SOURCE DATA ===\n{source_facts_summary}"

    try:
        result_dict = call_llm_json(system=system_prompt, user=user_prompt)
        result = EditResult(**result_dict)
        log.info("Self-edit completed. Changes: %s", result.changes_made)
        return result
    except (ValueError, Exception) as e:
        log.error("Self-edit failed: %s. Using original article.", e)
        return EditResult(revised_article=article_text, changes_made=["self-edit failed, using original"])
