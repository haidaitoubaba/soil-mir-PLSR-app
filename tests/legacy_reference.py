"""Frozen scientific functions copied from the pre-app legacy script.

This module exists only as a regression oracle during refactoring. It should not be imported by
application code.
"""

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
from scipy.special import inv_boxcox
from scipy.stats import boxcox, yeojohnson as yj
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold, KFold, StratifiedGroupKFold


PREPROCESSING_NAMES = (
    "1st Derivative",
    "1st Deriv + SLS",
    "1st Deriv + SNV",
    "1st Deriv + MSC",
)


def first_deriv(X, window, poly):
    return savgol_filter(X, window_length=window, polyorder=poly, deriv=1, axis=1)


def straight_line_subtraction(X):
    n = X.shape[1]
    x = np.arange(n, dtype=float)
    slopes = (X[:, -1] - X[:, 0]) / (n - 1)
    baselines = X[:, 0:1] + slopes[:, None] * x[None, :]
    return X - baselines


def snv(X):
    mu = X.mean(axis=1, keepdims=True)
    sd = X.std(axis=1, keepdims=True)
    sd[sd == 0] = 1e-10
    return (X - mu) / sd


def msc(X, reference=None):
    if reference is None:
        reference = X.mean(axis=0)
    X = np.asarray(X, dtype=float)
    reference = np.asarray(reference, dtype=float)
    ref_centered = reference - reference.mean()
    denom_ref = np.dot(ref_centered, ref_centered)
    if denom_ref == 0:
        return X.copy()
    x_mean = X.mean(axis=1)
    slopes = ((X - x_mean[:, None]) @ ref_centered) / denom_ref
    intercepts = x_mean - slopes * reference.mean()
    slopes = np.where(slopes == 0, 1e-10, slopes)
    return (X - intercepts[:, None]) / slopes[:, None]


def apply_transform(y, method):
    m = method.lower().strip()
    if m in ("none", ""):
        return y, None
    if m == "sqrt":
        if np.any(y < 0):
            raise ValueError("sqrt transform requires all reference values >= 0")
        return np.sqrt(y), None
    if m == "log":
        if np.any(y < 0):
            raise ValueError("log transform requires all reference values >= 0")
        return np.log1p(y), None
    if m == "log10":
        if np.any(y < 0):
            raise ValueError("log10 transform requires all reference values >= 0")
        return np.log10(y + 1), None
    if m == "cbrt":
        return np.cbrt(y), None
    if m == "boxcox":
        if np.any(y <= 0):
            raise ValueError("boxcox requires all reference values > 0 (no zeros)")
        y_t, lam = boxcox(y)
        return y_t, lam
    if m == "yeojohnson":
        y_t, lam = yj(y)
        return y_t, lam
    raise ValueError(f"Unknown transform '{method}'.")


def back_transform(y_t, method, lam=None):
    m = method.lower().strip()
    if m in ("none", ""):
        return y_t
    if m == "sqrt":
        return np.clip(y_t, 0, None) ** 2
    if m == "log":
        return np.expm1(y_t)
    if m == "log10":
        return 10**y_t - 1
    if m == "cbrt":
        return y_t**3
    if m == "boxcox":
        return inv_boxcox(y_t, lam)
    if m == "yeojohnson":
        values = np.asarray(y_t, dtype=float)
        result = np.empty_like(values)
        positive = values >= 0
        if lam == 0:
            result[positive] = np.expm1(values[positive])
        else:
            result[positive] = np.expm1(np.log1p(lam * values[positive]) / lam)
        if lam == 2:
            result[~positive] = -np.expm1(-values[~positive])
        else:
            power = 2 - lam
            result[~positive] = -np.expm1(np.log1p(-power * values[~positive]) / power)
        return result
    return y_t


def segment_slices(lengths, width):
    if (
        not lengths
        or any(not isinstance(n, (int, np.integer)) or n < 1 for n in lengths)
        or sum(lengths) != width
    ):
        raise ValueError("Saved interval lengths do not match the spectral matrix.")
    boundaries = np.r_[0, np.cumsum(lengths)]
    return [slice(int(a), int(b)) for a, b in zip(boundaries[:-1], boundaries[1:])]


