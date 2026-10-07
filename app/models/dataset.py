import pandas as pd
from app.features.technical import FEATURE_COLUMNS
from app.strategy.setups import generate_target


def build_training_frame(df: pd.DataFrame, horizon=5) -> tuple[pd.DataFrame, list[str]]:
    data = df.copy()
    data["target_return"] = generate_target(data, horizon)
    data["target_class"] = pd.cut(
        data["target_return"],
        bins=[-float("inf"), -0.02, 0.02, float("inf")],
        labels=["BEARISH", "NEUTRAL", "BULLISH"],
    )
    data = data.dropna(subset=FEATURE_COLUMNS + ["target_return", "target_class"]).copy()
    return data, FEATURE_COLUMNS
