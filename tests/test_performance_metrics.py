import numpy as np
import pytest

from soil_mir.metrics import grouped_average_frame, regression_metrics


def test_additional_metrics_have_known_analytical_values():
    measured = np.array([1.0, 2.0, 3.0])
    predicted = np.array([1.0, 2.0, 4.0])
    metrics = regression_metrics(measured, predicted)

    assert metrics["RMSE"] == pytest.approx(np.sqrt(1 / 3))
    assert metrics["RPD"] == pytest.approx(np.sqrt(3))
    assert metrics["MAE"] == pytest.approx(1 / 3)
    assert metrics["CCC"] == pytest.approx(6 / 7)


def test_perfect_predictions_and_bias_penalty():
    measured = np.array([1.0, 2.0, 3.0])
    perfect = regression_metrics(measured, measured)
    assert perfect["RPD"] == float("inf")
    assert perfect["MAE"] == 0.0
    assert perfect["CCC"] == pytest.approx(1.0)

    shifted = regression_metrics(measured, measured + 1)
    assert shifted["MAE"] == 1.0
    assert shifted["Bias"] == -1.0
    assert shifted["CCC"] == pytest.approx(4 / 7)


def test_undefined_metrics_for_single_sample_and_constant_reference():
    one = regression_metrics([1.0], [1.0])
    assert set(one) == {"R2", "RMSE", "RPIQ", "Bias", "RPD", "MAE", "CCC"}
    assert all(np.isnan(value) for value in one.values())

    constant = regression_metrics([2.0, 2.0, 2.0], [2.0, 2.0, 2.0])
    assert np.isnan(constant["RPD"])
    assert np.isnan(constant["CCC"])
    assert constant["MAE"] == 0.0


def test_replicate_predictions_are_aggregated_before_metrics():
    grouped = grouped_average_frame(
        [1.0, 1.0, 3.0, 3.0],
        [0.0, 2.0, 2.0, 4.0],
        ["A", "A", "B", "B"],
    )
    metrics = regression_metrics(grouped["Measured"], grouped["Predicted"])
    assert len(grouped) == 2
    assert metrics["MAE"] == 0.0
    assert metrics["CCC"] == pytest.approx(1.0)
    assert metrics["RPD"] == float("inf")
