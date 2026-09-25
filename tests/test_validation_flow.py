from threading import Event

import numpy as np
import pytest

from soil_mir.regions import prepare_region_config
from soil_mir.services.calibration import (
    CalibrationDataset,
    refit_final_model_only,
)
from soil_mir.splits import inner_split_info
from soil_mir.validation import (
    RunCancelled,
    outer_splits,
    run_validation,
)


def _dataset(groups=2):
    rng = np.random.default_rng(20260923)
    axis = np.linspace(600, 4000, 64)
    rows = []
    y = []
    keys = []
    labels = []

    for index in range(8):
        sample = f"S{index:02d}"
        group = str(index % groups)
        signal = (
            0.12
            + 0.00003 * axis
            + 0.03
            * np.sin(
                axis / 180 + index / 5
            )
        )
        response = 1.5 + index * 0.5
        for _ in range(2):
            rows.append(
                signal
                + rng.normal(
                    0,
                    0.001,
                    len(axis),
                )
            )
            y.append(response)
            keys.append(sample)
            labels.append(group)

    return (
        np.asarray(rows),
        np.asarray(y),
        np.asarray(keys),
        np.asarray(labels),
        axis,
    )


def _config(axis, method="kfold"):
    cfg = {
        "wn_min": 600.0,
        "wn_max": 4000.0,
        "exclude_co2": False,
        "co2_exclude_min": 2300.0,
        "co2_exclude_max": 2400.0,
        "sg_window": 7,
        "sg_polyorder": 2,
        "max_rank": 2,
        "region_search_n_windows": 2,
        "rmsecv_tolerance_pct": 5.0,
        "outlier_max_pct": 0.0,
        "random_seed": 42,
        "internal_cv_folds": 2,
        "outer_cv_folds": 2,
        "n_repeats": 2,
        "validation_fraction": 0.25,
        "ks_representation": "raw",
        "ks_pca_variance": 0.99,
        "method": method,
        "use_group_stratification": True,
        "property_name": "synthetic_STC",
        "units": "g C/kg soil",
        "transform": "sqrt",
        "model_role": "final_all_samples",
        "outer_n_jobs": 1,
        "inner_thread_limit": 1,
    }
    return prepare_region_config(
        cfg,
        axis,
    )


def test_outer_kfold_has_no_sample_leakage():
    X, _, keys, labels, axis = _dataset()
    cfg = _config(axis)

    splits, info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert len(splits) == 2
    assert info["actual_folds"] == 2
    for train, test in splits:
        assert not (
            set(keys[train])
            & set(keys[test])
        )


def test_nested_kfold_validation_covers_every_sample():
    X, y, keys, labels, axis = _dataset()
    cfg = _config(axis)

    result = run_validation(
        X,
        y,
        keys,
        labels,
        axis,
        cfg,
    )

    assert result[
        "unique_validation_samples"
    ] == 8
    assert set(
        result["predictions"]["Sample Key"]
    ) == set(keys)
    assert not result[
        "predictions"
    ]["Sample Key"].duplicated().any()
    assert set(
        result["summary"]["Metric"]
    ) == {
        "R2",
        "RMSE",
        "RPIQ",
        "Bias",
    }
    assert result["final_model"][
        "training_sample_count"
    ] == 8


def test_kennard_stone_split_is_deterministic():
    X, _, keys, labels, axis = _dataset()
    cfg = _config(
        axis,
        method="kennard_stone",
    )

    first, info_one = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )
    second, info_two = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    np.testing.assert_array_equal(
        first[0][0],
        second[0][0],
    )
    np.testing.assert_array_equal(
        first[0][1],
        second[0][1],
    )
    assert info_one == info_two
    assert (
        len(np.unique(keys[first[0][1]]))
        == 2
    )



