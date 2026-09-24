from __future__ import annotations


VALIDATION_METHOD_LABELS = {
    "kfold": "K-fold Cross-Validation",
    "monte_carlo": "Monte Carlo Repeated Holdout",
    "loso": "Leave-One-Sample-Out (LOSO)",
    "logo": "Leave-One-Group-Out (LOGO)",
    "kennard_stone": "Kennard–Stone Holdout",
}

VALIDATION_METHOD_DESCRIPTIONS = {
    "kfold": (
        "Unique samples are divided into K folds; each fold is used once "
        "for outer validation."
    ),
    "monte_carlo": (
        "Repeated random sample-level holdouts estimate performance across "
        "multiple calibration/validation splits."
    ),
    "loso": (
        "One unique sample is held out for outer validation at a time."
    ),
    "logo": (
        "One treatment/group is held out for outer validation at a time."
    ),
    "kennard_stone": (
        "A fixed validation subset is selected to represent the spectral "
        "space using the Kennard–Stone algorithm."
    ),
}


def validation_method_label(method: str) -> str:
    """Return a user-facing label while preserving unknown legacy keys."""
    key = str(method)
    return VALIDATION_METHOD_LABELS.get(
        key,
        key,
    )


def validation_method_description(method: str) -> str:
    """Return a short user-facing explanation for a validation method."""
    key = str(method)
    return VALIDATION_METHOD_DESCRIPTIONS.get(
        key,
        "",
    )


def format_analysis_key(key: str) -> str:
    """Format PROPERTY::method keys for user-facing run-history text."""
    value = str(key)
    if "::" not in value:
        return value
    property_name, method = value.split(
        "::",
        1,
    )
    return (
        f"{property_name} / "
        f"{validation_method_label(method)}"
    )
