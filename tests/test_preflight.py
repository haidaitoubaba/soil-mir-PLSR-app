import numpy as np

from soil_mir.services.calibration import (
    CalibrationDataset,
    preflight_validation_methods,
)


def _dataset(groups=4):
    rng = np.random.default_rng(20260923)
    axis = np.linspace(600, 4000, 64)
    rows = []
    y = []
    samples = []
    labels = []

    for index in range(12):
        signal = (
            0.1
            + 0.00004 * axis
            + 0.02 * np.sin(axis / 170 + index / 4)
        )
        for _ in range(2):
            rows.append(
                signal
                + rng.normal(0, 0.001, len(axis))
            )
            y.append(1.0 + index * 0.25)
            samples.append(f"S{index:02d}")
            labels.append(str(index % groups))

    return CalibrationDataset(
        X=np.asarray(rows),
        y=np.asarray(y),
        sample_ids=np.asarray(samples),
        group_labels=np.asarray(labels),
        wavenumbers=axis,
        property_name="202_STC",
        units="g C/kg soil",
        transform="sqrt",
        exclude_co2=False,
        rows=len(rows),
        unique_samples=12,
    )


def _settings():
    return {
        "max_rank": 3,
        "region_search_n_windows": 2,
        "rmsecv_tolerance_pct": 5.0,
        "sg_window": 7,
        "sg_polyorder": 2,
        "random_seed": 42,
        "internal_cv_folds": 3,
        "outer_cv_folds": 3,
        "n_repeats": 2,
        "validation_fraction": 0.25,
        "ks_representation": "raw",
        "ks_pca_variance": 0.99,
        "wn_min": 600.0,
        "wn_max": 4000.0,
    }


def test_preflight_accepts_feasible_methods():
    frame = preflight_validation_methods(
        _dataset(groups=4),
        methods=["kfold", "logo", "kennard_stone"],
        **_settings(),
    )

    assert set(frame["Status"]) == {"Pass"}
    assert set(frame["Method"]) == {
        "kfold",
        "logo",
        "kennard_stone",
    }
    assert frame["Outer splits"].gt(0).all()


def test_preflight_surfaces_infeasible_logo():
    frame = preflight_validation_methods(
        _dataset(groups=2),
        methods=["logo"],
        **_settings(),
    )

    assert frame.iloc[0]["Status"] == "Fail"
    assert "at least three treatments" in frame.iloc[0]["Details"]
