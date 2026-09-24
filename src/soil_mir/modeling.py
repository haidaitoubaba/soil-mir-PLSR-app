from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
from scipy.linalg import pinv
from sklearn.cross_decomposition import PLSRegression

from soil_mir.io.opus import resample_spectrum, validate_wavenumbers
from soil_mir.metrics import grouped_metric_state, regression_metrics
from soil_mir.preprocessing import (
    PREPROCESSING_NAMES,
    _postprocess_derivative,
    fit_transform_preprocessor,
    preprocessor_state,
    segment_slices,
    spectral_derivative,
    transform_preprocessor,
)
from soil_mir.regions import (
    choose_with_tolerance,
    prepare_region_config,
    region_metadata,
    select_region,
)
from soil_mir.splits import cv_splits_for_training, inner_split_info
from soil_mir.transforms import apply_transform, back_transform


def build_cv_preprocessing_cache(
    X: np.ndarray,
    splits: list,
    prep_name: str,
    cfg: dict,
    derivative: np.ndarray | None = None,
) -> list[dict]:
    if derivative is None:
        derivative = spectral_derivative(X, cfg)

    fold_cache = []
    for train_idx, test_idx in splits:
        train_derivative = derivative[train_idx]
        fitted = preprocessor_state(prep_name, train_derivative, cfg)
        fold_cache.append(
            {
                "train_idx": train_idx,
                "test_idx": test_idx,
                "X_train_prep": _postprocess_derivative(
                    prep_name,
                    train_derivative,
                    fitted["msc_reference"],
                    fitted["segment_lengths"],
                ),
                "X_test_prep": _postprocess_derivative(
                    prep_name,
                    derivative[test_idx],
                    fitted["msc_reference"],
                    fitted["segment_lengths"],
                ),
            }
        )
    return fold_cache


def build_cv_response_cache(
    y_original: np.ndarray,
    splits: list,
    method: str,
) -> list:
    return [
        apply_transform(y_original[train_idx], method)
        for train_idx, _ in splits
    ]


def grouped_cv_predict_plsr_from_cache(
    fold_cache: list[dict],
    y_original: np.ndarray,
    groups: np.ndarray,
    rank: int,
    transform_method: str,
    response_cache: list | None = None,
    metric_state: tuple | None = None,
) -> tuple[np.ndarray, dict]:
    if response_cache is None:
        response_cache = build_cv_response_cache(
            y_original,
            [
                (fold["train_idx"], fold["test_idx"])
                for fold in fold_cache
            ],
            transform_method,
        )
    if metric_state is None:
        metric_state = grouped_metric_state(y_original, groups)

    predictions = np.full(len(y_original), np.nan)
    for fold, (train_response, fold_lambda) in zip(
        fold_cache,
        response_cache,
    ):
        train_X = fold["X_train_prep"]
        n_comp = min(rank, train_X.shape[0] - 1, train_X.shape[1])
        if n_comp < 1:
            raise ValueError("Insufficient training rows for a PLS component.")

        pls = PLSRegression(n_components=n_comp, scale=False)
        pls.fit(train_X, train_response)
        predictions[fold["test_idx"]] = back_transform(
            pls.predict(fold["X_test_prep"]).ravel(),
            transform_method,
            fold_lambda,
        )

    if not np.isfinite(predictions).all():
        raise ValueError(
            "CV predictions are missing or non-finite after inverse transformation."
        )

    inverse, counts, measured, iqr = metric_state
    predicted = np.bincount(inverse, weights=predictions) / counts
    return predictions, regression_metrics(measured, predicted, iqr)


