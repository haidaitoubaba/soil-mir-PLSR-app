import numpy as np
import pandas as pd

from legacy_modeling_reference import (
    build_cv_preprocessing_cache as legacy_build_cache,
    build_cv_response_cache as legacy_response_cache,
    cv_rank_path as legacy_rank_path,
)
from legacy_reference import grouped_splits
from soil_mir.modeling import (
    build_cv_preprocessing_cache,
    build_cv_response_cache,
    cv_rank_path,
)
from soil_mir.splits import grouped_splits as current_grouped_splits


def _dataset():
    rng = np.random.default_rng(20260923)
    axis = np.linspace(600, 4000, 128)
    sample_ids = np.array([f"S{i:02d}" for i in range(18)])
    sample_groups = np.array([str(i % 6) for i in range(18)])

    rows = []
    y = []
    keys = []
    labels = []
    for index, (sample, group) in enumerate(zip(sample_ids, sample_groups)):
        signal = (
            0.2
            + 0.00003 * axis
            + 0.04 * np.sin(axis / 140 + index / 9)
            + 0.015 * np.cos(axis / 80 + index / 5)
        )
        response = 2.0 + index * 0.35 + 0.3 * np.sin(index / 3)
        for replicate in range(3):
            rows.append(signal + rng.normal(0, 0.0015, len(axis)))
            y.append(response)
            keys.append(sample)
            labels.append(group)

    return np.asarray(rows), np.asarray(y), np.asarray(keys), np.asarray(labels)


def test_pls_rank_path_matches_legacy():
    X, y, keys, labels = _dataset()

    legacy_splits, legacy_info = grouped_splits(keys, labels, 4, 42, outer=False)
    current_splits, current_info = current_grouped_splits(keys, labels, 4, 42, outer=False)
    assert current_info == legacy_info
    for current, legacy in zip(current_splits, legacy_splits):
        np.testing.assert_array_equal(current[0], legacy[0])
        np.testing.assert_array_equal(current[1], legacy[1])

    cfg = {"sg_window": 11, "sg_polyorder": 2, "_segment_lengths": [64, 64]}
    prep = "1st Deriv + MSC"

    legacy_cache = legacy_build_cache(X, legacy_splits, prep, cfg)
    current_cache = build_cv_preprocessing_cache(X, current_splits, prep, cfg)
    legacy_responses = legacy_response_cache(y, legacy_splits, "sqrt")
    current_responses = build_cv_response_cache(y, current_splits, "sqrt")

    expected_predictions, expected_results = legacy_rank_path(
        legacy_cache, y, keys, 5, "sqrt", legacy_responses
    )
    actual_predictions, actual_results = cv_rank_path(
        current_cache, y, keys, 5, "sqrt", current_responses
    )

    np.testing.assert_allclose(
        actual_predictions,
        expected_predictions,
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )

    expected_frame = pd.DataFrame([metrics for metrics, _ in expected_results])
    actual_frame = pd.DataFrame([metrics for metrics, _ in actual_results])
    np.testing.assert_allclose(
        actual_frame.to_numpy(dtype=float),
        expected_frame.to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    assert [error for _, error in actual_results] == [error for _, error in expected_results]
