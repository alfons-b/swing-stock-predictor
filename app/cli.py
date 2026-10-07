import typer
from app.database.init_db import initialize_database
from app.database.session import database_health
from app.pipeline.daily import run_daily

app = typer.Typer(help="BEI AI Swing Stock Predictor")


@app.command()
def setup() -> None:
    """Validate environment and initialize the database schema."""
    from pathlib import Path
    for directory in ["data/raw", "data/processed", "data/cache", "data/output", "models", "reports"]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    initialize_database()
    from app.data.universe import UniverseManager
    universe = UniverseManager().load()
    typer.echo(f"UNIVERSE CONFIGURED: {len(universe)} tickers")
    typer.echo("SETUP: OK")


@app.command("health")
def health() -> None:
    result = database_health()
    typer.echo(f"DATABASE: {result['status']}")
    typer.echo(f"DATABASE DIALECT: {result['dialect']}")
    typer.echo(f"ENVIRONMENT: {result['environment']}")
    typer.echo(f"TIMEZONE: {result['timezone']}")


@app.command("daily")
def daily() -> None:
    """Run one finite daily pipeline. It exits when processing is complete."""
    from pathlib import Path
    import os
    tickers = os.getenv("STOCK_UNIVERSE", "").strip()
    if not tickers:
        # No fabricated universe: require an explicit production universe until
        # the authoritative universe provider is configured.
        typer.echo("DAILY PIPELINE: no STOCK_UNIVERSE configured; nothing executed.")
        raise typer.Exit(code=2)
    ticker_list = [x.strip().upper() for x in tickers.split(",") if x.strip()]
    from app.pipeline.evaluation import evaluate_pending_predictions
    evaluated = evaluate_pending_predictions()
    df = run_daily(ticker_list)
    from app.reporting.daily_report import write_daily_report
    csv_path, html_path = write_daily_report(df)
    typer.echo(f"PREDICTIONS EVALUATED: {evaluated}")
    typer.echo(f"DAILY PIPELINE: completed ({len(df)} results)")
    typer.echo(f"CSV: {csv_path}")
    typer.echo(f"REPORT: {html_path}")


@app.command("validate-data")
def validate_data() -> None:
    typer.echo("DATA VALIDATION: use app.data.manager validation during ingestion.")


@app.command("update-data")
def update_data() -> None:
    typer.echo("UPDATE DATA: use daily pipeline or ingest_ticker for incremental updates.")


@app.command("features")
def features() -> None:
    typer.echo("FEATURE ENGINE: callable via app.features.technical.add_features.")


@app.command("train")
def train() -> None:
    from scripts.train_from_database import main as train_main
    train_main()


@app.command("evaluate")
def evaluate() -> None:
    from app.pipeline.evaluation import evaluate_pending_predictions
    count = evaluate_pending_predictions()
    typer.echo(f"PREDICTION EVALUATION: {count} new evaluations")


@app.command("backtest")
def backtest() -> None:
    typer.echo("BACKTEST: engine available in app.backtest.engine; orchestration is next refinement.")


@app.command("scan")
def scan() -> None:
    typer.echo("SCANNER: use app.scanner.scanner.rank_stock over the universe.")


@app.command("predict")
def predict(ticker: str) -> None:
    typer.echo(f"PREDICT {ticker}: run daily pipeline with STOCK_UNIVERSE={ticker}.")


if __name__ == "__main__":
    app()
