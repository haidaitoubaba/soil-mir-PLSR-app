from __future__ import annotations

import time
from contextlib import nullcontext

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.spatial.distance import cdist
from sklearn.decomposition import PCA
from sklearn.model_selection import (
    LeaveOneGroupOut,
    StratifiedShuffleSplit,
)
from threadpoolctl import threadpool_limits

from soil_mir.metrics import (
    grouped_average_frame,
    regression_metrics,
)
from soil_mir.modeling import (
    fit_calibration_model,
    predict_model_bundle,
)
from soil_mir.preprocessing import snv, spectral_derivative
from soil_mir.regions import prepare_region_config, select_region
from soil_mir.splits import (
    check_splits,
    grouped_splits,
    inner_split_info,
    validate_sample_labels,
)


def kennard_stone_split(
    X: np.ndarray,
    keys: np.ndarray,
    cfg: dict,
) -> tuple:
    X = np.asarray(X, dtype=float)
    keys = np.asarray(keys)
    if (
        X.ndim != 2
        or keys.ndim != 1
        or len(X) != len(keys)
        or not len(keys)
        or not X.shape[1]
    ):
        raise ValueError(
            "Spectra and sample IDs must have matching nonempty rows."
        )
    if (
        not np.isfinite(X).all()
        or pd.isna(keys).any()
        or any(not str(key).strip() for key in keys)
    ):
        raise ValueError(
            "KS requires finite spectra and nonempty sample IDs."
        )

    samples = np.unique(keys)
    fraction = float(cfg["validation_fraction"])
    if not 0 < fraction < 1:
        raise ValueError(
            "validation_fraction must lie between zero and one."
        )

    n_val = int(np.ceil(len(samples) * fraction))
    n_train = len(samples) - n_val
    if min(n_train, n_val) < 2:
        raise ValueError(
            "KS requires at least two calibration and two "
            "validation samples."
        )

    means = np.vstack(
        [
            X[keys == sample].mean(axis=0)
            for sample in samples
        ]
    )
    mode = cfg.get("ks_representation", "raw")
    representation = means

    if mode == "derivative_snv":
        representation = snv(
            spectral_derivative(means, cfg)
        )
    elif mode == "pca":
        if not np.any(np.ptp(means, axis=0)):
            raise ValueError(
                "PCA split design requires spectral variation."
            )
        representation = PCA(
            n_components=float(cfg["ks_pca_variance"]),
            svd_solver="full",
            whiten=False,
        ).fit_transform(means)
    elif mode != "raw":
        raise ValueError("Unknown KS representation.")

    if not np.isfinite(representation).all():
        raise ValueError("KS representation is not finite.")

    farthest, first, second = -1.0, 0, 1
    for start in range(0, len(samples), 256):
        distances = cdist(
            representation[start : start + 256],
            representation,
            metric="sqeuclidean",
        )
        if not np.isfinite(distances).all():
            raise ValueError(
                "KS distances overflowed; inspect spectral magnitudes."
            )
        for local in range(len(distances)):
            distances[local, : start + local + 1] = -1
        flat = int(np.argmax(distances))
        row, col = np.unravel_index(
            flat,
            distances.shape,
        )
        if distances[row, col] > farthest:
            farthest = float(distances[row, col])
            first = start + row
            second = col

    selected = [first, second]
    nearest = np.minimum(
        cdist(
            representation,
            representation[[first]],
            "sqeuclidean",
        ).ravel(),
        cdist(
            representation,
            representation[[second]],
            "sqeuclidean",
        ).ravel(),
    )
    nearest[selected] = -np.inf

    while len(selected) < n_train:
        index = int(np.argmax(nearest))
        selected.append(index)
        nearest = np.minimum(
            nearest,
            cdist(
                representation,
                representation[[index]],
                "sqeuclidean",
            ).ravel(),
        )
        nearest[selected] = -np.inf

    train_mask = np.isin(
        keys,
        samples[selected],
    )
    ranks = {
        samples[index]: rank
        for rank, index in enumerate(selected, 1)
    }
    membership = pd.DataFrame(
        {
            "Sample Key": samples,
            "Set": [
                "Calibration"
                if sample in ranks
                else "Validation"
                for sample in samples
            ],
            "KS Selection Order": [
                ranks.get(sample, np.nan)
                for sample in samples
            ],
            "Spectra": [
                int(np.sum(keys == sample))
                for sample in samples
            ],
        }
    )
    metadata = {
        "algorithm": (
            "Kennard-Stone farthest-pair then maximin"
        ),
        "representation": mode,
        "distance": "Euclidean; no wavelength autoscaling",
        "pca_variance": (
            float(cfg["ks_pca_variance"])
            if mode == "pca"
            else None
        ),
        "representation_dimensions": representation.shape[1],
        "sample_representation": (
            "mean of replicate spectra; original rows retained for PLS"
        ),
        "requested_validation_fraction": fraction,
        "actual_validation_fraction": (
            n_val / len(samples)
        ),
        "calibration_samples": n_train,
        "validation_samples": n_val,
        "tie_break": "sorted sample ID",
        "treatment_stratified": False,
    }
    return (
        train_mask,
        ~train_mask,
        membership,
        metadata,
    )


