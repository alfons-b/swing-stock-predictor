from datetime import timedelta
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Prediction, PriceHistory
from app.database.session import get_engine


def evaluate_pending_predictions(horizon_days=5):
    session = Session(get_engine())
    evaluated = 0
    try:
        predictions = session.scalars(select(Prediction)).all()
        for prediction in predictions:
            # Skip already evaluated predictions.
            from app.database.models import PredictionEvaluation
            exists = session.scalar(
                select(PredictionEvaluation).where(
                    PredictionEvaluation.prediction_id == prediction.id
                )
            )
            if exists:
                continue

            target_date = prediction.prediction_date + timedelta(days=horizon_days)
            prices = session.scalars(
                select(PriceHistory)
                .where(
                    PriceHistory.stock_id == prediction.stock_id,
                    PriceHistory.date >= prediction.prediction_date,
                    PriceHistory.date <= target_date,
                )
                .order_by(PriceHistory.date)
            ).all()

            if len(prices) < 2:
                continue

            entry = float(prices[0].close)
            future = prices[-1]
            actual = float(future.close) / entry - 1
            future_high = max(float(p.high) for p in prices)
            future_low = min(float(p.low) for p in prices)
            mfe = future_high / entry - 1
            mae = future_low / entry - 1

            correct = (
                actual > 0 if prediction.bullish_probability >= prediction.bearish_probability
                else actual <= 0
            )

            session.add(PredictionEvaluation(
                prediction_id=prediction.id,
                evaluation_date=future.date,
                actual_return=actual,
                mfe=mfe,
                mae=mae,
                hit_stop=None,
                hit_tp1=None,
                hit_tp2=None,
                prediction_correct=correct,
            ))
            evaluated += 1

        session.commit()
        return evaluated
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
