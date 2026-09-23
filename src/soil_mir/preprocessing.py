from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

PREPROCESSING_NAMES = (
    "1st Derivative",
    "1st Deriv + SLS",
    "1st Deriv + SNV",
    "1st Deriv + MSC",
)


def first_deriv(X: np.ndarray, window: int, poly: int) -> np.ndarray:
    return savgol_filter(X, window_length=window, polyorder=poly, deriv=1, axis=1)


def straight_line_subtraction(X: np.ndarray) -> np.ndarray:
    n = X.shape[1]
    x = np.arange(n, dtype=float)
    slopes = (X[:, -1] - X[:, 0]) / (n - 1)
    baselines = X[:, 0:1] + slopes[:, None] * x[None, :]
    return X - baselines


def snv(X: np.ndarray) -> np.ndarray:
    mu = X.mean(axis=1, keepdims=True)
    sd = X.std(axis=1, keepdims=True)
    sd[sd == 0] = 1e-10
    return (X - mu) / sd


def msc(X: np.ndarray, reference: np.ndarray | None = None) -> np.ndarray:
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


def segment_slices(lengths: list[int], width: int) -> list[slice]:
    if (
        not lengths
        or any(not isinstance(n, (int, np.integer)) or n < 1 for n in lengths)
        or sum(lengths) != width
    ):
        raise ValueError("Saved interval lengths do not match the spectral matrix.")
    boundaries = np.r_[0, np.cumsum(lengths)]
    return [slice(int(a), int(b)) for a, b in zip(boundaries[:-1], boundaries[1:])]


def spectral_derivative(X: np.ndarray, cfg: dict) -> np.ndarray:
    lengths = cfg.get("_segment_lengths", [X.shape[1]])
    segments = segment_slices(lengths, X.shape[1])
    if min(lengths) < cfg["sg_window"]:
        raise ValueError("Every included interval must fit the derivative window.")
    return np.concatenate(
        [first_deriv(X[:, segment], cfg["sg_window"], cfg["sg_polyorder"]) for segment in segments],
        axis=1,
    )


def preprocessor_state(prep_name: str, derivative: np.ndarray, cfg: dict) -> dict:
    if prep_name not in PREPROCESSING_NAMES:
        raise ValueError(f"Unknown preprocessing option: {prep_name}")
    return {
        "name": prep_name,
        "window": cfg["sg_window"],
        "polyorder": cfg["sg_polyorder"],
        "segment_lengths": list(cfg.get("_segment_lengths", [derivative.shape[1]])),
        "algorithm": "per_interval_derivative_v1",
        "msc_reference": derivative.mean(axis=0) if prep_name == "1st Deriv + MSC" else None,
    }


def _postprocess_derivative(
    prep_name: str,
    X_deriv: np.ndarray,
    msc_reference: np.ndarray | None = None,
    segment_lengths: list[int] | None = None,
) -> np.ndarray:
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


def fit_preprocessor(prep_name: str, X_train: np.ndarray, cfg: dict) -> dict:
    derivative = spectral_derivative(X_train, cfg)
    return preprocessor_state(prep_name, derivative, cfg)


def transform_preprocessor(fitted: dict, X: np.ndarray) -> np.ndarray:
    X_out = spectral_derivative(
        X,
        {
            "sg_window": fitted["window"],
            "sg_polyorder": fitted["polyorder"],
            "_segment_lengths": fitted.get("segment_lengths", [X.shape[1]]),
        },
    )
    return _postprocess_derivative(
        fitted["name"],
        X_out,
        msc_reference=fitted.get("msc_reference"),
        segment_lengths=fitted.get("segment_lengths"),
    )


def fit_transform_preprocessor(prep_name: str, X_train: np.ndarray, cfg: dict) -> tuple[dict, np.ndarray]:
    derivative = spectral_derivative(X_train, cfg)
    fitted = preprocessor_state(prep_name, derivative, cfg)
    return fitted, _postprocess_derivative(
        prep_name, derivative, fitted["msc_reference"], fitted["segment_lengths"]
    )