def outer_splits(
    X: np.ndarray,
    keys: np.ndarray,
    labels: np.ndarray,
    cfg: dict,
) -> tuple[list, dict]:
    validate_sample_labels(keys, labels)
    method = cfg["method"]
    seed = cfg["random_seed"]
    info = {
        "method": method,
        "seed": seed,
    }

    if method == "kfold":
        splits, details = grouped_splits(
            keys,
            labels,
            cfg["outer_cv_folds"],
            seed,
            outer=True,
        )
        info.update(details)
    elif method == "monte_carlo":
        sample_df = pd.DataFrame(
            {
                "Sample": keys,
                "Group": labels,
            }
        ).drop_duplicates("Sample")
        splits = []
        for repeat in range(cfg["n_repeats"]):
            train_samples, test_samples = next(
                StratifiedShuffleSplit(
                    n_splits=1,
                    test_size=cfg["validation_fraction"],
                    random_state=seed + repeat,
                ).split(
                    sample_df["Sample"],
                    sample_df["Group"],
                )
            )
            splits.append(
                (
                    np.flatnonzero(
                        np.isin(
                            keys,
                            sample_df.iloc[
                                train_samples
                            ]["Sample"],
                        )
                    ),
                    np.flatnonzero(
                        np.isin(
                            keys,
                            sample_df.iloc[
                                test_samples
                            ]["Sample"],
                        )
                    ),
                )
            )
        info.update(
            splitter="StratifiedShuffleSplit(sample)",
            repeats=len(splits),
            validation_fraction=cfg[
                "validation_fraction"
            ],
        )
    elif method in ("loso", "logo"):
        if (
            method == "logo"
            and len(np.unique(labels)) < 3
        ):
            raise ValueError(
                "Outer LOGO requires at least three treatments."
            )
        split_groups = (
            keys if method == "loso" else labels
        )
        splits = list(
            LeaveOneGroupOut().split(
                np.zeros(len(keys)),
                groups=split_groups,
            )
        )
        info["splitter"] = (
            "LeaveOneGroupOut(sample)"
            if method == "loso"
            else "LeaveOneGroupOut(treatment)"
        )
    elif method == "kennard_stone":
        _, split_cfg = select_region(
            X,
            cfg,
            "Full range",
        )
        train_mask, test_mask, _, ks_info = (
            kennard_stone_split(
                X,
                keys,
                split_cfg,
            )
        )
        splits = [
            (
                np.flatnonzero(train_mask),
                np.flatnonzero(test_mask),
            )
        ]
        info.update(ks_info)
    else:
        raise ValueError(
            f"Unsupported validation method: {method}"
        )

    check_splits(splits, keys)
    if method == "monte_carlo" and any(
        len(np.unique(keys[test])) < 2
        for _, test in splits
    ):
        raise ValueError(
            "Monte Carlo validation requires at least "
            "two unique validation samples."
        )

    for number, (train, _) in enumerate(splits):
        inner_split_info(
            keys[train],
            labels[train],
            cfg,
            seed + number,
        )

    return splits, info


