from soil_mir.methods import (
    VALIDATION_METHOD_LABELS,
    format_analysis_key,
    validation_method_description,
    validation_method_label,
)


def test_validation_method_labels_cover_all_internal_keys():
    assert VALIDATION_METHOD_LABELS == {
        "kfold": "K-fold Cross-Validation",
        "monte_carlo": "Monte Carlo Repeated Holdout",
        "loso": "Leave-One-Sample-Out (LOSO)",
        "logo": "Leave-One-Group-Out (LOGO)",
        "kennard_stone": "Kennard–Stone Holdout",
    }


def test_validation_method_labels_do_not_change_internal_keys():
    keys = list(
        VALIDATION_METHOD_LABELS
    )
    assert keys == [
        "kfold",
        "monte_carlo",
        "loso",
        "logo",
        "kennard_stone",
    ]
    assert validation_method_label(
        "monte_carlo"
    ) == "Monte Carlo Repeated Holdout"
    assert validation_method_label(
        "legacy_method"
    ) == "legacy_method"


def test_validation_method_descriptions_are_available():
    for method in VALIDATION_METHOD_LABELS:
        assert validation_method_description(
            method
        ).strip()


def test_analysis_key_formatting_is_user_friendly():
    assert format_analysis_key(
        "202_STC::logo"
    ) == (
        "202_STC / "
        "Leave-One-Group-Out (LOGO)"
    )
    assert format_analysis_key(
        "unchanged"
    ) == "unchanged"
