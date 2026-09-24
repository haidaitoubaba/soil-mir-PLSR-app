from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import r2_score


def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def rpiq_score(y_true, y_pred) -> float:
    iqr = float(np.percentile(y_true, 75) - np.percentile(y_true, 25))
    return iqr / rmse(y_true, y_pred)


def bias_score(y_true, y_pred) -> float:
    return float(np.mean(np.asarray(y_true) - np.asarray(y_pred)))


def grouped_average_frame(y_true, y_pred, groups) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "Sample Key": groups,
            "Measured": np.asarray(y_true, dtype=float),
            "Predicted": np.asarray(y_pred, dtype=float),
        }
    )
    return frame.groupby("Sample Key", as_index=False).agg(
        {"Measured": "mean", "Predicted": "mean"}
    )


def regression_metrics(y_true, y_pred, reference_iqr=None) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) < 2:
        return {"R2": np.nan, "RMSE": np.nan, "RPIQ": np.nan, "Bias": np.nan}
    error = y_true - y_pred
    error_rmse = float(np.sqrt(np.mean(error**2)))
    iqr = (
        float(np.subtract(*np.percentile(y_true, [75, 25])))
        if reference_iqr is None
        else reference_iqr
    )
    ratio = iqr / error_rmse if error_rmse else (np.inf if iqr else np.nan)
    return {
        "R2": float(r2_score(y_true, y_pred)),
        "RMSE": error_rmse,
        "RPIQ": float(ratio),
        "Bias": float(error.mean()),
    }


def grouped_metric_state(y_original: np.ndarray, groups: np.ndarray) -> tuple:
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    measured = np.bincount(inverse, weights=y_original) / counts
    iqr = float(np.subtract(*np.percentile(measured, [75, 25])))
    return inverse, counts, measured, iqr
