from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import joblib
import numpy as np
import pandas as pd

from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss, mean_absolute_error
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier, XGBRegressor


LABELS = ["BEARISH", "NEUTRAL", "BULLISH"]


@dataclass
class ModelBundle:
    classifier: object
    regressor: object
    feature_columns: list[str]
    version: str
    metrics: dict


def _class_ids(y):
    return y.map({v: i for i, v in enumerate(LABELS)}).astype(int)


def train_candidate(train: pd.DataFrame, valid: pd.DataFrame, features: list[str], seed=42):
    Xtr, Xv = train[features], valid[features]
    ytr, yv = _class_ids(train["target_class"]), _class_ids(valid["target_class"])

    classifier = XGBClassifier(
        n_estimators=350, max_depth=5, learning_rate=0.04,
        subsample=0.85, colsample_bytree=0.85,
        objective="multi:softprob", num_class=3,
        eval_metric="mlogloss", random_state=seed, n_jobs=2
    )
    classifier.fit(Xtr, ytr)

    regressor = XGBRegressor(
        n_estimators=300, max_depth=5, learning_rate=0.04,
        subsample=0.85, colsample_bytree=0.85,
        objective="reg:squarederror", random_state=seed, n_jobs=2
    )
    regressor.fit(Xtr, train["target_return"])

    proba = classifier.predict_proba(Xv)
    pred = classifier.predict(Xv)
    pred_ret = regressor.predict(Xv)
    metrics = {
        "accuracy": float(accuracy_score(yv, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(yv, pred)),
        "log_loss": float(log_loss(yv, proba, labels=[0,1,2])),
        "mae_return": float(mean_absolute_error(valid["target_return"], pred_ret)),
    }
    return ModelBundle(classifier, regressor, features, "candidate", metrics)


def predict(bundle: ModelBundle, frame: pd.DataFrame) -> dict:
    X = frame[bundle.feature_columns].tail(1)
    proba = bundle.classifier.predict_proba(X)[0]
    expected = float(bundle.regressor.predict(X)[0])
    return {
        "bearish_probability": float(proba[0]),
        "neutral_probability": float(proba[1]),
        "bullish_probability": float(proba[2]),
        "expected_return": expected,
    }


def save_bundle(bundle: ModelBundle, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_bundle(path: str | Path) -> ModelBundle:
    return joblib.load(path)


def config_hash(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()
