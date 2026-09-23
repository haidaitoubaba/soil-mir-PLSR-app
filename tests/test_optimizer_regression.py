import numpy as np
import pandas as pd
import pytest

from legacy_optimizer_reference import (
    legacy_optimize_plsr_grouped,
)
from soil_mir.modeling import (
    fit_calibration_model,
    optimize_plsr_grouped,
    predict_model_bundle,
)
from soil_mir.regions import prepare_region_config
from soil_mir.transforms import apply_transform


def _dataset():
    rng = np.random.default_rng(20260923)
    axis = np.linspace(600, 4000, 96)
    rows = []
    y = []
    keys = []
    labels = []

    for index in range(12):
        sample = f"S{index:02d}"
        group = str(index % 4)
        signal = (
            0.15
            + 0.00004 * axis
            + 0.035
            * np.sin(axis / 160 + index / 6)
            + 0.018
            * np.cos(axis / 95 + index / 4)
        )
        response = (
            2.0
            + index * 0.45
            + 0.4 * np.sin(index / 2.5)
        )
        for _ in range(2):
            rows.append(
                signal
                + rng.normal(
                    0,
                    0.0015,
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


def _config(axis):
    cfg = {
        "wn_min": 600.0,
        "wn_max": 4000.0,
        "exclude_co2": False,
        "co2_exclude_min": 2300.0,
        "co2_exclude_max": 2400.0,
        "sg_window": 9,
        "sg_polyorder": 2,
        "max_rank": 3,
        "region_search_n_windows": 3,
        "rmsecv_tolerance_pct": 5.0,
        "outlier_max_pct": 0.0,
        "random_seed": 42,
        "internal_cv_folds": 3,
        "method": "kfold",
        "property_name": "synthetic_STC",
        "units": "g C/kg soil",
        "transform": "sqrt",
        "model_role": "final_all_samples",
    }
    return prepare_region_config(cfg, axis)


def test_backward_region_optimizer_matches_legacy():
    X, y, keys, labels, axis = _dataset()
    cfg = _config(axis)
    y_t, lam = apply_transform(y, "sqrt")

    expected_frame, expected_best = (
        legacy_optimize_plsr_grouped(
            X,
            y,
            keys,
            labels,
            cfg,
            "sqrt",
            42,
        )
    )
    actual_frame, actual_best = optimize_plsr_grouped(
        X,
        y_t,
        y,
        keys,
        labels,
        cfg,
        "sqrt",
        lam,
        42,
    )

    assert actual_best["Region"] == expected_best["Region"]
    assert (
        actual_best["Preprocessing"]
        == expected_best["Preprocessing"]
    )
    assert actual_best["Rank"] == expected_best["Rank"]

    numeric = [
        "RMSECV",
        "R2_CV",
        "RPIQ_CV",
        "Bias_CV",
    ]
    np.testing.assert_allclose(
        actual_frame[numeric].to_numpy(dtype=float),
        expected_frame[numeric].to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    pd.testing.assert_series_equal(
        actual_frame["Selected"],
        expected_frame["Selected"],
        check_names=False,
    )


def test_final_calibration_bundle_is_self_consistent():
    X, y, keys, labels, axis = _dataset()
    cfg = _config(axis)

    bundle, best, removed, search = (
        fit_calibration_model(
            X,
            y,
            keys,
            axis,
            cfg,
            labels,
        )
    )

    assert removed == []
    assert bundle["selected_region"] == best["Region"]
    assert (
        bundle["selected_preprocessing"]
        == best["Preprocessing"]
    )
    assert bundle["selected_rank"] == best["Rank"]
    assert search["Selected"].sum() == 1

    predictions = predict_model_bundle(
        bundle,
        X,
        axis,
    )
    assert predictions.shape == y.shape
    assert np.isfinite(predictions).all()
    assert bundle["training_sample_count"] == 12
    assert bundle["training_spectrum_count"] == 24
    assert bundle["selected_calibration_rmsecv"] == pytest.approx(
        best["RMSECV"]
    )