def cv_rank_path(
    fold_cache: list[dict],
    y_original: np.ndarray,
    groups: np.ndarray,
    maximum_rank: int,
    method: str,
    response_cache: list,
) -> tuple[np.ndarray, list]:
    capacity = min(
        min(
            fold["X_train_prep"].shape[0] - 1,
            fold["X_train_prep"].shape[1],
        )
        for fold in fold_cache
    )
    limit = min(maximum_rank, capacity)
    predictions = np.full((maximum_rank, len(y_original)), np.nan)
    errors = ["" for _ in range(maximum_rank)]

    for rank in range(limit, maximum_rank):
        errors[rank] = f"Rank exceeds the inner-fold capacity ({capacity})."

    for fold, (response, fold_lambda) in zip(
        fold_cache,
        response_cache,
    ):
        train = fold["X_train_prep"]
        test = fold["X_test_prep"]
        path = None
        try:
            model = PLSRegression(
                n_components=limit,
                scale=False,
            ).fit(train, response)
            if not np.all(np.linalg.norm(model.x_weights_, axis=0) > 0):
                raise ValueError("PLS stopped before maximum rank")
            path = model
        except Exception:
            path = None

        for index in range(limit):
            rank = index + 1
            try:
                if path is None:
                    pred = (
                        PLSRegression(
                            n_components=rank,
                            scale=False,
                        )
                        .fit(train, response)
                        .predict(test)
                        .ravel()
                    )
                else:
                    weights = path.x_weights_[:, :rank]
                    loadings = path.x_loadings_[:, :rank]
                    coef = (
                        weights
                        @ pinv(loadings.T @ weights)
                        @ path.y_loadings_[:, :rank].T
                    )
                    pred = (
                        (test - train.mean(axis=0)) @ coef
                        + np.mean(response, axis=0)
                    ).ravel()

                pred = back_transform(
                    pred,
                    method,
                    fold_lambda,
                )
                if not np.isfinite(pred).all():
                    raise ValueError(
                        "Non-finite inverse-transformed predictions"
                    )
                predictions[index, fold["test_idx"]] = pred
            except Exception as exc:
                errors[index] = str(exc)

    inverse, counts, measured, iqr = grouped_metric_state(
        y_original,
        groups,
    )
    results = []
    for index, pred in enumerate(predictions):
        if errors[index] or not np.isfinite(pred).all():
            results.append(
                (None, errors[index] or "Missing CV predictions")
            )
        else:
            averaged = np.bincount(inverse, weights=pred) / counts
            results.append(
                (regression_metrics(measured, averaged, iqr), "")
            )

    return predictions, results


def optimize_plsr_grouped(
    X: np.ndarray,
    y_t: np.ndarray,
    y_original: np.ndarray,
    groups: np.ndarray,
    strata: np.ndarray,
    cfg: dict,
    transform_method: str,
    lam: float | None,
    random_state: int,
) -> tuple[pd.DataFrame, dict]:
    del y_t, lam

    splits = cv_splits_for_training(
        groups,
        strata,
        cfg,
        random_state,
    )
    responses = build_cv_response_cache(
        y_original,
        splits,
        transform_method,
    )
    records = []
    windows = tuple(
        window["Window"] for window in cfg["_region_windows"]
    )
    maximum_rank = int(cfg["max_rank"])

    for prep in PREPROCESSING_NAMES:
        evaluated = {}

        def evaluate(chosen):
            name = (
                "Full range"
                if len(chosen) == len(windows)
                else " + ".join(chosen)
            )
            if name in evaluated:
                return evaluated[name]

            region = cfg["_regions"][name]
            try:
                region_X, region_cfg = select_region(
                    X,
                    cfg,
                    name,
                )
                cache = build_cv_preprocessing_cache(
                    region_X,
                    splits,
                    prep,
                    region_cfg,
                )
                _, results = cv_rank_path(
                    cache,
                    y_original,
                    groups,
                    maximum_rank,
                    transform_method,
                    responses,
                )
            except Exception as exc:
                results = [(None, str(exc))] * maximum_rank

            scores = []
            for rank, (metrics, error) in enumerate(results, 1):
                record = {
                    **region_metadata(name, region),
                    "Preprocessing": prep,
                    "Rank": rank,
                    "Windows Retained": len(chosen),
                    "RMSECV": np.nan,
                    "R2_CV": np.nan,
                    "RPIQ_CV": np.nan,
                    "Bias_CV": np.nan,
                    "Status": "Failed",
                    "Error": error,
                }
                if metrics is not None:
                    record.update(
                        RMSECV=metrics["RMSE"],
                        R2_CV=metrics["R2"],
                        RPIQ_CV=metrics["RPIQ"],
                        Bias_CV=metrics["Bias"],
                        Status="Success",
                    )
                    scores.append(metrics["RMSE"])
                records.append(record)

            evaluated[name] = min(scores) if scores else np.inf
            return evaluated[name]

        current = windows
        evaluate(current)
        while len(current) > 1:
            children = [
                tuple(window for window in current if window != removed)
                for removed in current
            ]
            ranked = [
                (evaluate(child), child)
                for child in children
            ]
            score, current = min(
                ranked,
                key=lambda item: (item[0], item[1]),
            )
            if not np.isfinite(score):
                break

    frame = pd.DataFrame(records)
    row, decision = choose_with_tolerance(
        frame,
        "RMSECV",
        cfg.get("rmsecv_tolerance_pct", 2.0),
    )
    best = {
        **row.to_dict(),
        **decision,
        "RMSE": float(row["RMSECV"]),
        "Rank": int(row["Rank"]),
    }
    frame["Within Tolerance"] = (
        np.isfinite(frame["RMSECV"])
        & (frame["RMSECV"] <= decision["Allowed RMSECV"])
    )
    frame["Selected"] = False
    frame.loc[row.name, "Selected"] = True
    frame["Tolerance (%)"] = decision["Tolerance (%)"]

    return frame, best