def run_outer_fold(
    number: int,
    split: tuple,
    X: np.ndarray,
    y: np.ndarray,
    keys: np.ndarray,
    labels: np.ndarray,
    axis: np.ndarray,
    cfg: dict,
) -> dict:
    started = time.time()
    train, test = split
    local = {
        **cfg,
        "random_seed": cfg["random_seed"] + number - 1,
        "model_role": "calibration_subset",
    }

    model, selected, removed, _ = (
        fit_calibration_model(
            X[train],
            y[train],
            keys[train],
            axis,
            local,
            labels[train],
        )
    )

    predicted_rows = predict_model_bundle(
        model,
        X[test],
        axis,
    )
    prediction = grouped_average_frame(
        y[test],
        predicted_rows,
        keys[test],
    )
    prediction.insert(
        0,
        "Outer Split",
        number,
    )
    prediction["Group"] = [
        str(
            labels[
                np.flatnonzero(keys == key)[0]
            ]
        )
        for key in prediction["Sample Key"]
    ]
    prediction["Residual"] = (
        prediction["Measured"]
        - prediction["Predicted"]
    )

    metrics = (
        regression_metrics(
            prediction["Measured"],
            prediction["Predicted"],
        )
        if len(prediction) > 1
        else {}
    )

    train_keys = keys[train]
    train_labels = labels[train]
    keep = ~np.isin(
        train_keys,
        model["removed_sample_ids"],
    )
    inner_info = inner_split_info(
        train_keys[keep],
        train_labels[keep],
        local,
        local["random_seed"],
    )[1]

    record = {
        "Outer Split": number,
        "Seed": local["random_seed"],
        "Calibration Samples": len(set(train_keys)),
        "Retained Calibration Samples": model[
            "training_sample_count"
        ],
        "Validation Samples": len(prediction),
        "Region": selected["Region"],
        "Preprocessing": selected["Preprocessing"],
        "Rank": selected["Rank"],
        "Internal RMSECV": selected["RMSECV"],
        "Removed Samples": "; ".join(
            map(str, removed)
        ),
        "Seconds": time.time() - started,
        **{
            f"Validation {key}": value
            for key, value in metrics.items()
        },
        **{
            f"Inner {key}": value
            for key, value in inner_info.items()
        },
    }

    if cfg["method"] == "loso":
        record.update(
            prediction.iloc[0][
                [
                    "Sample Key",
                    "Measured",
                    "Predicted",
                    "Residual",
                ]
            ].to_dict()
        )
    if cfg["method"] == "logo":
        record["Held-out Treatment"] = str(
            labels[test][0]
        )

    search = model[
        "calibration_search_results"
    ].assign(**{"Outer Split": number})
    model.update(
        validation_sample_ids=sorted(
            set(keys[test])
        ),
        holdout_metrics=metrics,
    )

    return {
        "record": record,
        "predictions": prediction,
        "search": search,
        "calibration_model": (
            model
            if cfg["method"] == "kennard_stone"
            else None
        ),
    }


def summarize_validation(
    predictions: pd.DataFrame,
    folds: pd.DataFrame,
    method: str,
) -> pd.DataFrame:
    if method == "monte_carlo":
        records = []
        for metric in (
            "R2",
            "RMSE",
            "RPIQ",
            "Bias",
        ):
            values = folds[
                f"Validation {metric}"
            ].dropna()
            records.append(
                {
                    "Metric": metric,
                    "Value": values.mean(),
                    "SD": values.std(ddof=1),
                    "Median": values.median(),
                    "2.5 Percentile": values.quantile(
                        0.025
                    ),
                    "97.5 Percentile": values.quantile(
                        0.975
                    ),
                    "Scope": (
                        "Mean over repeated random sample "
                        "holdouts; repeats are dependent"
                    ),
                }
            )
        return pd.DataFrame(records)

    scope = (
        "One spectrally selected holdout"
        if method == "kennard_stone"
        else (
            "Pooled outer predictions; one prediction "
            "per eligible sample"
        )
    )
    metrics = regression_metrics(
        predictions["Measured"],
        predictions["Predicted"],
    )
    return pd.DataFrame(
        [
            {
                "Metric": key,
                "Value": value,
                "Scope": scope,
            }
            for key, value in metrics.items()
        ]
    )


def _parallel_settings(
    cfg: dict,
) -> tuple[int, int | None]:
    outer_n_jobs = cfg.get(
        "outer_n_jobs",
        1,
    )
    if (
        isinstance(outer_n_jobs, bool)
        or not isinstance(
            outer_n_jobs,
            (int, np.integer),
        )
        or outer_n_jobs == 0
    ):
        raise ValueError(
            "outer_n_jobs must be a nonzero integer."
        )

    inner_thread_limit = cfg.get(
        "inner_thread_limit",
        1,
    )
    if inner_thread_limit is not None and (
        isinstance(inner_thread_limit, bool)
        or not isinstance(
            inner_thread_limit,
            (int, np.integer),
        )
        or inner_thread_limit < 1
    ):
        raise ValueError(
            "inner_thread_limit must be a positive integer or None."
        )

    return (
        int(outer_n_jobs),
        (
            None
            if inner_thread_limit is None
            else int(inner_thread_limit)
        ),
    )


def numerical_thread_context(
    cfg: dict,
):
    _, limit = _parallel_settings(cfg)
    if limit is None:
        return nullcontext()
    return threadpool_limits(
        limits=limit,
    )


