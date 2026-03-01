"""Article draft writer using LLM."""

from __future__ import annotations

from nasvetlo.drafting.synthesis import UnifiedFacts
from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, get_llm_provider

log = get_logger("drafting.writer")


def write_article(facts: UnifiedFacts) -> str:
    """Generate a Bulgarian article draft from unified facts."""
    system_prompt = load_prompt("article_writer.txt")

    # Build user prompt with all facts
    parts = []
    parts.append("=== ПОТВЪРДЕНИ ФАКТИ (от 2+ източника) ===")
    for f in facts.confirmed_facts:
        parts.append(f"- {f}")

    if facts.single_source_facts:
        parts.append("\n=== ФАКТИ ОТ ЕДИН ИЗТОЧНИК (отбележи източника) ===")
        for f in facts.single_source_facts:
            parts.append(f"- {f}")

    if facts.disputed_points:
        parts.append("\n=== СПОРНИ/НЕЯСНИ ТОЧКИ ===")
        for f in facts.disputed_points:
            parts.append(f"- {f}")

    if facts.timeline:
        parts.append("\n=== ДАТИ И ЧИСЛА ===")
        for t in facts.timeline:
            parts.append(f"- {t}")

    if facts.all_entities:
        parts.append("\n=== СПОМЕНАТИ ЛИЦА/ОРГАНИЗАЦИИ ===")
        parts.append(", ".join(facts.all_entities))

    parts.append(f"\n=== ИЗТОЧНИЦИ ===")
    parts.append(", ".join(facts.source_domains))

    user_prompt = "\n".join(parts)

    provider = get_llm_provider()
    response = provider.complete(
        system=system_prompt,
        user=user_prompt,
        temperature=0.4,
        max_tokens=4096,
    )

    article_text = response.text.strip()
    log.info("Generated article draft: %d chars", len(article_text))
    return article_text
