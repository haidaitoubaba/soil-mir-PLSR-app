from __future__ import annotations

import joblib
import numpy as np
import pytest
from scipy.signal import savgol_filter

from soil_mir.modeling import build_cv_preprocessing_cache
from soil_mir.preprocessing import (
    LEGACY_PREPROCESSING_NAMES,
    PREPROCESSING_NAMES,
    configured_preprocessing_methods,
    fit_transform_preprocessor,
    msc,
    spectral_preprocessing_base,
    snv,
    transform_preprocessor,
)
from soil_mir.regions import prepare_region_config


@pytest.fixture
def spectra():
    rng = np.random.default_rng(20261111)
    axis = np.linspace(600.0, 4000.0, 48)
    return np.asarray([
        0.15
        + 0.00003 * axis
        + 0.025 * np.sin(axis / 125 + index / 3)
        + rng.normal(0, 0.0005, len(axis))
        for index in range(8)
    ])


@pytest.fixture
def options():
    return {"sg_window": 7, "sg_polyorder": 2, "_segment_lengths": [24, 24]}


def test_all_eleven_methods_are_registered_and_legacy_default_is_preserved():
    assert len(PREPROCESSING_NAMES) == 11
    assert len(set(PREPROCESSING_NAMES)) == 11
    assert configured_preprocessing_methods({"sg_polyorder": 2}) == (
        LEGACY_PREPROCESSING_NAMES
    )
    assert configured_preprocessing_methods({
        "sg_polyorder": 2,
        "preprocessing_methods": list(PREPROCESSING_NAMES),
    }) == PREPROCESSING_NAMES


@pytest.mark.parametrize("name", PREPROCESSING_NAMES)
def test_fit_and_saved_transform_agree_for_every_method(spectra, options, name, tmp_path):
    state, fitted = fit_transform_preprocessor(name, spectra, options)
    np.testing.assert_allclose(
        transform_preprocessor(state, spectra),
        fitted,
        rtol=1e-11,
        atol=1e-11,
    )
    saved = tmp_path / "model_state.joblib"
    joblib.dump(state, saved)
    np.testing.assert_allclose(
        transform_preprocessor(joblib.load(saved), spectra),
        fitted,
        rtol=1e-11,
        atol=1e-11,
    )
    assert fitted.shape == spectra.shape
    assert np.isfinite(fitted).all()


def test_raw_snv_and_msc_do_not_apply_a_derivative(spectra, options):
    raw, raw_values = fit_transform_preprocessor("Raw Spectra", spectra, options)
    np.testing.assert_array_equal(raw_values, spectra)
    np.testing.assert_array_equal(transform_preprocessor(raw, spectra), spectra)

    _, snv_values = fit_transform_preprocessor("SNV", spectra, options)
    np.testing.assert_allclose(snv_values, snv(spectra), rtol=1e-12, atol=1e-12)
    _, msc_values = fit_transform_preprocessor("MSC", spectra, options)
    np.testing.assert_allclose(
        msc_values,
        msc(spectra, reference=spectra.mean(axis=0)),
        rtol=1e-12,
        atol=1e-12,
    )


@pytest.mark.parametrize(
    ("name", "derivative"),
    [
        ("SG Smoothing", 0),
        ("2nd Derivative", 2),
        ("2nd Deriv + SNV", 2),
        ("2nd Deriv + MSC", 2),
    ],
)
def test_sg_operations_are_segmentwise(spectra, options, name, derivative):
    base = spectral_preprocessing_base(name, spectra, options)
    expected = np.concatenate(
        [
            savgol_filter(
                spectra[:, segment],
                window_length=options["sg_window"],
                polyorder=options["sg_polyorder"],
                deriv=derivative,
                axis=1,
            )
            for segment in (slice(0, 24), slice(24, 48))
        ],
        axis=1,
    )
    np.testing.assert_allclose(base, expected, rtol=0, atol=1e-12)


@pytest.mark.parametrize("name", ["MSC", "1st Deriv + MSC", "2nd Deriv + MSC"])
def test_msc_uses_only_training_spectra_inside_cv(spectra, options, name):
    train = np.array([0, 1, 2, 3, 4])
    test = np.array([5, 6, 7])
    split = [(train, test)]
    folds = build_cv_preprocessing_cache(spectra, split, name, options)
    changed = spectra.copy()
    changed[test] += np.linspace(10.0, 25.0, spectra.shape[1])
    changed_folds = build_cv_preprocessing_cache(changed, split, name, options)
    np.testing.assert_allclose(
        folds[0]["X_train_prep"],
        changed_folds[0]["X_train_prep"],
        rtol=0,
        atol=1e-12,
    )
    state, train_prepared = fit_transform_preprocessor(name, spectra[train], options)
    np.testing.assert_allclose(folds[0]["X_train_prep"], train_prepared)
    np.testing.assert_allclose(
        folds[0]["X_test_prep"],
        transform_preprocessor(state, spectra[test]),
    )
    np.testing.assert_allclose(
        state["msc_reference"],
        spectral_preprocessing_base(name, spectra[train], options).mean(axis=0),
    )


def test_methods_without_sg_accept_short_spectral_intervals(spectra):
    tiny = spectra[:, :6]
    options = {"sg_window": 11, "sg_polyorder": 2, "_segment_lengths": [2, 4]}
    for name in ("Raw Spectra", "SNV", "MSC"):
        state, values = fit_transform_preprocessor(name, tiny, options)
        assert values.shape == tiny.shape
        np.testing.assert_allclose(transform_preprocessor(state, tiny), values)

    config = prepare_region_config(
        {
            "wn_min": 600.0,
            "wn_max": 605.0,
            "sg_window": 11,
            "sg_polyorder": 2,
            "region_search_n_windows": 1,
            "preprocessing_methods": ["Raw Spectra"],
        },
        np.linspace(600.0, 605.0, 6),
    )
    assert config["_regions"]["Full range"]["error"] == ""


def test_invalid_candidate_selection_and_second_derivative_parameters(spectra):
    for methods in ([], ["Unknown"], ["SNV", "SNV"]):
        with pytest.raises(ValueError, match="preprocessing"):
            configured_preprocessing_methods(
                {"preprocessing_methods": methods, "sg_polyorder": 2}
            )
    with pytest.raises(ValueError, match="polynomial order"):
        configured_preprocessing_methods(
            {"preprocessing_methods": ["2nd Derivative"], "sg_polyorder": 1}
        )
    with pytest.raises(ValueError, match="polynomial order"):
        fit_transform_preprocessor(
            "2nd Derivative",
            spectra,
            {"sg_window": 7, "sg_polyorder": 1},
        )