def remove_concentration_outliers_mc(
    X: np.ndarray,
    y_t: np.ndarray,
    groups: np.ndarray,
    cfg: dict,
    prep_name: str,
    rank: int,
) -> tuple[np.ndarray, list]:
    n_samples = len(np.unique(groups))
    fraction = float(cfg.get("outlier_max_pct", 0.0))
    if not 0 <= fraction <= 1:
        raise ValueError("outlier_max_pct must be between 0 and 1.")

    max_n = int(
        Decimal(n_samples) * Decimal(str(fraction))
    )
    if fraction == 0:
        return np.ones(len(y_t), dtype=bool), []

    fitted, X_prep = fit_transform_preprocessor(
        prep_name,
        X,
        cfg,
    )
    del fitted
    n_comp = min(
        rank,
        X_prep.shape[0] - 2,
        X_prep.shape[1],
    )
    if n_comp < 1:
        return np.ones(len(y_t), dtype=bool), []

    pls = PLSRegression(
        n_components=n_comp,
        scale=False,
    )
    pls.fit(X_prep, y_t)
    y_hat = pls.predict(X_prep).ravel()
    resid = y_t - y_hat
    scores = pls.x_scores_
    lev = np.sum(
        (scores @ np.linalg.pinv(scores.T @ scores)) * scores,
        axis=1,
    ).clip(0, 1)
    mse = np.mean(resid**2)
    stud = (
        resid / np.sqrt(mse * (1 - lev + 1e-10))
        if mse > 0
        else np.zeros_like(resid)
    )

    lev_thr = 3.0 * lev.mean()
    row_flagged = (np.abs(stud) > 2.5) | (lev > lev_thr)
    if not row_flagged.any():
        return np.ones(len(y_t), dtype=bool), []

    row_score = np.abs(stud) + lev / (lev.mean() + 1e-10)
    flag_df = pd.DataFrame(
        {
            "Sample Key": groups,
            "Flagged": row_flagged,
            "Score": row_score,
        }
    )
    sample_scores = (
        flag_df[flag_df["Flagged"]]
        .groupby("Sample Key")["Score"]
        .max()
        .sort_values(ascending=False)
    )
    removed_samples = list(sample_scores.index[:max_n])
    keep = ~np.isin(groups, removed_samples)
    return keep, removed_samples


