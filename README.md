# На Светло (NA SVETLO) – MVP

Automated Bulgarian news aggregation pipeline. Ingests RSS feeds, clusters articles into events, scores importance, generates Bulgarian-language drafts, and creates WordPress pending posts for editorial review.

**Key safety constraint: never auto-publishes.** All WordPress posts are created with `status: pending`.

## Quick Start

```bash
# 1. Clone and enter
cd nasvetlo-mvp

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
cp config.example.yaml config.yaml
# Edit .env with your API keys
# Edit config.yaml with your RSS sources and WordPress details

# 5. Run dry-run (no WordPress calls)
python -m nasvetlo.cli run-once --dry-run

# 6. Run tests
pytest tests/ -v
```

## CLI Commands

```bash
# Single pipeline run (dry-run, no WP publishing)
python -m nasvetlo.cli run-once --dry-run

# Single pipeline run (live, creates pending WP posts)
python -m nasvetlo.cli run-once

# Limit drafts per run
python -m nasvetlo.cli run-once --dry-run --max 3

# Daemon mode (runs every 40 min by default)
python -m nasvetlo.cli daemon

# Check status
python -m nasvetlo.cli status

# Pause/resume
python -m nasvetlo.cli pause
python -m nasvetlo.cli resume

# Backfill (re-process last N hours)
python -m nasvetlo.cli backfill --hours 48
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | Anthropic API key |
| `OPENAI_API_KEY` | Alt* | OpenAI API key (if using OpenAI provider) |
| `WP_APPLICATION_PASSWORD` | For live | WordPress application password |
| `DATABASE_URL` | No | SQLite URL (default: `sqlite:///nasvetlo.db`) |
| `NASVETLO_CONFIG` | No | Path to config YAML (default: `config.yaml`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token (optional) |

\* One LLM provider key is required.

## Configuration

Edit `config.yaml` to configure:

- **sources**: RSS feeds with tier (1-4) and credibility scores
- **thresholds**: similarity, min sources, time windows, importance cutoff
- **scoring_weights**: formula weights for importance calculation
- **schedule**: scan interval and daily draft cap
- **safety**: keyword lists for risk detection
- **wordpress**: WP REST API connection details
- **llm**: provider, model, temperature

### Adding Sources Safely

1. Add the source to `config.yaml` under `sources:`
2. Set `tier` (1=institutional, 2=quality, 3=mainstream, 4=tabloid)
3. Set `credibility_score` (0.0-1.0)
4. Set `enabled: true`
5. Run `python -m nasvetlo.cli run-once --dry-run` to verify

## Architecture

```
RSS Feeds → Ingest & Dedupe → Cluster by Event → Coherence Check (LLM)
    → Score Importance → Generate Draft (LLM) → Self-Edit (LLM)
    → Safety Gate → SEO Fields (LLM) → WordPress (pending)
```

### Pipeline Steps

1. **Ingestion**: Fetch RSS, normalize text, deduplicate by URL + content hash
2. **Clustering**: Embed articles, assign to clusters by cosine similarity (≥0.80)
3. **Coherence**: LLM validates that cluster articles describe the same event
4. **Scoring**: Importance formula (source count, tier, speed, institutional, recency)
5. **Drafting**: Per-source fact extraction → fact merge → article writing → self-edit
6. **Safety**: Rule-based keyword scan + LLM risk classifier
7. **Publishing**: WordPress REST API with `status: pending` (never auto-publish)

### Safety Rules

- Min 3 independent sources (distinct domains) per cluster
- Daily cap: 8 drafts
- Auto-pause on 3 consecutive failures or 3 high-risk articles in 24h
- Never auto-publish: all posts are `pending`
- Defamation keywords trigger high-risk flag

## VPS Deployment

```bash
# On VPS (Ubuntu/Debian)
sudo apt update && sudo apt install python3.11 python3.11-venv

# Clone repo
git clone <repo-url> nasvetlo-mvp
cd nasvetlo-mvp

# Setup
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
cp config.example.yaml config.yaml
nano .env  # Add API keys
nano config.yaml  # Configure sources and WordPress

# Test
pytest tests/ -v
python -m nasvetlo.cli run-once --dry-run

# Run as systemd service (see docs/RUNBOOK.md)
```

## Testing

```bash
# All tests
pytest tests/ -v

# Specific test files
pytest tests/test_normalize.py -v
pytest tests/test_clustering.py -v
pytest tests/test_importance.py -v
pytest tests/test_pipeline_dry_run.py -v
```

## Next Steps Backlog

- [ ] Web dashboard for editorial review
- [ ] Image generation/selection (copyright-safe)
- [ ] Telegram distribution channel
- [ ] Remote embeddings provider (OpenAI, Cohere)
- [ ] Better fact deduplication via LLM synthesis step
- [ ] Multi-language support
- [ ] RSS feed health monitoring and alerts
- [ ] A/B testing for article quality
- [ ] Analytics integration (post performance tracking)
- [ ] Cluster merging for evolving stories
- [ ] Rate limiting for LLM API calls
- [ ] Database migration tooling (Alembic)
