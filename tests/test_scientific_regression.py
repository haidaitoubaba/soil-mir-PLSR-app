from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from legacy_reference import (
    PREPROCESSING_NAMES,
    apply_transform as legacy_apply_transform,
    back_transform as legacy_back_transform,
    choose_with_tolerance as legacy_choose_with_tolerance,
    fit_transform_preprocessor as legacy_fit_transform_preprocessor,
    grouped_splits as legacy_grouped_splits,
    regression_metrics as legacy_regression_metrics,
)
from soil_mir.io.reference import read_property_sheet
from soil_mir.metrics import regression_metrics
from soil_mir.preprocessing import fit_transform_preprocessor
from soil_mir.regions import choose_with_tolerance
from soil_mir.splits import grouped_splits
from soil_mir.transforms import apply_transform, back_transform


FIXTURE = Path(__file__).parent / "fixtures" / "soil_mir_202"
WORKBOOK = FIXTURE / "reference" / "reference_202_stc_stn.xlsx"


@pytest.fixture
def spectral_matrix():
    rng = np.random.default_rng(20260923)
    axis = np.linspace(600, 4000, 256)
    rows = []
    for sample in range(24):
        baseline = (
            0.15
            + 0.00004 * axis
            + 0.05 * np.sin(axis / 170 + sample / 8)
            + 0.03 * np.exp(-((axis - (1450 + sample * 8)) / 180) ** 2)
        )
        for replicate in range(3):
            rows.append(baseline + rng.normal(0, 0.002 + replicate * 0.0002, len(axis)))
    return np.asarray(rows), axis


def test_real_stc_stn_sqrt_transform_matches_legacy():
    for sheet in ("202_STC", "202_STN"):
        frame = read_property_sheet(WORKBOOK, sheet)
        y = frame["Reference Value"].to_numpy(dtype=float)
        legacy, legacy_lam = legacy_apply_transform(y, "sqrt")
        current, current_lam = apply_transform(y, "sqrt")
        np.testing.assert_allclose(current, legacy, rtol=0, atol=0)
        assert current_lam == legacy_lam
        np.testing.assert_allclose(
            back_transform(current, "sqrt", current_lam),
            legacy_back_transform(legacy, "sqrt", legacy_lam),
            rtol=0,
            atol=1e-12,
        )


@pytest.mark.parametrize("method", ["none", "sqrt", "log", "log10", "cbrt", "boxcox", "yeojohnson"])
def test_all_response_transforms_match_legacy(method):
    y = np.array([0.4, 0.8, 1.2, 2.5, 4.0, 7.5], dtype=float)
    if method == "boxcox":
        y = y + 0.2
    expected, expected_lam = legacy_apply_transform(y, method)
    actual, actual_lam = apply_transform(y, method)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    if expected_lam is None:
        assert actual_lam is None
    else:
        assert actual_lam == pytest.approx(expected_lam, rel=1e-12, abs=1e-12)
    np.testing.assert_allclose(
        back_transform(actual, method, actual_lam),
        legacy_back_transform(expected, method, expected_lam),
        rtol=1e-11,
        atol=1e-11,
    )


@pytest.mark.parametrize("prep_name", PREPROCESSING_NAMES)
def test_preprocessing_matches_legacy(spectral_matrix, prep_name):
    X, _ = spectral_matrix
    cfg = {"sg_window": 11, "sg_polyorder": 2, "_segment_lengths": [128, 128]}
    expected_state, expected = legacy_fit_transform_preprocessor(prep_name, X, cfg)
    actual_state, actual = fit_transform_preprocessor(prep_name, X, cfg)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    assert actual_state["name"] == expected_state["name"]
    assert actual_state["segment_lengths"] == expected_state["segment_lengths"]
    if prep_name == "1st Deriv + MSC":
        np.testing.assert_allclose(
            actual_state["msc_reference"], expected_state["msc_reference"], rtol=0, atol=0
        )


def test_metrics_match_legacy_on_stc_like_values():
    measured = np.array([2.4, 3.1, 5.8, 8.9, 12.2, 15.4])
    predicted = np.array([2.6, 3.0, 5.5, 9.2, 11.8, 15.1])
    expected = legacy_regression_metrics(measured, predicted)
    actual = regression_metrics(measured, predicted)
    assert actual == pytest.approx(expected, rel=1e-14, abs=1e-14)


def test_rank_tolerance_rule_matches_legacy():
    candidates = pd.DataFrame(
        [
            {"Region": "Full range", "Preprocessing": "1st Derivative", "Rank": 6, "RMSECV": 0.300},
            {"Region": "W01", "Preprocessing": "1st Deriv + SNV", "Rank": 4, "RMSECV": 0.309},
            {"Region": "W02", "Preprocessing": "1st Deriv + MSC", "Rank": 3, "RMSECV": 0.320},
            {"Region": "W03", "Preprocessing": "1st Deriv + SLS", "Rank": 5, "RMSECV": 0.301},
        ]
    )
    expected_row, expected_decision = legacy_choose_with_tolerance(candidates, "RMSECV", 5)
    actual_row, actual_decision = choose_with_tolerance(candidates, "RMSECV", 5)
    assert actual_row.to_dict() == expected_row.to_dict()
    assert actual_decision == pytest.approx(expected_decision)


def test_grouped_outer_splits_match_legacy_fixture_design():
    manifest = pd.read_csv(FIXTURE / "manifest.csv")
    keys = np.repeat(manifest["Sample"].to_numpy(), 3)
    labels = np.repeat(manifest["Group"].astype(str).to_numpy(), 3)
    expected, expected_info = legacy_grouped_splits(keys, labels, 5, 42, outer=True)
    actual, actual_info = grouped_splits(keys, labels, 5, 42, outer=True)
    assert actual_info == expected_info
    assert len(actual) == len(expected)
    for (a_train, a_test), (e_train, e_test) in zip(actual, expected):
        np.testing.assert_array_equal(a_train, e_train)
        np.testing.assert_array_equal(a_test, e_test)
        assert not (set(keys[a_train]) & set(keys[a_test]))
