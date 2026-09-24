from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import (
    GroupKFold,
    KFold,
    LeaveOneGroupOut,
    StratifiedGroupKFold,
)


def validate_sample_ids(keys: np.ndarray) -> None:
    keys = np.asarray(keys)
    if (
        not len(keys)
        or pd.isna(keys).any()
        or any(not str(value).strip() for value in keys)
    ):
        raise ValueError(
            "Sample IDs must be nonempty and complete."
        )


def _normalised_labels(
    labels: np.ndarray,
) -> np.ndarray:
    values = np.asarray(labels, dtype=object)
    return np.asarray(
        [
            ""
            if pd.isna(value)
            else str(value).strip()
            for value in values
        ],
        dtype=object,
    )


def treatment_labels_complete(
    keys: np.ndarray,
    labels: np.ndarray,
) -> bool:
    """Return whether every row has a consistent, nonblank group label."""
    validate_sample_ids(keys)
    labels = np.asarray(labels, dtype=object)
    if len(keys) != len(labels):
        raise ValueError(
            "Sample IDs and treatment labels must be aligned."
        )

    normalised = _normalised_labels(labels)
    known = pd.DataFrame(
        {
            "Sample": np.asarray(keys),
            "Group": normalised,
        }
    )
    known = known[known["Group"] != ""]
    if (
        not known.empty
        and known.groupby("Sample")["Group"]
        .nunique()
        .gt(1)
        .any()
    ):
        raise ValueError(
            "Each sample must belong to exactly one treatment."
        )
    return bool(np.all(normalised != ""))


def validate_sample_labels(
    keys: np.ndarray,
    labels: np.ndarray,
) -> None:
    """Validate labels for methods that explicitly require treatment groups."""
    if not treatment_labels_complete(
        keys,
        labels,
    ):
        raise ValueError(
            "Treatment labels must be nonempty and complete."
        )


def check_splits(splits: list, keys: np.ndarray) -> None:
    for train, test in splits:
        if (
            not len(train)
            or not len(test)
            or len(np.unique(keys[train])) < 2
        ):
            raise ValueError(
                "Each fold needs at least two training samples "
                "and one validation sample."
            )
        if set(keys[train]) & set(keys[test]):
            raise ValueError(
                "Replicate spectra cross the split boundary."
            )


def grouped_splits(
    keys: np.ndarray,
    labels: np.ndarray,
    count: int,
    seed: int,
    outer: bool = False,
) -> tuple[list, dict]:
    validate_sample_ids(keys)
    labels_complete = treatment_labels_complete(
        keys,
        labels,
    )
    normalised = _normalised_labels(labels)

    n_samples = len(np.unique(keys))
    if outer and n_samples < count:
        raise ValueError(
            f"Outer {count}-fold CV requires at least {count} samples."
        )

    actual = min(count, n_samples)
    if actual < 2:
        raise ValueError(
            "At least two samples are required for inner CV."
        )

    splits = None
    if labels_complete:
        _, label_counts = np.unique(
            normalised,
            return_counts=True,
        )
        if (
            len(np.unique(normalised)) > 1
            and min(label_counts) >= actual
        ):
            candidate = list(
                StratifiedGroupKFold(
                    n_splits=actual,
                    shuffle=True,
                    random_state=seed,
                ).split(
                    np.zeros(len(keys)),
                    normalised,
                    keys,
                )
            )
            if all(
                len(train) and len(test)
                for train, test in candidate
            ):
                splits = candidate

    fallback = splits is None
    if fallback:
        if outer:
            samples = np.unique(keys)
            splits = [
                (
                    np.flatnonzero(
                        np.isin(keys, samples[train])
                    ),
                    np.flatnonzero(
                        np.isin(keys, samples[test])
                    ),
                )
                for train, test in KFold(
                    actual,
                    shuffle=True,
                    random_state=seed,
                ).split(samples)
            ]
        else:
            splits = list(
                GroupKFold(actual).split(
                    np.zeros(len(keys)),
                    groups=keys,
                )
            )

    if any(
        not len(train)
        or not len(test)
        or len(train) < 2
        or set(keys[train]) & set(keys[test])
        for train, test in splits
    ):
        raise ValueError(
            "Inner folds lack enough training spectra "
            "or overlap sample IDs."
        )

    return splits, {
        "splitter": (
            "StratifiedGroupKFold"
            if not fallback
            else (
                "Shuffled sample KFold"
                if outer
                else "GroupKFold"
            )
        ),
        "requested_folds": count,
        "actual_folds": actual,
        "fallback": fallback,
        "fallback_reason": (
            "Treatment labels unavailable, incomplete, or infeasible"
            if fallback
            else ""
        ),
        "group_stratification_used": not fallback,
        "seed": seed,
    }


def inner_split_info(
    keys: np.ndarray,
    labels: np.ndarray,
    cfg: dict,
    seed: int,
) -> tuple[list, dict]:
    if cfg["method"] == "logo":
        if not treatment_labels_complete(
            keys,
            labels,
        ):
            raise ValueError(
                "Leave-One-Group-Out (LOGO) requires a Group column "
                "with non-missing group labels for every sample."
            )
        normalised = _normalised_labels(labels)
        if len(np.unique(normalised)) < 2:
            raise ValueError(
                "Inner LOGO requires at least two treatments."
            )
        splits = list(
            LeaveOneGroupOut().split(
                np.zeros(len(keys)),
                groups=normalised,
            )
        )
        check_splits(splits, keys)
        return splits, {
            "splitter": "LeaveOneGroupOut(treatment)",
            "actual_folds": len(splits),
            "fallback": False,
            "group_stratification_used": True,
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
    return inner_split_info(
        groups,
        strata,
        cfg,
        random_state,
    )[0]
