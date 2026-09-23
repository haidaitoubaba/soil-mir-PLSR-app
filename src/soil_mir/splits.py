from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import (
    GroupKFold,
    KFold,
    LeaveOneGroupOut,
    StratifiedGroupKFold,
)


def validate_sample_labels(keys: np.ndarray, labels: np.ndarray) -> None:
    if (
        len(keys) != len(labels)
        or not len(keys)
        or pd.isna(keys).any()
        or pd.isna(labels).any()
    ):
        raise ValueError(
            "Sample IDs and treatment labels must be nonempty, complete and aligned."
        )
    if any(not str(v).strip() for v in list(keys) + list(labels)):
        raise ValueError("Sample IDs and treatment labels must not be blank.")
    if (
        pd.DataFrame({"Sample": keys, "Group": labels})
        .groupby("Sample")["Group"]
        .nunique()
        .gt(1)
        .any()
    ):
        raise ValueError("Each sample must belong to exactly one treatment.")


def check_splits(splits: list, keys: np.ndarray) -> None:
    for train, test in splits:
        if not len(train) or not len(test) or len(np.unique(keys[train])) < 2:
            raise ValueError(
                "Each fold needs at least two training samples and one validation sample."
            )
        if set(keys[train]) & set(keys[test]):
            raise ValueError("Replicate spectra cross the split boundary.")


def grouped_splits(
    keys: np.ndarray,
    labels: np.ndarray,
    count: int,
    seed: int,
    outer: bool = False,
) -> tuple[list, dict]:
    validate_sample_labels(keys, labels)
    n_samples = len(np.unique(keys))
    if outer and n_samples < count:
        raise ValueError(f"Outer {count}-fold CV requires at least {count} samples.")

    actual = min(count, n_samples)
    if actual < 2:
        raise ValueError("At least two samples are required for inner CV.")

    splits = None
    _, label_counts = np.unique(labels, return_counts=True)
    if len(np.unique(labels)) > 1 and min(label_counts) >= actual:
        candidate = list(
            StratifiedGroupKFold(
                n_splits=actual,
                shuffle=True,
                random_state=seed,
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
                for a, b in KFold(
                    actual,
                    shuffle=True,
                    random_state=seed,
                ).split(samples)
            ]
        else:
            splits = list(GroupKFold(actual).split(np.zeros(len(keys)), groups=keys))

    if any(
        not len(a) or not len(b) or len(a) < 2 or set(keys[a]) & set(keys[b])
        for a, b in splits
    ):
        raise ValueError("Inner folds lack enough training spectra or overlap sample IDs.")

    return splits, {
        "splitter": (
            "StratifiedGroupKFold"
            if not fallback
            else ("Shuffled sample KFold" if outer else "GroupKFold")
        ),
        "requested_folds": count,
        "actual_folds": actual,
        "fallback": fallback,
        "fallback_reason": (
            "Treatment balancing unavailable or infeasible" if fallback else ""
        ),
        "seed": seed,
    }


def inner_split_info(
    keys: np.ndarray,
    labels: np.ndarray,
    cfg: dict,
    seed: int,
) -> tuple[list, dict]:
    if cfg["method"] == "logo":
        validate_sample_labels(keys, labels)
        if len(np.unique(labels)) < 2:
            raise ValueError("Inner LOGO requires at least two treatments.")
        splits = list(
            LeaveOneGroupOut().split(np.zeros(len(keys)), groups=labels)
        )
        check_splits(splits, keys)
        return splits, {
            "splitter": "LeaveOneGroupOut(treatment)",
            "actual_folds": len(splits),
            "fallback": False,
            "seed": seed,
        }

    return grouped_splits(
        keys,
        labels,
        cfg["internal_cv_folds"],
        seed,
    )


def cv_splits_for_training(
    groups: np.ndarray,
    strata: np.ndarray,
    cfg: dict,
    random_state: int,
) -> list:
    return inner_split_info(groups, strata, cfg, random_state)[0]
