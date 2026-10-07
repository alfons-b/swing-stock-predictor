import pandas as pd
from app.features.technical import add_features, FEATURE_COLUMNS
from app.models.dataset import build_training_frame


def sample_ohlcv(n=300):
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series(range(100, 100+n), dtype=float)
    return pd.DataFrame({
        "date": dates,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 100000,
    })


def test_features_are_backward_looking():
    df = sample_ohlcv()
    out1 = add_features(df)
    changed = df.copy()
    changed.loc[len(changed)-1, "close"] += 99999
    out2 = add_features(changed)

    # The feature vector at t-1 must not change when future t changes.
    for col in FEATURE_COLUMNS:
        a, b = out1.loc[len(out1)-2, col], out2.loc[len(out2)-2, col]
        if pd.notna(a) and pd.notna(b):
            assert a == b


def test_future_target_is_not_feature():
    frame, features = build_training_frame(add_features(sample_ohlcv()))
    assert "target_return" not in features
    assert "target_class" not in features
