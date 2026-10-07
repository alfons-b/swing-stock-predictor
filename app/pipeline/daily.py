from pathlib import Path
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Stock, PriceHistory, Prediction, TradingSignal
from app.database.session import get_engine
from app.data.manager import ingest_ticker
from app.features.technical import add_features
from app.models.model import load_bundle, predict
from app.storage.model_storage import DatabaseModelStorage
from app.risk.engine import calculate_risk
from app.scanner.scanner import rank_stock


def load_stock_prices(session, stock_id):
    rows = session.scalars(
        select(PriceHistory).where(
            PriceHistory.stock_id == stock_id
        ).order_by(PriceHistory.date)
    ).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        "date": r.date,
        "open": float(r.open) if r.open is not None else None,
        "high": float(r.high),
        "low": float(r.low),
        "close": float(r.close),
        "volume": float(r.volume or 0),
    } for r in rows])


def _load_active_model(model_path):
    if model_path and Path(model_path).exists():
        return load_bundle(model_path), {"version": getattr(load_bundle(model_path), "version", "local")}
    storage = DatabaseModelStorage()
    return storage.load_active_model()


def run_daily(
    tickers: list[str],
    model_path="models/active.joblib",
    capital=10_000_000,
):
    results = []

    try:
        bundle, model_meta = _load_active_model(model_path)
        model_version = model_meta.get("version", getattr(bundle, "version", "unknown"))
    except FileNotFoundError:
        bundle = None
        model_version = "NO_ACTIVE_MODEL"

    for ticker in tickers:
        try:
            ingest_ticker(ticker)
        except Exception as exc:
            results.append({"ticker": ticker, "status": "DATA_FAILED", "error": str(exc)})
            continue

        session = Session(get_engine())
        try:
            stock = session.scalar(select(Stock).where(Stock.ticker == ticker))
            df = load_stock_prices(session, stock.id)

            if len(df) < 220:
                results.append({"ticker": ticker, "status": "INSUFFICIENT_DATA"})
                continue

            df = add_features(df)
            rank = rank_stock(df)
            row = df.iloc[-1]

            if bundle is not None:
                model_result = predict(bundle, df)
                confidence = model_result["bullish_probability"]
                expected = model_result["expected_return"]
            else:
                model_result = {
                    "bullish_probability": None,
                    "neutral_probability": None,
                    "bearish_probability": None,
                    "expected_return": None,
                }
                confidence, expected = 0.0, 0.0

            risk = calculate_risk(
                price=float(row["close"]),
                atr=float(row["atr"]),
                support=float(row["low_20d"]),
                resistance=float(row["high_20d"]),
                probability=confidence,
                expected_return=expected,
                capital=capital,
                risk_per_trade=0.01,
                minimum_rr=1.5,
                board_lot=100,
            )

            # Persist every generated prediction. A prediction is historical evidence,
            # so it is never overwritten merely because a later run uses another model.
            prediction = Prediction(
                stock_id=stock.id,
                prediction_date=row["date"],
                model_version=model_version,
                bullish_probability=model_result["bullish_probability"] or 0,
                neutral_probability=model_result["neutral_probability"] or 0,
                bearish_probability=model_result["bearish_probability"] or 0,
                expected_return=model_result["expected_return"],
                decision=risk.decision,
                score=rank["score"],
            )
            session.add(prediction)
            session.flush()

            session.add(TradingSignal(
                prediction_id=prediction.id,
                setup=rank["setup"],
                entry_low=risk.entry_low,
                entry_ideal=risk.entry_ideal,
                entry_high=risk.entry_high,
                stop_loss=risk.stop_loss,
                tp1=risk.tp1,
                tp2=risk.tp2,
                risk_reward=risk.risk_reward,
                position_size=risk.position_size,
                number_of_lots=risk.number_of_lots,
            ))
            session.commit()

            results.append({
                "ticker": ticker,
                "date": str(row["date"]),
                **rank,
                **model_result,
                "entry_low": risk.entry_low,
                "entry_ideal": risk.entry_ideal,
                "entry_high": risk.entry_high,
                "stop_loss": risk.stop_loss,
                "tp1": risk.tp1,
                "tp2": risk.tp2,
                "risk_reward": risk.risk_reward,
                "position_size": risk.position_size,
                "number_of_lots": risk.number_of_lots,
                "decision": risk.decision,
                "model_version": model_version,
            })
        except Exception as exc:
            session.rollback()
            results.append({"ticker": ticker, "status": "ANALYSIS_FAILED", "error": str(exc)})
        finally:
            session.close()

    return pd.DataFrame(results)
