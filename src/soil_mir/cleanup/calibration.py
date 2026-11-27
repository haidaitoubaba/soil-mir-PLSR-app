"""Cleanup's desktop Half A and Half B numerical workflow.

Preprocessing and response transforms are carried over from the MIR Cleanup
v1.4 desktop source. This module only evaluates the saved calibration split.
"""

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
from sklearn.cross_decomposition import PLSRegression
from threadpoolctl import threadpool_limits


def first_deriv(X, window, poly):
    return savgol_filter(X, window_length=window, polyorder=poly, deriv=1, axis=1)


def straight_line_subtraction(X):
    """Remove linear baseline from each spectrum"""
    n = X.shape[1]
    x = np.arange(n, dtype=float)
    slopes = (X[:, -1] - X[:, 0]) / (n - 1)
    baselines = X[:, 0:1] + slopes[:, None] * x[None, :]
    return X - baselines


def snv(X):
    """Standard Normal Variate"""
    mu = X.mean(axis=1, keepdims=True)
    sd = X.std(axis=1, keepdims=True)
    sd[sd == 0] = 1e-10
    return (X - mu) / sd


def msc(X, reference=None):
    """Multiplicative Scatter Correction"""
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


PREPROCESSING_NAMES = (
    "1st Derivative",
    "1st Deriv + SLS",
    "1st Deriv + SNV",
    "1st Deriv + MSC",
)


def apply_transform(y, method):
    """Apply the chosen transformation to reference values."""
    from scipy.stats import boxcox, yeojohnson as yj

    m = method.lower().strip()
    if m in ("none", ""):
        return y, None
    elif m == "sqrt":
        if np.any(y < 0):
            raise ValueError("sqrt transform requires all reference values >= 0")
        return np.sqrt(y), None
    elif m == "log":
        if np.any(y < 0):
            raise ValueError("log transform requires all reference values >= 0")
        return np.log1p(y), None  # log(y + 1) — safe for zeros
    elif m == "log10":
        if np.any(y < 0):
            raise ValueError("log10 transform requires all reference values >= 0")
        return np.log10(y + 1), None
    elif m == "cbrt":
        return np.cbrt(y), None  # cube root handles negatives naturally
    elif m == "boxcox":
        if np.any(y <= 0):
            raise ValueError("boxcox requires all reference values > 0 (no zeros)")
        y_t, lam = boxcox(y)
        return y_t, lam
    elif m == "yeojohnson":
        y_t, lam = yj(y)
        return y_t, lam
    else:
        raise ValueError(
            f"Unknown transform '{method}'. "
            f"Valid options: none, sqrt, log, log10, cbrt, boxcox, yeojohnson"
        )


def back_transform(y_t, method, lam=None):
    """Reverse the transformation back to original units."""
    from scipy.special import inv_boxcox

    m = method.lower().strip()
    if m in ("none", ""):
        return y_t
    elif m == "sqrt":
        return np.clip(y_t, 0, None) ** 2
    elif m == "log":
        return np.expm1(y_t)  # exp(y) - 1  (inverse of log1p)
    elif m == "log10":
        return 10**y_t - 1
    elif m == "cbrt":
        return y_t**3
    elif m == "boxcox":
        return inv_boxcox(y_t, lam)
    elif m == "yeojohnson":
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
    else:
        return y_t


def segment_slices(lengths: list, width: int) -> list:
    if (
        not lengths
        or any(not isinstance(n, (int, np.integer)) or n < 1 for n in lengths)
        or sum(lengths) != width
    ):
        raise ValueError("Saved interval lengths do not match the spectral matrix.")
    boundaries = np.r_[0, np.cumsum(lengths)]
    return [slice(int(a), int(b)) for a, b in zip(boundaries[:-1], boundaries[1:])]


def spectral_derivative(X: np.ndarray, cfg: dict) -> np.ndarray:
    """Differentiate each included interval independently; never cross a gap."""
    lengths = cfg.get("_segment_lengths", [X.shape[1]])
    segments = segment_slices(lengths, X.shape[1])
    if min(lengths) < cfg["sg_window"]:
        raise ValueError("Every included interval must fit the derivative window.")
    return np.concatenate(
        [first_deriv(X[:, segment], cfg["sg_window"], cfg["sg_polyorder"]) for segment in segments],
        axis=1,
    )