def test_parallel_outer_validation_matches_sequential_results():
    X, y, keys, labels, axis = _dataset()

    sequential_cfg = _config(axis)
    sequential_cfg["outer_n_jobs"] = 1
    parallel_cfg = _config(axis)
    parallel_cfg["outer_n_jobs"] = 2

    sequential = run_validation(
        X,
        y,
        keys,
        labels,
        axis,
        sequential_cfg,
    )
    parallel = run_validation(
        X,
        y,
        keys,
        labels,
        axis,
        parallel_cfg,
    )

    sort_columns = [
        "Outer Split",
        "Sample Key",
    ]
    sequential_predictions = (
        sequential["predictions"]
        .sort_values(sort_columns)
        .reset_index(drop=True)
    )
    parallel_predictions = (
        parallel["predictions"]
        .sort_values(sort_columns)
        .reset_index(drop=True)
    )

    assert (
        sequential_predictions["Sample Key"].tolist()
        == parallel_predictions["Sample Key"].tolist()
    )
    np.testing.assert_allclose(
        sequential_predictions[
            ["Measured", "Predicted", "Residual"]
        ],
        parallel_predictions[
            ["Measured", "Predicted", "Residual"]
        ],
        rtol=0,
        atol=1e-12,
    )

    sequential_folds = (
        sequential["folds"]
        .sort_values("Outer Split")
        .reset_index(drop=True)
    )
    parallel_folds = (
        parallel["folds"]
        .sort_values("Outer Split")
        .reset_index(drop=True)
    )
    for column in (
        "Seed",
        "Region",
        "Preprocessing",
        "Rank",
        "Calibration Samples",
        "Validation Samples",
    ):
        assert (
            sequential_folds[column].tolist()
            == parallel_folds[column].tolist()
        )

    assert (
        sequential["final_settings"]
        == parallel["final_settings"]
    )
    assert (
        sequential["split_info"]["outer_n_jobs"]
        == 1
    )
    assert (
        parallel["split_info"]["outer_n_jobs"]
        == 2
    )
    assert (
        parallel["split_info"]["inner_thread_limit"]
        == 1
    )



def test_validation_honors_pre_requested_cancellation():
    X, y, keys, labels, axis = _dataset()
    cfg = _config(axis)
    cancel_event = Event()
    cancel_event.set()

    with pytest.raises(
        RunCancelled,
        match="cancelled",
    ):
        run_validation(
            X,
            y,
            keys,
            labels,
            axis,
            cfg,
            cancel_event=cancel_event,
        )



@pytest.mark.parametrize(
    ("method", "groups", "expected_splits"),
    [
        ("monte_carlo", 4, 2),
        ("loso", 4, 8),
        ("logo", 4, 4),
        ("kennard_stone", 4, 1),
    ],
)
def test_outer_validation_designs_keep_replicates_together(
    method,
    groups,
    expected_splits,
):
    X, _, keys, labels, axis = _dataset(
        groups=groups
    )
    cfg = _config(
        axis,
        method=method,
    )
    if method == "monte_carlo":
        cfg["validation_fraction"] = 0.50

    splits, _ = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert len(splits) == expected_splits
    for train, test in splits:
        assert not (
            set(keys[train])
            & set(keys[test])
        )

    if method == "loso":
        held_out = [
            set(keys[test]).pop()
            for _, test in splits
        ]
        assert set(held_out) == set(keys)
        assert all(
            len(np.unique(keys[test])) == 1
            for _, test in splits
        )

    if method == "logo":
        held_out_groups = [
            set(labels[test]).pop()
            for _, test in splits
        ]
        assert set(held_out_groups) == set(labels)
        assert all(
            len(np.unique(labels[test])) == 1
            for _, test in splits
        )


def test_monte_carlo_splits_are_reproducible():
    X, _, keys, labels, axis = _dataset(
        groups=4
    )
    cfg = _config(
        axis,
        method="monte_carlo",
    )
    cfg["validation_fraction"] = 0.50

    first, first_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )
    second, second_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert first_info == second_info
    assert len(first) == 2
    for (
        (first_train, first_test),
        (second_train, second_test),
    ) in zip(first, second):
        np.testing.assert_array_equal(
            first_train,
            second_train,
        )
        np.testing.assert_array_equal(
            first_test,
            second_test,
        )


