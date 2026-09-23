from __future__ import annotations

import numpy as np
from scipy.linalg import pinv
from sklearn.cross_decomposition import PLSRegression

from soil_mir.metrics import grouped_metric_state, regression_metrics
from soil_mir.preprocessing import (
    _postprocess_derivative,
    preprocessor_state,
    spectral_derivative,
)
from soil_mir.transforms import apply_transform, back_transform


def build_cv_preprocessing_cache(
    X: np.ndarray,
    splits: list,
    prep_name: str,
    cfg: dict,
    derivative: np.ndarray | None = None,
) -> list[dict]:
    """Cache fold-specific preprocessing without leaking validation rows into fitted state."""
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


def build_cv_response_cache(y_original: np.ndarray, splits: list, method: str) -> list:
    """Fit response transforms on each training fold only."""
    return [apply_transform(y_original[train_idx], method) for train_idx, _ in splits]


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
            [(fold["train_idx"], fold["test_idx"]) for fold in fold_cache],
            transform_method,
        )
    if metric_state is None:
        metric_state = grouped_metric_state(y_original, groups)

    predictions = np.full(len(y_original), np.nan)
    for fold, (train_response, fold_lambda) in zip(fold_cache, response_cache):
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
        raise ValueError("CV predictions are missing or non-finite after inverse transformation.")

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
    """Evaluate ranks 1..maximum_rank using the legacy prefix-reconstruction algorithm."""
    capacity = min(
        min(fold["X_train_prep"].shape[0] - 1, fold["X_train_prep"].shape[1])
        for fold in fold_cache
    )
    limit = min(maximum_rank, capacity)
    predictions = np.full((maximum_rank, len(y_original)), np.nan)
    errors = ["" for _ in range(maximum_rank)]

    for rank in range(limit, maximum_rank):
        errors[rank] = f"Rank exceeds the inner-fold capacity ({capacity})."

    for fold, (response, fold_lambda) in zip(fold_cache, response_cache):
        train = fold["X_train_prep"]
        test = fold["X_test_prep"]
        path = None
        try:
            model = PLSRegression(n_components=limit, scale=False).fit(train, response)
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
                        PLSRegression(n_components=rank, scale=False)
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
                        (test - train.mean(axis=0)) @ coef + np.mean(response, axis=0)
                    ).ravel()

                pred = back_transform(pred, method, fold_lambda)
                if not np.isfinite(pred).all():
                    raise ValueError("Non-finite inverse-transformed predictions")
                predictions[index, fold["test_idx"]] = pred
            except Exception as exc:
                errors[index] = str(exc)

    inverse, counts, measured, iqr = grouped_metric_state(y_original, groups)
    results = []
    for index, pred in enumerate(predictions):
        if errors[index] or not np.isfinite(pred).all():
            results.append((None, errors[index] or "Missing CV predictions"))
        else:
            averaged = np.bincount(inverse, weights=pred) / counts
            results.append((regression_metrics(measured, averaged, iqr), ""))

    return predictions, results
