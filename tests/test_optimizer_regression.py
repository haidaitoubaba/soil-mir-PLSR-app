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
    assert {"RPD_CV", "MAE_CV", "CCC_CV"} <= set(actual_frame.columns)
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



def test_optimizer_searches_explicit_new_preprocessing_candidates():
    X, y, keys, labels, axis = _dataset()
    cfg = _config(axis)
    cfg.update(
        {
            "preprocessing_methods": [
                "Raw Spectra",
                "SNV",
                "MSC",
                "SG Smoothing",
                "2nd Derivative",
                "2nd Deriv + SNV",
                "2nd Deriv + MSC",
            ],
            "region_search_n_windows": 1,
            "max_rank": 1,
        }
    )
    cfg = prepare_region_config(cfg, axis)
    y_t, lam = apply_transform(y, "sqrt")
    search, best = optimize_plsr_grouped(
        X, y_t, y, keys, labels, cfg, "sqrt", lam, 42
    )
    assert set(search["Preprocessing"]) == set(cfg["preprocessing_methods"])
    assert best["Preprocessing"] in cfg["preprocessing_methods"]
    assert search["Selected"].sum() == 1

    model, _, _, _ = fit_calibration_model(
        X, y, keys, axis, cfg, labels
    )
    assert model["selected_preprocessing"] in cfg["preprocessing_methods"]
    np.testing.assert_array_equal(
        predict_model_bundle(model, X, axis).shape, y.shape
    )


@pytest.mark.parametrize("name", ["Raw Spectra", "SG Smoothing", "2nd Deriv + MSC"])
def test_new_preprocessing_can_fit_and_predict_from_model_bundle(name):
    X, y, keys, labels, axis = _dataset()
    cfg = _config(axis)
    cfg.update({
        "preprocessing_methods": [name],
        "region_search_n_windows": 1,
        "max_rank": 1,
    })
    cfg = prepare_region_config(cfg, axis)
    model, best, _, _ = fit_calibration_model(X, y, keys, axis, cfg, labels)
    assert best["Preprocessing"] == name
    assert model["preprocessing_state"]["name"] == name
    predicted = predict_model_bundle(model, X, axis)
    assert predicted.shape == y.shape
    assert np.isfinite(predicted).all()
