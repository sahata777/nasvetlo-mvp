# Architecture Decision Records

## ADR-001: SQLite as Primary Database

**Status**: Accepted

**Context**: MVP needs simple, zero-dependency persistence. Expected volume is ~1000 articles/day.

**Decision**: Use SQLite with SQLAlchemy ORM. Store embeddings as JSON text.

**Consequences**: Simple deployment (single file). Limited concurrent writes (acceptable for single-pipeline architecture). Easy to migrate to PostgreSQL later by changing `DATABASE_URL`.

## ADR-002: Local Embeddings Default

**Status**: Accepted

**Context**: Need multilingual embeddings for Bulgarian text similarity. External API calls add latency and cost.

**Decision**: Default to `sentence-transformers` with `paraphrase-multilingual-MiniLM-L12-v2`. Clean `EmbeddingProvider` interface allows swapping to remote APIs.

**Consequences**: Requires ~500MB model download on first run. Works offline. Lower latency than API calls. Quality sufficient for news clustering.

## ADR-003: Provider-Agnostic LLM Interface

**Status**: Accepted

**Context**: LLM market is evolving. Need flexibility to switch providers.

**Decision**: Abstract `LLMProvider` base class with `AnthropicProvider` and `OpenAIProvider` implementations. Provider selected via config.

**Consequences**: Easy to add new providers. Slightly more complex than direct API calls. Mock provider enables testing without network.

## ADR-004: Never Auto-Publish

**Status**: Accepted (Hard Constraint)

**Context**: Automated news generation carries risk of factual errors, bias, or defamatory content.

**Decision**: All WordPress posts created with `status: pending`. No code path allows `status: publish`. This is enforced at the WordPress client level.

**Consequences**: Every article requires human editorial review before going live. Adds editorial overhead but eliminates publication risk.

## ADR-005: Minimum 3 Independent Sources

**Status**: Accepted (Hard Constraint)

**Context**: Single-source stories carry high risk of misinformation or manipulation.

**Decision**: Clusters must have ≥3 unique domains before becoming drafting candidates. This is checked at the clustering level.

**Consequences**: Reduces false stories. May miss legitimate exclusives. Acceptable trade-off for MVP.

## ADR-006: Prompt Files Separated from Code

**Status**: Accepted

**Context**: Prompts are the most frequently tuned component. Need to iterate without code changes.

**Decision**: All LLM prompts stored as `.txt` files in `nasvetlo/prompts/`. Loaded at runtime.

**Consequences**: Easy to edit and version-track prompts. No code deployment needed for prompt changes. Slightly more file I/O (negligible).

## ADR-007: Auto-Pause Safety Mechanism

**Status**: Accepted

**Context**: Unattended pipelines can fail in loops or produce problematic content.

**Decision**: Auto-pause after 3 consecutive failures OR 3 high-risk articles in 24 hours. Manual resume required via CLI.

**Consequences**: Prevents runaway error loops. Requires operator intervention to resume. Acceptable for MVP with human oversight.

## ADR-008: Daily Cap of 8 Drafts

**Status**: Accepted

**Context**: Need to limit LLM costs and editorial workload.

**Decision**: Maximum 8 drafts per calendar day (UTC). Configurable in YAML.

**Consequences**: Limits costs. Prioritizes most important events. May miss lower-importance stories on busy news days.