def preprocessor_state(prep_name: str, derivative: np.ndarray, cfg: dict) -> dict:
    """Build serializable state; derivative rows must be training spectra only."""
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


def transform_preprocessor(fitted, X):
    prep_name = fitted["name"]
    X_out = spectral_derivative(
        X,
        {
            "sg_window": fitted["window"],
            "sg_polyorder": fitted["polyorder"],
            "_segment_lengths": fitted.get("segment_lengths", [X.shape[1]]),
        },
    )
    return _postprocess_derivative(
        prep_name,
        X_out,
        msc_reference=fitted.get("msc_reference"),
        segment_lengths=fitted.get("segment_lengths"),
    )


def fit_transform_preprocessor(prep_name, X_train, cfg):
    """Return fitted state and transformed (spectra, wavenumbers) matrix."""
    derivative = spectral_derivative(X_train, cfg)
    fitted = preprocessor_state(prep_name, derivative, cfg)
    return fitted, _postprocess_derivative(
        prep_name, derivative, fitted["msc_reference"], fitted["segment_lengths"]
    )


def half_diagnostics(
    matrix, records, config, assignment, pca_exclusions, *, half, a_selection=None, a_exclusions=()
):
    """Fit one saved half and evaluate its selection on the opposite half."""
    if half == "B" and a_selection is None:
        raise ValueError("Half B requires the preprocessing and selected rank from Half A.")
    frame = pd.DataFrame(records)
    included = ~frame["File Name"].isin(pca_exclusions)
    sides = frame["Sample"].astype(str).map(assignment)
    if not sides[included].isin(["A", "B"]).all():
        raise ValueError("The saved split is missing assignments for retained samples.")
    train = (included & sides.eq(half)).to_numpy()
    opposite = "B" if half == "A" else "A"
    test = (included & sides.eq(opposite) & ~frame["File Name"].isin(a_exclusions)).to_numpy()
    if frame.loc[train, "Sample"].nunique() < 2 or frame.loc[test, "Sample"].nunique() < 2:
        raise ValueError("At least two retained samples are required in each half.")
    training, comparison = matrix[train], matrix[test]
    if not np.isfinite(training).all() or not np.isfinite(comparison).all():
        raise ValueError("Retained spectra contain non-finite values.")
    reference = frame["Reference Value"].to_numpy(float)
    groups = frame.loc[test, "Sample"].astype(str).to_numpy()
    with threadpool_limits(limits=1):
        diagnostics, search = diagnose_half(
            training,
            comparison,
            reference[train],
            reference[test],
            groups,
            config,
            half,
            a_selection,
        )
    result = frame.loc[train].assign(**diagnostics)
    return {
        "rows": result.astype(object).where(pd.notna(result), None).to_dict(orient="records"),
        "search": search,
        "validation_files": frame.loc[test, "File Name"].tolist(),
        "selection_source": "optimized on B" if half == "A" else "A",
    }


