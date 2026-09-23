import numpy as np

from soil_mir.regions import prepare_region_config
from soil_mir.validation import (
    outer_splits,
    run_validation,
)


def _dataset():
    rng = np.random.default_rng(20260923)
    axis = np.linspace(600, 4000, 64)
    rows = []
    y = []
    keys = []
    labels = []

    for index in range(8):
        sample = f"S{index:02d}"
        group = str(index % 2)
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
        "property_name": "synthetic_STC",
        "units": "g C/kg soil",
        "transform": "sqrt",
        "model_role": "final_all_samples",
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
