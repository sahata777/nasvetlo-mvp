"""Safety gating: rule-based + LLM classifier."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("drafting.safety")


class SafetyResult(BaseModel):
    risk_level: str = "low"  # low | medium | high
    flags: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)


def rule_based_scan(text: str, config: AppConfig) -> list[str]:
    """Scan text for high-risk and defamation keywords."""
    flags: list[str] = []
    text_lower = text.lower()

    for kw in config.safety.defamation_keywords:
        if kw.lower() in text_lower:
            flags.append(f"defamation_keyword: {kw}")

    # Check for unattributed accusations
    high_risk_hits = []
    for kw in config.safety.high_risk_keywords:
        if kw.lower() in text_lower:
            high_risk_hits.append(kw)
    if high_risk_hits:
        flags.append(f"high_risk_keywords: {', '.join(high_risk_hits)}")

    return flags


def llm_safety_check(article_text: str) -> SafetyResult:
    """Run LLM safety classifier."""
    system_prompt = load_prompt("safety_classifier_json.txt")
    try:
        result_dict = call_llm_json(system=system_prompt, user=article_text)
        return SafetyResult(**result_dict)
    except (ValueError, Exception) as e:
        log.error("LLM safety check failed: %s. Defaulting to high risk.", e)
        return SafetyResult(
            risk_level="high",
            flags=[f"LLM safety check failed: {e}"],
            required_actions=["Manual review required - safety check error"],
        )


def full_safety_gate(article_text: str, config: AppConfig) -> SafetyResult:
    """Run full safety pipeline: rule-based + LLM."""
    # Rule-based scan
    rule_flags = rule_based_scan(article_text, config)

    # LLM classifier
    llm_result = llm_safety_check(article_text)

    # Merge flags
    all_flags = rule_flags + llm_result.flags

    # Escalate risk level if rule-based found defamation
    risk_level = llm_result.risk_level
    if any("defamation" in f for f in rule_flags):
        risk_level = "high"
    elif rule_flags and risk_level == "low":
        risk_level = "medium"

    return SafetyResult(
        risk_level=risk_level,
        flags=all_flags,
        required_actions=llm_result.required_actions,
    )
