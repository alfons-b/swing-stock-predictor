from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, Index, LargeBinary
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(100))
    subsector: Mapped[str | None] = mapped_column(String(100))
    listed_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_price_stock_date"),
        Index("ix_price_stock_date", "stock_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column()
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("stock_id", "action_date", "action_type", name="uq_corp_action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"))
    action_date: Mapped[date] = mapped_column(Date)
    action_type: Mapped[str] = mapped_column(String(50))
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))


class MarketIndex(Base):
    __tablename__ = "market_index"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_index_symbol_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column()


class SectorData(Base):
    __tablename__ = "sector_data"
    __table_args__ = (UniqueConstraint("sector", "date", name="uq_sector_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector: Mapped[str] = mapped_column(String(100))
    date: Mapped[date] = mapped_column(Date)
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column()


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_feature_stock_date"),
        Index("ix_feature_stock_date", "stock_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    feature_version: Mapped[str] = mapped_column(String(50))
    payload: Mapped[str] = mapped_column(Text)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (Index("ix_prediction_stock_date", "stock_id", "prediction_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"))
    prediction_date: Mapped[date] = mapped_column(Date)
    model_version: Mapped[str] = mapped_column(String(100))
    bullish_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    neutral_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    bearish_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    expected_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    decision: Mapped[str] = mapped_column(String(30))
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))


class PredictionEvaluation(Base):
    __tablename__ = "prediction_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id", ondelete="CASCADE"), unique=True)
    evaluation_date: Mapped[date] = mapped_column(Date)
    actual_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    mfe: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    mae: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    hit_stop: Mapped[bool | None]
    hit_tp1: Mapped[bool | None]
    hit_tp2: Mapped[bool | None]
    prediction_correct: Mapped[bool | None]


class TradingSignal(Base):
    __tablename__ = "trading_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id", ondelete="CASCADE"))
    setup: Mapped[str] = mapped_column(String(80))
    entry_low: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    entry_ideal: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    entry_high: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    tp1: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    tp2: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    risk_reward: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    position_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    number_of_lots: Mapped[int | None]


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30))
    metrics_json: Mapped[str | None] = mapped_column(Text)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    exit_date: Mapped[date | None] = mapped_column(Date)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    quantity: Mapped[int | None]
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30))
    training_start: Mapped[date | None] = mapped_column(Date)
    training_end: Mapped[date | None] = mapped_column(Date)
    feature_version: Mapped[str | None] = mapped_column(String(50))
    metrics_json: Mapped[str | None] = mapped_column(Text)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    artifact_blob: Mapped[bytes | None] = mapped_column(LargeBinary)
    config_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True)
    run_type: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30))
    stocks_processed: Mapped[int] = mapped_column(Integer, default=0)
    stocks_failed: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    model_version: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider_type: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
