"""Named entity extraction from article text via LLM.

Extracts five entity types from a Bulgarian article:
    people, organizations, locations, companies, laws

Each entity carries a ``role`` field (subject / mentioned / location /
organization) that is propagated to the knowledge graph edge.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("entities.extractor")


class EntityItem(BaseModel):
    name: str
    role: str = "mentioned"


class ExtractionResult(BaseModel):
    people: list[EntityItem] = Field(default_factory=list)
    organizations: list[EntityItem] = Field(default_factory=list)
    locations: list[EntityItem] = Field(default_factory=list)
    companies: list[EntityItem] = Field(default_factory=list)
    laws: list[EntityItem] = Field(default_factory=list)

    def total(self) -> int:
        return (
            len(self.people)
            + len(self.organizations)
            + len(self.locations)
            + len(self.companies)
            + len(self.laws)
        )


def extract_entities(article_text: str) -> ExtractionResult:
    """Extract named entities from a Bulgarian article via LLM.

    Returns an ``ExtractionResult`` with all five entity type lists.
    On any failure, returns an empty result so the pipeline is never blocked.
    """
    system_prompt = load_prompt("entity_extractor.txt")

    # Limit input length — entity extraction does not need the full
    # context sections appended by Phase 4; use the first 3000 chars
    # of the article to keep prompt costs low.
    truncated = article_text[:3000]

    try:
        raw = call_llm_json(system=system_prompt, user=truncated)
        result = ExtractionResult(**raw)
        log.info(
            "Extracted %d entities: %d people, %d orgs, %d locations, "
            "%d companies, %d laws",
            result.total(),
            len(result.people),
            len(result.organizations),
            len(result.locations),
            len(result.companies),
            len(result.laws),
        )
        return result
    except Exception as e:
        log.error("Entity extraction failed: %s. Returning empty result.", e)
        return ExtractionResult()
