import numpy as np

from soil_mir.services.calibration import (
    CalibrationDataset,
    preflight_validation_methods,
)


def _dataset(
    groups=4,
    include_groups=True,
    partial_groups=False,
):
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
            if include_groups:
                label = str(index % groups)
                if partial_groups and index == 0:
                    label = ""
            else:
                label = ""
            labels.append(label)

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
        group_column_present=include_groups,
        group_labels_complete=(
            include_groups
            and not partial_groups
        ),
        group_count=(
            groups
            if include_groups
            else 0
        ),
        missing_group_samples=(
            1
            if partial_groups
            else (
                0
                if include_groups
                else 12
            )
        ),
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
        "use_group_stratification": True,
        "wn_min": 600.0,
        "wn_max": 4000.0,
    }


def test_preflight_accepts_feasible_methods():
    settings = _settings()
    settings["validation_fraction"] = 0.50
    frame = preflight_validation_methods(
        _dataset(groups=4),
        methods=[
            "kfold",
            "monte_carlo",
            "loso",
            "logo",
            "kennard_stone",
        ],
        **settings,
    )

    assert set(frame["Status"]) == {"Pass"}
    assert set(frame["Method"]) == {
        "kfold",
        "monte_carlo",
        "loso",
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


def test_preflight_allows_non_group_methods_without_group():
    settings = _settings()
    settings["validation_fraction"] = 0.50
    frame = preflight_validation_methods(
        _dataset(
            include_groups=False,
        ),
        methods=[
            "kfold",
            "monte_carlo",
            "loso",
            "kennard_stone",
        ],
        **settings,
    )

    assert set(frame["Status"]) == {"Pass"}
    assert set(frame["Groups"]) == {0}
    assert set(frame["Group data"]) == {
        "Not provided"
    }


def test_preflight_logo_requires_complete_group():
    frame = preflight_validation_methods(
        _dataset(
            include_groups=False,
        ),
        methods=["logo"],
        **_settings(),
    )

    assert frame.iloc[0]["Status"] == "Fail"
    assert (
        "requires a Group column"
        in frame.iloc[0]["Details"]
    )


def test_preflight_partial_group_falls_back_for_kfold():
    frame = preflight_validation_methods(
        _dataset(
            partial_groups=True,
        ),
        methods=["kfold"],
        **_settings(),
    )

    assert frame.iloc[0]["Status"] == "Pass"
    assert frame.iloc[0]["Group data"] == "Partial"
    assert (
        frame.iloc[0]["Details"]
        == "Shuffled sample KFold"
    )



def test_preflight_reports_optional_group_toggle_and_actual_use():
    settings = _settings()
    settings["validation_fraction"] = 0.50
    settings["use_group_stratification"] = False

    frame = preflight_validation_methods(
        _dataset(groups=4),
        methods=[
            "kfold",
            "monte_carlo",
            "logo",
        ],
        **settings,
    )

    kfold = frame[
        frame["Method"] == "kfold"
    ].iloc[0]
    monte_carlo = frame[
        frame["Method"] == "monte_carlo"
    ].iloc[0]
    logo = frame[
        frame["Method"] == "logo"
    ].iloc[0]

    assert (
        kfold["Group stratification requested"]
        == "No"
    )
    assert (
        kfold["Outer Group stratification used"]
        == "No"
    )
    assert (
        kfold["Inner Group stratification used"]
        == "No"
    )
    assert (
        kfold["Details"]
        == "Shuffled sample KFold"
    )

    assert (
        monte_carlo[
            "Group stratification requested"
        ]
        == "No"
    )
    assert (
        monte_carlo[
            "Outer Group stratification used"
        ]
        == "No"
    )
    assert (
        monte_carlo[
            "Inner Group stratification used"
        ]
        == "No"
    )
    assert (
        monte_carlo["Details"]
        == "ShuffleSplit(sample)"
    )

    assert (
        logo["Group stratification requested"]
        == "Required"
    )
    assert (
        logo["Outer Group stratification used"]
        == "Yes"
    )
    assert (
        logo["Inner Group stratification used"]
        == "Yes"
    )