def fit_calibration_model(
    X: np.ndarray,
    y_original: np.ndarray,
    groups: np.ndarray,
    wavenumbers: np.ndarray,
    cfg: dict,
    group_labels: np.ndarray,
) -> tuple[dict, dict, list, pd.DataFrame]:
    if "_regions" not in cfg:
        cfg = prepare_region_config(
            cfg,
            wavenumbers,
        )

    transform_method = cfg.get("transform", "none")
    y_t, lam = apply_transform(
        y_original,
        transform_method,
    )
    search, best = optimize_plsr_grouped(
        X,
        y_t,
        y_original,
        groups,
        group_labels,
        cfg,
        transform_method,
        lam,
        int(cfg["random_seed"]),
    )

    initial_X, initial_cfg = select_region(
        X,
        cfg,
        best["Region"],
    )
    keep, removed_samples = remove_concentration_outliers_mc(
        initial_X,
        y_t,
        groups,
        initial_cfg,
        best["Preprocessing"],
        best["Rank"],
    )

    y_clean = y_original[keep]
    groups_clean = groups[keep]
    group_labels_clean = group_labels[keep]
    inner_split_info(
        groups_clean,
        group_labels_clean,
        cfg,
        int(cfg["random_seed"]),
    )

    if (
        cfg["method"] == "logo"
        and cfg.get("model_role") == "final_all_samples"
        and len(np.unique(group_labels_clean)) < 3
    ):
        raise ValueError(
            "Final LOGO calibration requires at least three retained treatments."
        )

    y_clean_t, lam = apply_transform(
        y_clean,
        transform_method,
    )
    initial_search = search.assign(
        Phase="Initial calibration search"
    )

    if removed_samples:
        search, best = optimize_plsr_grouped(
            X[keep],
            y_clean_t,
            y_clean,
            groups_clean,
            group_labels_clean,
            cfg,
            transform_method,
            lam,
            int(cfg["random_seed"]),
        )

    selection_summary = search.assign(
        Phase="Final calibration search",
        **{
            "Selection Scope": (
                "Internal CV on final calibration data; "
                "not held-out validation"
            )
        },
    )
    calibration_search = (
        pd.concat(
            [initial_search, selection_summary],
            ignore_index=True,
        )
        if removed_samples
        else selection_summary.copy()
    )

    X_clean, region_cfg = select_region(
        X[keep],
        cfg,
        best["Region"],
    )
    selected_region = cfg["_regions"][best["Region"]]
    selected_wavenumbers = np.asarray(wavenumbers)[
        selected_region["indices"]
    ]

    fitted_prep, X_clean_prep = fit_transform_preprocessor(
        best["Preprocessing"],
        X_clean,
        region_cfg,
    )
    n_comp = min(
        best["Rank"],
        X_clean_prep.shape[0] - 1,
        X_clean_prep.shape[1],
    )
    if n_comp < 1:
        raise RuntimeError(
            "The selected PLS rank is invalid for the final calibration data."
        )

    pls = PLSRegression(
        n_components=n_comp,
        scale=False,
    )
    pls.fit(
        X_clean_prep,
        y_clean_t,
    )

    model_bundle = {
        "preprocessing_state": fitted_prep,
        "preprocessing": fitted_prep,
        "pls_model": pls,
        "model": pls,
        "selected_preprocessing": best["Preprocessing"],
        "selected_rank": int(best["Rank"]),
        "requested_rank": int(best["Rank"]),
        "fitted_rank": int(n_comp),
        "selected_calibration_rmsecv": best["RMSECV"],
        "rmsecv_tolerance_pct": cfg.get(
            "rmsecv_tolerance_pct",
            2.0,
        ),
        "minimum_calibration_rmsecv": best["Minimum RMSECV"],
        "actual_rmsecv_increase_pct": best[
            "RMSECV Increase (%)"
        ],
        "selected_region": best["Region"],
        "region_search_n_windows": cfg.get(
            "region_search_n_windows",
            10,
        ),
        "region_search_windows": cfg["_region_windows"],
        "selected_regions_cm1": selected_region["intervals"],
        "regions_label": selected_region["label"],
        "requested_regions_cm1": selected_region[
            "requested_intervals"
        ],
        "bundle_version": 3,
        "calibration_search_results": calibration_search,
        "training_sample_ids": sorted(set(groups_clean)),
        "wavenumbers": selected_wavenumbers.copy(),
        "exclude_co2": bool(cfg.get("exclude_co2", False)),
        "co2_exclude_min": cfg.get("co2_exclude_min"),
        "co2_exclude_max": cfg.get("co2_exclude_max"),
        "response_transform": transform_method,
        "response_transform_parameter": lam,
        "property_name": cfg["property_name"],
        "units": cfg.get("units", ""),
        "training_sample_count": int(
            len(np.unique(groups_clean))
        ),
        "training_spectrum_count": int(len(X_clean)),
        "removed_sample_ids": list(removed_samples),
        "validation_method": cfg["method"],
        "inner_validation_method": (
            "leave_one_treatment_out"
            if cfg["method"] == "logo"
            else "sample_grouped_kfold"
        ),
        "internal_cv_folds": cfg.get("internal_cv_folds"),
        "calibration_scope": "all retained calibration samples",
    }

    return (
        model_bundle,
        best,
        removed_samples,
        selection_summary,
    )


def predict_model_bundle(
    bundle: dict,
    X: np.ndarray,
    source_wavenumbers: np.ndarray,
) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    source = validate_wavenumbers(source_wavenumbers)
    target = validate_wavenumbers(bundle["wavenumbers"])

    if (
        X.ndim != 2
        or X.shape[1] != len(source)
        or not np.isfinite(X).all()
    ):
        raise ValueError(
            "External matrix must be finite and match the source axis."
        )

    if np.array_equal(source, target):
        aligned = X
    else:
        if source[0] > source[-1]:
            source = source[::-1]
            X = X[:, ::-1]
        step = float(np.median(np.diff(source)))
        source_segments = np.split(
            np.arange(len(source)),
            np.flatnonzero(np.diff(source) > 1.5 * step) + 1,
        )
        aligned = np.empty(
            (len(X), len(target))
        )
        for segment in segment_slices(
            bundle["preprocessing_state"]["segment_lengths"],
            len(target),
        ):
            target_part = target[segment]
            covering = next(
                (
                    idx
                    for idx in source_segments
                    if source[idx[0]] <= target_part.min()
                    and source[idx[-1]] >= target_part.max()
                ),
                None,
            )
            if covering is None or len(covering) < 2:
                raise ValueError(
                    "External spectra do not continuously cover "
                    "a selected model interval."
                )
            aligned[:, segment] = np.vstack(
                [
                    resample_spectrum(
                        row[covering],
                        source[covering],
                        target_part,
                    )
                    for row in X
                ]
            )

    matrix = transform_preprocessor(
        bundle["preprocessing_state"],
        aligned,
    )
    predictions = back_transform(
        bundle["pls_model"].predict(matrix).ravel(),
        bundle["response_transform"],
        bundle["response_transform_parameter"],
    )
    if not np.isfinite(predictions).all():
        raise ValueError(
            "External predictions are non-finite "
            "after inverse transformation."
        )
    return predictions
