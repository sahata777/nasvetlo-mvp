"""CLI interface using Typer."""

from __future__ import annotations

import json
import sys

import typer

app = typer.Typer(name="nasvetlo", help="На Светло – Bulgarian news aggregation pipeline")


@app.command()
def run_once(
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip publishing step"),
    max_drafts: int = typer.Option(None, "--max", "-n", help="Max drafts to generate this run"),
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Run the pipeline once."""
    from nasvetlo.logging_utils import setup_logging
    from nasvetlo.settings import get_settings
    from nasvetlo.config import load_config
    from nasvetlo.pipeline.run_once import run_pipeline

    settings = get_settings()
    setup_logging(settings.log_level)
    cfg_path = config_path or settings.nasvetlo_config
    config = load_config(cfg_path)

    summary = run_pipeline(config, dry_run=dry_run, max_drafts=max_drafts)

    typer.echo("\n=== Pipeline Run Summary ===")
    typer.echo(f"  Articles ingested:   {summary['articles_ingested']}")
    typer.echo(f"  Clusters formed:     {summary['clusters_formed']}")
    typer.echo(f"  Coherence validated: {summary.get('coherence_validated', 0)}")
    typer.echo(f"  Clusters scored:     {summary.get('clusters_scored', 0)}")
    typer.echo(f"  Drafts created:      {summary['drafts_created']}")
    typer.echo(f"  Drafts published:    {summary['drafts_published']}")
    typer.echo(f"  Errors:              {summary['errors']}")
    typer.echo(f"  Dry run:             {summary['dry_run']}")
    if summary.get("error_details"):
        typer.echo(f"  Error details:       {summary['error_details']}")


@app.command()
def daemon():
    """Run the pipeline as a daemon with scheduled intervals."""
    from nasvetlo.pipeline.daemon import run_daemon
    run_daemon()


@app.command()
def status(
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Show current pipeline status."""
    from nasvetlo.settings import get_settings
    from nasvetlo.config import load_config
    from nasvetlo.db import get_session, init_db
    from nasvetlo.models import RunLog, GeneratedArticle, Cluster, RawArticle
    from nasvetlo.utils.time import utcnow
    from datetime import timedelta

    settings = get_settings()
    cfg_path = config_path or settings.nasvetlo_config
    load_config(cfg_path)
    init_db()
    session = get_session()

    # Last run
    last_run = session.query(RunLog).order_by(RunLog.id.desc()).first()
    if last_run:
        typer.echo(f"Last run: {last_run.started_at} | Status: {last_run.status}")
        typer.echo(f"  Ingested: {last_run.articles_ingested} | Drafts: {last_run.drafts_created} | Errors: {last_run.errors}")
        typer.echo(f"  Paused: {last_run.is_paused}")
    else:
        typer.echo("No runs recorded yet.")

    # Counts
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total_articles = session.query(RawArticle).count()
    total_clusters = session.query(Cluster).count()
    candidate_clusters = session.query(Cluster).filter(Cluster.is_candidate == True).count()  # noqa: E712
    today_drafts = session.query(GeneratedArticle).filter(GeneratedArticle.created_at >= today_start).count()

    typer.echo(f"\nTotal articles: {total_articles}")
    typer.echo(f"Total clusters: {total_clusters} (candidates: {candidate_clusters})")
    typer.echo(f"Drafts today: {today_drafts}/{load_config(cfg_path).schedule.daily_cap}")

    session.close()


@app.command()
def pause(
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Pause the pipeline."""
    from nasvetlo.settings import get_settings
    from nasvetlo.config import load_config
    from nasvetlo.db import get_session, init_db
    from nasvetlo.pipeline.run_once import _set_paused

    settings = get_settings()
    cfg_path = config_path or settings.nasvetlo_config
    load_config(cfg_path)
    init_db()
    session = get_session()
    _set_paused(session, True)
    session.close()
    typer.echo("Pipeline PAUSED. Use 'nasvetlo resume' to continue.")


@app.command()
def resume(
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Resume the pipeline after pause."""
    from nasvetlo.settings import get_settings
    from nasvetlo.config import load_config
    from nasvetlo.db import get_session, init_db
    from nasvetlo.pipeline.run_once import _set_paused

    settings = get_settings()
    cfg_path = config_path or settings.nasvetlo_config
    load_config(cfg_path)
    init_db()
    session = get_session()
    _set_paused(session, False)
    session.close()
    typer.echo("Pipeline RESUMED.")


@app.command()
def backfill(
    hours: int = typer.Option(24, "--hours", "-h", help="Hours to look back"),
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Re-process articles from the last N hours."""
    from nasvetlo.logging_utils import setup_logging
    from nasvetlo.settings import get_settings
    from nasvetlo.config import load_config
    from nasvetlo.db import get_session, init_db
    from nasvetlo.models import RawArticle
    from nasvetlo.utils.time import utcnow
    from datetime import timedelta

    settings = get_settings()
    setup_logging(settings.log_level)
    cfg_path = config_path or settings.nasvetlo_config
    config = load_config(cfg_path)
    init_db()
    session = get_session()

    cutoff = utcnow() - timedelta(hours=hours)
    # Reset cluster assignments for recent articles so they get re-clustered
    articles = session.query(RawArticle).filter(RawArticle.fetched_at >= cutoff).all()
    for article in articles:
        article.cluster_id = None
    session.commit()
    session.close()

    typer.echo(f"Reset {len(articles)} articles from last {hours}h. Running pipeline...")

    from nasvetlo.pipeline.run_once import run_pipeline
    summary = run_pipeline(config, dry_run=True)
    typer.echo(f"Backfill complete. Clusters: {summary['clusters_formed']}, Drafts: {summary['drafts_created']}")


@app.command()
def serve(
    host: str = typer.Option(None, "--host", help="Bind host"),
    port: int = typer.Option(None, "--port", "-p", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config YAML"),
):
    """Start the web server (public site + editorial dashboard)."""
    import uvicorn
    from nasvetlo.logging_utils import setup_logging
    from nasvetlo.settings import get_settings
    from nasvetlo.config import load_config

    settings = get_settings()
    setup_logging(settings.log_level)
    cfg_path = config_path or settings.nasvetlo_config
    config = load_config(cfg_path)

    bind_host = host or config.web.host
    bind_port = port or config.web.port

    typer.echo(f"Starting Na Svetlo web server on {bind_host}:{bind_port}")
    uvicorn.run(
        "nasvetlo.web.app:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        reload=reload,
    )


def main():
    app()


if __name__ == "__main__":
    main()