def _light_method_config(
    axis,
    method,
):
    cfg = _config(
        axis,
        method=method,
    )
    cfg.update(
        {
            "max_rank": 1,
            "region_search_n_windows": 1,
            "internal_cv_folds": 2,
            "outer_n_jobs": 1,
        }
    )
    if method == "monte_carlo":
        cfg["validation_fraction"] = 0.50
    return prepare_region_config(
        cfg,
        axis,
    )


def test_monte_carlo_end_to_end_uses_repeat_summary():
    X, y, keys, labels, axis = _dataset(
        groups=4
    )
    cfg = _light_method_config(
        axis,
        "monte_carlo",
    )

    result = run_validation(
        X,
        y,
        keys,
        labels,
        axis,
        cfg,
    )

    assert len(result["folds"]) == 2
    assert set(
        result["summary"]["Metric"]
    ) == {
        "R2",
        "RMSE",
        "RPIQ",
        "Bias",
    }
    assert {
        "SD",
        "Median",
        "2.5 Percentile",
        "97.5 Percentile",
    } <= set(
        result["summary"].columns
    )
    assert result[
        "split_info"
    ]["repeats"] == 2


def test_kennard_stone_end_to_end_has_single_fixed_holdout():
    X, y, keys, labels, axis = _dataset(
        groups=4
    )
    cfg = _light_method_config(
        axis,
        "kennard_stone",
    )

    result = run_validation(
        X,
        y,
        keys,
        labels,
        axis,
        cfg,
    )

    assert len(result["folds"]) == 1
    assert result[
        "split_info"
    ]["representation"] == "raw"
    assert result[
        "unique_validation_samples"
    ] == 2
    assert (
        result["summary"]["Scope"]
        == "One spectrally selected holdout"
    ).all()



def test_final_only_refit_changes_tolerance_without_outer_validation():
    X, y, keys, labels, axis = _dataset(
        groups=4
    )
    dataset = CalibrationDataset(
        X=X,
        y=y,
        sample_ids=keys,
        group_labels=labels,
        wavenumbers=axis,
        property_name="synthetic_STC",
        units="g C/kg soil",
        transform="sqrt",
        exclude_co2=False,
        rows=len(X),
        unique_samples=len(
            np.unique(keys)
        ),
    )

    refit = refit_final_model_only(
        dataset,
        method="monte_carlo",
        max_rank=1,
        region_search_n_windows=1,
        rmsecv_tolerance_pct=4.0,
        sg_window=7,
        sg_polyorder=2,
        random_seed=42,
        internal_cv_folds=2,
        outer_cv_folds=2,
        n_repeats=2,
        validation_fraction=0.50,
        ks_representation="raw",
        ks_pca_variance=0.99,
        wn_min=600.0,
        wn_max=4000.0,
        outer_n_jobs=1,
        inner_thread_limit=1,
    )

    assert refit[
        "refit_tolerance_pct"
    ] == 4.0
    assert refit[
        "outer_validation_rerun"
    ] is False
    assert refit[
        "config"
    ]["rmsecv_tolerance_pct"] == 4.0
    assert refit[
        "final_model"
    ]["artifact_role"] == "final_only_refit"
    assert refit[
        "final_model"
    ]["outer_validation_rerun"] is False
    assert not refit[
        "final_search"
    ].empty


