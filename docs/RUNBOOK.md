# NA SVETLO – Operations Runbook

## Setup

### Prerequisites
- Python 3.11+
- SQLite (bundled with Python)
- API key for Anthropic or OpenAI
- WordPress site with REST API enabled and application password

### Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env` and fill in API keys
2. Copy `config.example.yaml` to `config.yaml` and customize sources
3. Set `DATABASE_URL` if not using default SQLite path

### WordPress Setup

1. Go to WordPress Admin → Users → Your Profile
2. Scroll to "Application Passwords"
3. Create a new application password for "nasvetlo-bot"
4. Copy the password to `.env` as `WP_APPLICATION_PASSWORD`
5. Ensure REST API is accessible at `{base_url}/wp-json/wp/v2/posts`

## Running

### Dry Run (Testing)

```bash
python -m nasvetlo.cli run-once --dry-run
```

This fetches RSS, clusters, scores, and generates drafts but does NOT call WordPress.

### Live Run

```bash
python -m nasvetlo.cli run-once
```

Creates pending WordPress posts for approved clusters.

### Daemon Mode

```bash
python -m nasvetlo.cli daemon
```

Runs the pipeline every N minutes (default: 40) as configured in `config.yaml`.

### Systemd Service (VPS)

Create `/etc/systemd/system/nasvetlo.service`:

```ini
[Unit]
Description=NA SVETLO News Pipeline
After=network.target

[Service]
Type=simple
User=nasvetlo
WorkingDirectory=/opt/nasvetlo-mvp
Environment=PATH=/opt/nasvetlo-mvp/.venv/bin
EnvironmentFile=/opt/nasvetlo-mvp/.env
ExecStart=/opt/nasvetlo-mvp/.venv/bin/python -m nasvetlo.cli daemon
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable nasvetlo
sudo systemctl start nasvetlo
sudo journalctl -u nasvetlo -f  # View logs
```

## Monitoring

### Check Status

```bash
python -m nasvetlo.cli status
```

Shows: last run time, articles ingested, drafts created, pause state.

### Logs

Logs are JSON-formatted on stderr. In daemon/systemd mode, use journalctl:

```bash
journalctl -u nasvetlo --since "1 hour ago" | jq .
```

Key log fields:
- `level`: INFO, WARNING, ERROR
- `step`: pipeline step name
- `cluster_id`: cluster being processed
- `source`: RSS source name

### Database Inspection

```bash
sqlite3 nasvetlo.db
.tables
SELECT COUNT(*) FROM raw_article;
SELECT id, importance_score, unique_domain_count, drafted FROM cluster WHERE is_candidate = 1;
SELECT id, title, safety_risk_level, published FROM generated_article ORDER BY created_at DESC LIMIT 10;
SELECT * FROM run_log ORDER BY id DESC LIMIT 5;
```

## Troubleshooting

### Pipeline is Paused

Check why:
```bash
python -m nasvetlo.cli status
sqlite3 nasvetlo.db "SELECT * FROM run_log ORDER BY id DESC LIMIT 5;"
```

Resume:
```bash
python -m nasvetlo.cli resume
```

Common causes:
- 3 consecutive LLM failures (check API key, rate limits)
- 3 high-risk articles in 24h (review safety flags)

### No Clusters Forming

- Check that RSS feeds are returning data: `python -c "from nasvetlo.ingestion.rss import fetch_feed; print(len(fetch_feed('URL')))"`
- Check similarity threshold (default 0.80) – may need tuning
- Check that feeds have overlapping stories

### LLM Errors

- Verify API key in `.env`
- Check rate limits / billing
- Inspect logs for specific error messages
- LLM JSON parse failures auto-retry twice before failing

### WordPress Publishing Fails

- Verify `base_url`, `username`, and application password
- Test manually: `curl -u user:password https://site.com/wp-json/wp/v2/posts`
- Check that REST API is not blocked by security plugin
- Verify category IDs in `config.yaml` match WordPress

## Adding RSS Sources

1. Edit `config.yaml`, add under `sources:`
2. Assign appropriate tier (1-4) and credibility score
3. Run `python -m nasvetlo.cli run-once --dry-run` to test
4. Monitor logs for feed parsing errors

## Backup

```bash
# Database
cp nasvetlo.db nasvetlo.db.bak

# Full backup
tar czf nasvetlo-backup-$(date +%Y%m%d).tar.gz nasvetlo.db config.yaml .env
```
