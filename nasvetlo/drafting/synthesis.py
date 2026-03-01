"""Merge facts from multiple source summaries into a unified fact set."""

from __future__ import annotations

from dataclasses import dataclass, field

from nasvetlo.drafting.source_summaries import SourceSummary
from nasvetlo.logging_utils import get_logger

log = get_logger("drafting.synthesis")


@dataclass
class UnifiedFacts:
    confirmed_facts: list[str] = field(default_factory=list)
    single_source_facts: list[str] = field(default_factory=list)
    disputed_points: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    all_entities: list[str] = field(default_factory=list)
    source_domains: list[str] = field(default_factory=list)


def merge_facts(summaries: list[SourceSummary]) -> UnifiedFacts:
    """Programmatically merge facts from multiple sources."""
    all_facts: dict[str, int] = {}
    all_entities: set[str] = set()
    all_numbers_dates: list[str] = []
    source_domains: list[str] = []

    for s in summaries:
        source_domains.append(s.source_domain)
        for entity in s.entities:
            all_entities.add(entity)
        all_numbers_dates.extend(s.numbers_dates)
        for fact in s.key_facts:
            normalized = fact.strip().lower()
            if normalized:
                all_facts[normalized] = all_facts.get(normalized, 0) + 1

    confirmed = []
    single_source = []

    for fact_lower, count in all_facts.items():
        # Find original casing
        original = fact_lower
        for s in summaries:
            for f in s.key_facts:
                if f.strip().lower() == fact_lower:
                    original = f.strip()
                    break

        if count >= 2:
            confirmed.append(original)
        else:
            single_source.append(original)

    # Disputed = facts in uncertainties
    disputed = []
    for s in summaries:
        disputed.extend(s.uncertainties)

    unified = UnifiedFacts(
        confirmed_facts=confirmed,
        single_source_facts=single_source,
        disputed_points=list(set(disputed)),
        timeline=sorted(set(all_numbers_dates)),
        all_entities=sorted(all_entities),
        source_domains=list(set(source_domains)),
    )

    log.info(
        "Merged facts: %d confirmed, %d single-source, %d disputed",
        len(unified.confirmed_facts),
        len(unified.single_source_facts),
        len(unified.disputed_points),
    )
    return unified