@pytest.mark.parametrize(
    "method",
    [
        "kfold",
        "monte_carlo",
        "loso",
        "kennard_stone",
    ],
)
def test_outer_splits_work_without_group_labels(
    method,
):
    X, _, keys, labels, axis = _dataset(
        groups=4
    )
    labels = np.full(
        labels.shape,
        "",
        dtype=object,
    )
    cfg = _config(
        axis,
        method=method,
    )
    if method == "monte_carlo":
        cfg["validation_fraction"] = 0.50

    splits, info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert splits
    assert (
        info["group_labels_complete"]
        is False
    )
    for train, test in splits:
        assert not (
            set(keys[train])
            & set(keys[test])
        )

    if method == "kfold":
        assert (
            info["splitter"]
            == "Shuffled sample KFold"
        )
    if method == "monte_carlo":
        assert (
            info["splitter"]
            == "ShuffleSplit(sample)"
        )


def test_logo_rejects_missing_group_labels():
    X, _, keys, labels, axis = _dataset(
        groups=4
    )
    labels = np.full(
        labels.shape,
        "",
        dtype=object,
    )
    cfg = _config(
        axis,
        method="logo",
    )

    with pytest.raises(
        ValueError,
        match="requires a Group column",
    ):
        outer_splits(
            X,
            keys,
            labels,
            cfg,
        )



def test_kfold_group_toggle_can_force_sample_level_splitting():
    X, _, keys, labels, axis = _dataset(
        groups=2
    )
    cfg = _config(
        axis,
        method="kfold",
    )

    _, grouped_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )
    assert (
        grouped_info["splitter"]
        == "StratifiedGroupKFold"
    )
    assert grouped_info[
        "group_stratification_requested"
    ] is True
    assert grouped_info[
        "group_stratification_used"
    ] is True

    cfg["use_group_stratification"] = False
    _, sample_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert (
        sample_info["splitter"]
        == "Shuffled sample KFold"
    )
    assert sample_info[
        "group_stratification_requested"
    ] is False
    assert sample_info[
        "group_stratification_used"
    ] is False
    assert sample_info[
        "inner_group_stratification_used"
    ] is False
    assert (
        sample_info["fallback_reason"]
        == "Group stratification disabled by configuration"
    )


def test_monte_carlo_group_toggle_can_force_unstratified_holdout():
    X, _, keys, labels, axis = _dataset(
        groups=2
    )
    cfg = _config(
        axis,
        method="monte_carlo",
    )
    cfg["validation_fraction"] = 0.50

    _, grouped_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )
    assert (
        grouped_info["splitter"]
        == "StratifiedShuffleSplit(sample)"
    )
    assert grouped_info[
        "group_stratification_used"
    ] is True

    cfg["use_group_stratification"] = False
    _, sample_info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert (
        sample_info["splitter"]
        == "ShuffleSplit(sample)"
    )
    assert sample_info[
        "group_stratification_requested"
    ] is False
    assert sample_info[
        "group_stratification_used"
    ] is False


def test_group_toggle_also_controls_non_logo_inner_cv():
    _, _, keys, labels, axis = _dataset(
        groups=2
    )
    cfg = _config(
        axis,
        method="kfold",
    )

    _, grouped_info = inner_split_info(
        keys,
        labels,
        cfg,
        42,
    )
    assert (
        grouped_info["splitter"]
        == "StratifiedGroupKFold"
    )

    cfg["use_group_stratification"] = False
    _, sample_info = inner_split_info(
        keys,
        labels,
        cfg,
        42,
    )
    assert sample_info["splitter"] == "GroupKFold"


def test_logo_requires_group_even_when_optional_group_toggle_is_off():
    X, _, keys, labels, axis = _dataset(
        groups=4
    )
    cfg = _config(
        axis,
        method="logo",
    )
    cfg["use_group_stratification"] = False

    splits, info = outer_splits(
        X,
        keys,
        labels,
        cfg,
    )

    assert len(splits) == 4
    assert (
        info["splitter"]
        == "LeaveOneGroupOut(treatment)"
    )
    assert info[
        "group_stratification_requested"
    ] is True
    assert info[
        "group_stratification_used"
    ] is True
    assert info[
        "inner_group_stratification_used"
    ] is True