def _run_outer_splits(
    splits: list,
    X: np.ndarray,
    y: np.ndarray,
    keys: np.ndarray,
    labels: np.ndarray,
    axis: np.ndarray,
    cfg: dict,
    progress_callback=None,
) -> list[dict]:
    outer_n_jobs, _ = _parallel_settings(
        cfg
    )
    total_steps = len(splits) + 1

    if outer_n_jobs == 1 or len(splits) == 1:
        results = []
        for number, split in enumerate(
            splits,
            1,
        ):
            if progress_callback is not None:
                progress_callback(
                    number - 1,
                    total_steps,
                    (
                        f"Outer split {number}/"
                        f"{len(splits)}"
                    ),
                )
            results.append(
                run_outer_fold(
                    number,
                    split,
                    X,
                    y,
                    keys,
                    labels,
                    axis,
                    cfg,
                )
            )
            if progress_callback is not None:
                progress_callback(
                    number,
                    total_steps,
                    (
                        f"Completed outer split "
                        f"{number}/{len(splits)}"
                    ),
                )
        return results

    if progress_callback is not None:
        progress_callback(
            0,
            total_steps,
            (
                f"Running {len(splits)} outer splits "
                f"with {outer_n_jobs} parallel workers"
            ),
        )

    generated = Parallel(
        n_jobs=outer_n_jobs,
        prefer="threads",
        require="sharedmem",
        return_as="generator_unordered",
    )(
        delayed(run_outer_fold)(
            number,
            split,
            X,
            y,
            keys,
            labels,
            axis,
            cfg,
        )
        for number, split in enumerate(
            splits,
            1,
        )
    )

    completed = 0
    by_number = {}
    for result in generated:
        number = int(
            result["record"][
                "Outer Split"
            ]
        )
        by_number[number] = result
        completed += 1
        if progress_callback is not None:
            progress_callback(
                completed,
                total_steps,
                (
                    f"Completed outer split {number}/"
                    f"{len(splits)} "
                    f"({completed}/{len(splits)} complete)"
                ),
            )

    return [
        by_number[number]
        for number in range(
            1,
            len(splits) + 1,
        )
    ]


def run_validation(
    X: np.ndarray,
    y: np.ndarray,
    keys: np.ndarray,
    labels: np.ndarray,
    axis: np.ndarray,
    cfg: dict,
    progress_callback=None,
) -> dict:
    started = time.time()
    if "_regions" not in cfg:
        cfg = prepare_region_config(
            cfg,
            axis,
        )

    splits, split_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assignments = []
    for number, (train, test) in enumerate(
        splits,
        1,
    ):
        for set_name, indices in (
            ("Calibration", train),
            ("Validation", test),
        ):
            for key in np.unique(keys[indices]):
                assignments.append(
                    {
                        "Outer Split": number,
                        "Sample Key": key,
                        "Set": set_name,
                        "Group": str(
                            labels[
                                np.flatnonzero(
                                    keys == key
                                )[0]
                            ]
                        ),
                    }
                )

    total_steps = len(splits) + 1
    outer_n_jobs, inner_thread_limit = (
        _parallel_settings(cfg)
    )
    split_info.update(
        {
            "outer_n_jobs": outer_n_jobs,
            "inner_thread_limit": (
                inner_thread_limit
            ),
        }
    )

    with numerical_thread_context(cfg):
        results = _run_outer_splits(
            splits,
            X,
            y,
            keys,
            labels,
            axis,
            cfg,
            progress_callback=progress_callback,
        )

        final_cfg = {
            **cfg,
            "model_role": "final_all_samples",
        }
        if progress_callback is not None:
            progress_callback(
                len(splits),
                total_steps,
                "Fitting final all-data model",
            )
        final_model, final_settings, _, final_search = (
            fit_calibration_model(
                X,
                y,
                keys,
                axis,
                final_cfg,
                labels,
            )
        )
    if progress_callback is not None:
        progress_callback(
            total_steps,
            total_steps,
            "Validation and final refit complete",
        )

    predictions = pd.concat(
        [
            result["predictions"]
            for result in results
        ],
        ignore_index=True,
    )

    if cfg["method"] in (
        "kfold",
        "loso",
        "logo",
    ):
        if (
            predictions["Sample Key"]
            .duplicated()
            .any()
            or set(predictions["Sample Key"])
            != set(keys)
        ):
            raise ValueError(
                "Outer predictions must cover every "
                "sample exactly once."
            )

    folds = pd.DataFrame(
        [
            result["record"]
            for result in results
        ]
    )
    summary = summarize_validation(
        predictions,
        folds,
        cfg["method"],
    )
    final_model.update(
        validation_scope=(
            "All-data refit has no independent holdout; "
            "reported outer scores evaluate model "
            "selection on supplied data"
        ),
        outer_split_info=split_info,
    )

    return {
        "summary": summary,
        "folds": folds,
        "predictions": predictions,
        "assignments": pd.DataFrame(
            assignments
        ),
        "optimization_results": pd.concat(
            [
                result["search"]
                for result in results
            ],
            ignore_index=True,
        ),
        "final_model": final_model,
        "final_settings": final_settings,
        "final_search": final_search,
        "split_info": split_info,
        "elapsed_seconds": time.time() - started,
        "unique_validation_samples": int(
            predictions["Sample Key"].nunique()
        ),
    }
