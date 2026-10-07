from dataclasses import dataclass
import pandas as pd
from app.models.model import train_candidate


@dataclass
class FoldResult:
    train_end: str
    validation_end: str
    metrics: dict


def walk_forward_splits(df: pd.DataFrame, min_train=252, validation_size=63):
    for train_end in range(min_train, len(df) - validation_size + 1, validation_size):
        train = df.iloc[:train_end]
        valid = df.iloc[train_end:train_end + validation_size]
        yield train, valid


def evaluate_walk_forward(df, features, min_train=252, validation_size=63):
    results = []
    for train, valid in walk_forward_splits(df, min_train, validation_size):
        bundle = train_candidate(train, valid, features)
        results.append(FoldResult(
            str(train["date"].iloc[-1]),
            str(valid["date"].iloc[-1]),
            bundle.metrics,
        ))
    return results