def diagnose_half(
    training, comparison, observed, opposite_observed, groups, config, half, a_selection
):
    transform = config["transform"]
    target, transform_parameter = apply_transform(observed, transform)
    if not np.isfinite(target).all() or np.var(target) == 0:
        raise ValueError("Calibration diagnosis unavailable: non-finite or constant response.")

    search = []
    best = None
    methods = (a_selection[0],) if a_selection else PREPROCESSING_NAMES
    for method in methods:
        preprocessor, calibration = fit_transform_preprocessor(method, training, config)
        validation = transform_preprocessor(preprocessor, comparison)
        diagnostic_rank = min(
            15,
            len(calibration) - 2,
            calibration.shape[1],
            np.linalg.matrix_rank(calibration - calibration.mean(axis=0)),
        )
        if a_selection and not 1 <= a_selection[1] <= diagnostic_rank:
            raise ValueError(
                f"Half B cannot support A's selected rank {a_selection[1]} "
                f"(available rank {diagnostic_rank})."
            )
        ranks = (a_selection[1],) if a_selection else range(1, diagnostic_rank + 1)
        for rank in ranks:
            model = PLSRegression(n_components=rank, scale=False).fit(calibration, target)
            predicted = back_transform(
                model.predict(validation).ravel(), transform, transform_parameter
            )
            means = (
                pd.DataFrame(
                    {
                        "sample": groups,
                        "true": opposite_observed,
                        "pred": predicted,
                    }
                )
                .groupby("sample")
                .mean()
            )
            error = float(np.sqrt(np.mean((means.true - means.pred) ** 2)))
            if not np.isfinite(error):
                raise ValueError("Non-finite diagnostic predictions.")
            search.append(
                {"Half": half, "Preprocessing": method, "Rank": rank, "Opposite-half RMSEP": error}
            )
            score = (error, rank, method)
            if best is None or score < best[0]:
                best = (score, calibration, diagnostic_rank)

    if best is None:
        raise ValueError("Calibration diagnosis unavailable: insufficient spectral rank.")
    (error, selected_rank, preprocessing), calibration, rank = best
    model = PLSRegression(n_components=rank, scale=False).fit(calibration, target)
    predicted = model.predict(calibration).ravel()
    residual = target - predicted
    scores = model.x_scores_
    leverage = np.sum((scores @ np.linalg.pinv(scores.T @ scores)) * scores, axis=1).clip(0, 1)
    mse = float(np.mean(residual**2))
    studentised = (
        (residual / np.sqrt(mse * (1 - leverage + 1e-10)))
        if mse > 0
        else np.zeros(len(calibration))
    )
    original_prediction = back_transform(predicted, transform, transform_parameter)
    if not np.isfinite(np.column_stack((predicted, studentised, original_prediction))).all():
        raise ValueError("Non-finite diagnostic result; review inputs.")
    return {
        "Diagnostic Note": "",
        "Half": half,
        "Preprocessing": preprocessing,
        "Selection Rank": int(selected_rank),
        "Diagnostic Rank": int(rank),
        "Opposite-half RMSEP": error,
        "Transformed Reference": target,
        "Transformed Prediction": predicted,
        "Transformed Residual": residual,
        "Studentised Residual": studentised,
        "Leverage": leverage,
        "Concentration Candidate": np.abs(studentised) > 2.5,
        "Calibration Prediction": original_prediction,
    }, search


def selection_from(diagnostic):
    first = diagnostic["rows"][0]
    return first["Preprocessing"], int(first["Selection Rank"])


def reviewed_half_decisions(records, diagnostic_rows, original, action, half):
    """Apply one manual decision while keeping prior PCA exclusions in effect."""
    files = set(action.get("files", []))
    allowed = {row["File Name"] for row in diagnostic_rows}
    if not files or not files <= allowed:
        raise ValueError(f"Select spectra in the displayed Half {half} fit.")
    unit, reason = action.get("unit"), action.get("reason", "")
    reasons = {"", "redundancy", "spectral_quality", "range", "concentration"}
    if unit not in {"spectrum", "sample"} or reason not in reasons:
        raise ValueError(f"Choose a valid Half {half} exclusion unit and reason.")
    if unit == "sample":
        samples = {records[name]["Sample"] for name in files}
        files = {name for name, row in records.items() if row["Sample"] in samples}

    decisions = dict(original)
    for name in sorted(files):
        existing = decisions.get(name)
        if existing and existing.get("stage", "PCA") == "PCA":
            continue
        if action["kind"] == "restore":
            if existing and existing["stage"] != half:
                raise ValueError("Restore records in the stage where they were excluded.")
            decisions.pop(name, None)
        else:
            decisions[name] = {
                "sample": str(records[name]["Sample"]),
                "stage": half,
                "unit": unit,
                "reason": reason,
                "comment": str(action.get("comment", "")).strip(),
            }
    return decisions


def calibration_record(row):
    return {
        "prediction": row["Calibration Prediction"],
        "transformed_reference": row["Transformed Reference"],
        "transformed_prediction": row["Transformed Prediction"],
        "residual": row["Transformed Residual"],
        "studentised": row["Studentised Residual"],
        "leverage": row["Leverage"],
        "candidate": bool(row["Concentration Candidate"]),
        "diagnostic_rank": int(row["Diagnostic Rank"]),
    }


def calibration_details(first, config, finished, limit, *, has_b=False):
    return {
        "preprocessing": first["Preprocessing"],
        "selectionRank": int(first["Selection Rank"]),
        "diagnosticRank": int(first["Diagnostic Rank"]),
        "rmsep": first["Opposite-half RMSEP"],
        "transform": config["transform"],
        "units": config["units"],
        "finished": finished,
        "hasB": has_b,
        "limit": limit,
    }
