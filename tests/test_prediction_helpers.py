from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from soil_mir.services import prediction
from soil_mir.services.prediction import (
    load_model_bundle,
    predict_external_dataset,
    resample_spectra_to_model_grid,
    save_prediction_results,
)


class _FirstColumnModel:
    def predict(self, X):
        X = np.asarray(X, dtype=float)
        return X[:, [0]]


def _bundle(wavenumbers):
    return {
        "preprocessing_state": {"name": "unused"},
        "pls_model": _FirstColumnModel(),
        "wavenumbers": np.asarray(
            wavenumbers,
            dtype=float,
        ),
        "response_transform": "none",
        "response_transform_parameter": None,
        "property_name": "STC",
        "units": "g C/kg soil",
    }


def test_invalid_model_bundle_is_rejected(tmp_path):
    path = tmp_path / "bad.joblib"
    joblib.dump(
        {"property_name": "STC"},
        path,
    )

    with pytest.raises(
        ValueError,
        match="missing required keys",
    ):
        load_model_bundle(path)


def test_model_grid_resampling_allows_tiny_boundary_extrapolation():
    raw_axis = np.array(
        [1000.1, 1001.1, 1002.1]
    )
    model_axis = np.array(
        [1000.0, 1001.0, 1002.2]
    )
    spectra = np.vstack(
        [
            2 * raw_axis + 1,
            -0.5 * raw_axis + 4,
        ]
    )

    actual = resample_spectra_to_model_grid(
        spectra,
        raw_axis,
        model_axis,
        max_extrapolation_cm1=0.25,
    )

    expected = np.vstack(
        [
            2 * model_axis + 1,
            -0.5 * model_axis + 4,
        ]
    )
    np.testing.assert_allclose(
        actual,
        expected,
        rtol=0,
        atol=1e-10,
    )


def test_model_grid_resampling_rejects_large_boundary_gap():
    with pytest.raises(
        ValueError,
        match="do not cover the model wavenumber range",
    ):
        resample_spectra_to_model_grid(
            np.ones((2, 3)),
            np.array(
                [1000.3, 1001.3, 1002.3]
            ),
            np.array(
                [1000.0, 1001.0, 1002.0]
            ),
            max_extrapolation_cm1=0.25,
        )


def test_external_prediction_uses_reference_order_and_sample_mapping(
    monkeypatch,
):
    axis = np.array([1000.0, 1001.0])
    spectra = {
        "A_2.0": np.array([2.0, 20.0]),
        "A_1.0": np.array([1.0, 10.0]),
        "B_1.0": np.array([4.0, 40.0]),
    }
    reference = pd.DataFrame(
        {
            "Sample": ["A", "A", "B"],
            "File Name": [
                "A_1.0",
                "A_2.0",
                "B_1.0",
            ],
            "Reference Value": [
                1.0,
                2.0,
                4.0,
            ],
        }
    )
    monkeypatch.setattr(
        prediction,
        "transform_preprocessor",
        lambda _state, X: X,
    )
    monkeypatch.setattr(
        prediction,
        "back_transform",
        lambda y, _method, _parameter: y,
    )

    replicate, sample, metrics = (
        predict_external_dataset(
            _bundle(axis),
            spectra,
            axis,
            reference,
        )
    )

    assert replicate["File Name"].tolist() == [
        "A_1.0",
        "A_2.0",
        "B_1.0",
    ]
    assert replicate["Sample"].tolist() == [
        "A",
        "A",
        "B",
    ]
    np.testing.assert_allclose(
        replicate["Predicted"],
        [1.0, 2.0, 4.0],
    )
    sample = sample.set_index("Sample")
    assert sample.loc["A", "Predicted"] == 1.5
    assert sample.loc["A", "Measured"] == 1.5
    assert metrics["Samples"] == 2
    assert metrics["Spectra"] == 3
    assert metrics["RMSE"] == pytest.approx(0.0)


def test_prediction_without_reference_treats_each_file_as_sample(
    monkeypatch,
):
    axis = np.array([1000.0, 1001.0])
    spectra = {
        "A.1": np.array([2.0, 20.0]),
        "A.0": np.array([1.0, 10.0]),
    }
    monkeypatch.setattr(
        prediction,
        "transform_preprocessor",
        lambda _state, X: X,
    )
    monkeypatch.setattr(
        prediction,
        "back_transform",
        lambda y, _method, _parameter: y,
    )

    replicate, sample, metrics = (
        predict_external_dataset(
            _bundle(axis),
            spectra,
            axis,
        )
    )

    assert replicate["Sample"].tolist() == [
        "A.0",
        "A.1",
    ]
    assert sample["Sample"].tolist() == [
        "A.0",
        "A.1",
    ]
    assert metrics == {
        "Samples": 2,
        "Spectra": 2,
    }


def test_external_library_uses_shared_alignment_and_cache(
    monkeypatch,
    tmp_path,
):
    for name in ("A.0", "B.0"):
        (tmp_path / name).write_bytes(b"x")

    raw = {
        "A.0": (
            np.array([4.0, 3.0, 2.0, 1.0]),
            np.array(
                [4000.0, 3000.0, 2000.0, 1000.0]
            ),
        ),
        "B.0": (
            np.array([3.9, 2.9, 1.9, 0.9]),
            np.array(
                [3999.0, 2999.0, 1999.0, 999.0]
            ),
        ),
    }
    stats = SimpleNamespace(
        hits=0,
        misses=2,
        requested=2,
        cache_path=None,
    )
    monkeypatch.setattr(
        prediction,
        "load_opus_spectra_cached",
        lambda *args, **kwargs: (raw, stats),
    )

    spectra, axis, returned_stats = (
        prediction.load_external_opus_library(
            tmp_path
        )
    )

    np.testing.assert_array_equal(
        axis,
        np.array([3000.0, 2000.0, 1000.0]),
    )
    assert set(spectra) == {"A.0", "B.0"}
    assert returned_stats is stats



def test_prediction_workbook_matches_authoritative_sheet_layout(
    tmp_path,
):
    replicate = pd.DataFrame(
        {
            "Sample": ["A", "A"],
            "File Name": ["A.0", "A.1"],
            "Measured": [1.0, 1.0],
            "Predicted": [0.9, 1.1],
            "Residual": [0.1, -0.1],
        }
    )
    sample = pd.DataFrame(
        {
            "Sample": ["A"],
            "Measured": [1.0],
            "Predicted": [1.0],
        }
    )
    metrics = {
        "R2": 1.0,
        "RMSE": 0.0,
        "RPIQ": 1.0,
        "Bias": 0.0,
        "Samples": 1,
        "Spectra": 2,
    }
    bundle = {
        "property_name": "STC",
        "units": "g C/kg soil",
        "selected_preprocessing": "1st Deriv + SNV",
        "selected_rank": 5,
        "response_transform": "sqrt",
        "exclude_co2": True,
    }
    output = tmp_path / "prediction.xlsx"

    returned = save_prediction_results(
        replicate,
        sample,
        metrics,
        bundle,
        output,
        tmp_path / "Final_Model.joblib",
        "213_STC",
    )

    assert returned == output
    workbook = pd.ExcelFile(output)
    assert workbook.sheet_names == [
        "Replicate Predictions",
        "Sample Predictions",
        "Metrics",
        "Model Info",
    ]

    info = pd.read_excel(
        output,
        sheet_name="Model Info",
    ).set_index("Field")
    assert info.loc[
        "Reference sheet",
        "Value",
    ] == "213_STC"
    assert info.loc[
        "Property",
        "Value",
    ] == "STC"
