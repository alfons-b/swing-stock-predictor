from datetime import date
import json
import uuid
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Stock, PriceHistory
from app.database.session import get_engine
from app.features.technical import add_features
from app.models.dataset import build_training_frame
from app.models.model import train_candidate
from app.storage.model_storage import DatabaseModelStorage


def load_dataset():
    session = Session(get_engine())
    try:
        stocks = session.scalars(select(Stock).where(Stock.is_active.is_(True))).all()
        frames = []
        for stock in stocks:
            rows = session.scalars(
                select(PriceHistory)
                .where(PriceHistory.stock_id == stock.id)
                .order_by(PriceHistory.date)
            ).all()
            if len(rows) < 300:
                continue
            df = pd.DataFrame([{
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume or 0),
            } for r in rows])
            df = add_features(df)
            frame, _ = build_training_frame(df, horizon=5)
            frame["ticker"] = stock.ticker
            frames.append(frame)
        if not frames:
            raise RuntimeError("No stock has enough real historical data for training.")
        return pd.concat(frames, ignore_index=True)
    finally:
        session.close()


def main():
    frame = load_dataset()
    features = [
        c for c in frame.columns
        if c not in {"date", "ticker", "target_return", "target_class"}
    ]
    split_date = frame["date"].quantile(0.8)
    train = frame[frame["date"] < split_date]
    valid = frame[frame["date"] >= split_date]
    bundle = train_candidate(train, valid, features)

    version = f"model_{date.today():%Y%m%d}_{uuid.uuid4().hex[:8]}"
    bundle.version = version
    storage = DatabaseModelStorage()
    storage.save(bundle, {
        "version": version,
        "status": "CANDIDATE",
        "training_start": train["date"].min(),
        "training_end": train["date"].max(),
        "feature_version": "technical_v1",
        "metrics_json": json.dumps(bundle.metrics),
    })

    # Promotion policy: baseline implementation requires non-trivial validation quality.
    # Future candidate comparison can be tightened with historical production metrics.
    if bundle.metrics["balanced_accuracy"] >= 0.34:
        storage.promote(version)
        print(f"PROMOTED {version}: {bundle.metrics}")
    else:
        print(f"REJECTED {version}: {bundle.metrics}")


if __name__ == "__main__":
    main()
