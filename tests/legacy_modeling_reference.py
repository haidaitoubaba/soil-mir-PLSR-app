"""Frozen PLS CV/rank-path functions copied from the legacy script."""

import numpy as np
from scipy.linalg import pinv
from sklearn.cross_decomposition import PLSRegression

from legacy_reference import (
    _postprocess_derivative,
    apply_transform,
    back_transform,
    preprocessor_state,
    regression_metrics,
    spectral_derivative,
)


def grouped_metric_state(y_original, groups):
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    measured = np.bincount(inverse, weights=y_original) / counts
    iqr = float(np.subtract(*np.percentile(measured, [75, 25])))
    return inverse, counts, measured, iqr


def build_cv_preprocessing_cache(X, splits, prep_name, cfg, derivative=None):
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


def build_cv_response_cache(y_original, splits, method):
    return [apply_transform(y_original[train_idx], method) for train_idx, _ in splits]


def cv_rank_path(fold_cache, y_original, groups, maximum_rank, method, response_cache):
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
        train, test = fold["X_train_prep"], fold["X_test_prep"]
        path = None
        try:
            model = PLSRegression(n_components=limit, scale=False).fit(train, response)
            if not np.all(np.linalg.norm(model.x_weights_, axis=0) > 0):
                raise ValueError("PLS stopped before maximum rank")
            path = model
        except Exception:
            pass

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