def spectral_derivative(X, cfg):
    lengths = cfg.get("_segment_lengths", [X.shape[1]])
    segments = segment_slices(lengths, X.shape[1])
    if min(lengths) < cfg["sg_window"]:
        raise ValueError("Every included interval must fit the derivative window.")
    return np.concatenate(
        [first_deriv(X[:, segment], cfg["sg_window"], cfg["sg_polyorder"]) for segment in segments],
        axis=1,
    )


def preprocessor_state(prep_name, derivative, cfg):
    return {
        "name": prep_name,
        "window": cfg["sg_window"],
        "polyorder": cfg["sg_polyorder"],
        "segment_lengths": list(cfg.get("_segment_lengths", [derivative.shape[1]])),
        "algorithm": "per_interval_derivative_v1",
        "msc_reference": derivative.mean(axis=0) if prep_name == "1st Deriv + MSC" else None,
    }


def _postprocess_derivative(prep_name, X_deriv, msc_reference=None, segment_lengths=None):
    if prep_name == "1st Derivative":
        return X_deriv
    if prep_name == "1st Deriv + SLS":
        segments = segment_slices(segment_lengths or [X_deriv.shape[1]], X_deriv.shape[1])
        return np.concatenate(
            [straight_line_subtraction(X_deriv[:, segment]) for segment in segments], axis=1
        )
    if prep_name == "1st Deriv + SNV":
        return snv(X_deriv)
    if prep_name == "1st Deriv + MSC":
        return msc(X_deriv, reference=msc_reference)
    raise ValueError(f"Unknown preprocessing option: {prep_name}")


def fit_transform_preprocessor(prep_name, X_train, cfg):
    derivative = spectral_derivative(X_train, cfg)
    fitted = preprocessor_state(prep_name, derivative, cfg)
    return fitted, _postprocess_derivative(
        prep_name, derivative, fitted["msc_reference"], fitted["segment_lengths"]
    )


def regression_metrics(y_true, y_pred, reference_iqr=None):
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


def choose_with_tolerance(frame, error_column, tolerance):
    eligible = frame[np.isfinite(frame[error_column]) & (frame[error_column] >= 0)].copy()
    if "Eligible" in eligible:
        eligible = eligible[eligible["Eligible"]]
    minimum = float(eligible[error_column].min())
    threshold = minimum * (1 + tolerance / 100)
    within = eligible[eligible[error_column] <= threshold]
    best = within.sort_values(["Rank", error_column, "Preprocessing", "Region"]).iloc[0]
    increase = 100 * (float(best[error_column]) / minimum - 1) if minimum > 0 else 0.0
    return best, {
        "Tolerance (%)": float(tolerance),
        "Minimum RMSECV": minimum,
        "Allowed RMSECV": threshold,
        "RMSECV Increase (%)": increase,
    }


def validate_sample_labels(keys, labels):
    if (
        len(keys) != len(labels)
        or not len(keys)
        or pd.isna(keys).any()
        or pd.isna(labels).any()
    ):
        raise ValueError
    if (
        pd.DataFrame({"Sample": keys, "Group": labels})
        .groupby("Sample")["Group"]
        .nunique()
        .gt(1)
        .any()
    ):
        raise ValueError


def grouped_splits(keys, labels, count, seed, outer=False):
    validate_sample_labels(keys, labels)
    n_samples = len(np.unique(keys))
    actual = min(count, n_samples)
    splits = None
    if (
        len(np.unique(labels)) > 1
        and min(np.unique(labels, return_counts=True)[1]) >= actual
    ):
        candidate = list(
            StratifiedGroupKFold(
                n_splits=actual, shuffle=True, random_state=seed
            ).split(np.zeros(len(keys)), labels, keys)
        )
        if all(len(a) and len(b) for a, b in candidate):
            splits = candidate
    fallback = splits is None
    if fallback:
        if outer:
            samples = np.unique(keys)
            splits = [
                (
                    np.flatnonzero(np.isin(keys, samples[a])),
                    np.flatnonzero(np.isin(keys, samples[b])),
                )
                for a, b in KFold(actual, shuffle=True, random_state=seed).split(samples)
            ]
        else:
            splits = list(GroupKFold(actual).split(np.zeros(len(keys)), groups=keys))
    return splits, {
        "splitter": (
            "StratifiedGroupKFold"
            if not fallback
            else ("Shuffled sample KFold" if outer else "GroupKFold")
        ),
        "requested_folds": count,
        "actual_folds": actual,
        "fallback": fallback,
        "fallback_reason": "Treatment balancing unavailable or infeasible" if fallback else "",
        "seed": seed,
    }
