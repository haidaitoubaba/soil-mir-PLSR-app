import pandas as pd

from soil_mir.regions import (
    build_tolerance_comparison,
)


def _search():
    return pd.DataFrame(
        [
            {
                "Region": "W01",
                "Regions (cm-1)": "600-1200",
                "Spectral Points": 100,
                "Preprocessing": "1st Derivative",
                "Rank": 7,
                "RMSECV": 1.000,
                "Status": "Success",
            },
            {
                "Region": "W02",
                "Regions (cm-1)": "1200-1800",
                "Spectral Points": 90,
                "Preprocessing": "1st Deriv + SNV",
                "Rank": 4,
                "RMSECV": 1.039,
                "Status": "Success",
            },
            {
                "Region": "W03",
                "Regions (cm-1)": "1800-2400",
                "Spectral Points": 80,
                "Preprocessing": "1st Deriv + MSC",
                "Rank": 2,
                "RMSECV": 1.081,
                "Status": "Success",
            },
        ]
    )


def test_tolerance_comparison_covers_zero_through_ten_percent():
    comparison = build_tolerance_comparison(
        _search(),
        configured_tolerance=5.0,
    )

    assert comparison[
        "Tolerance (%)"
    ].tolist() == [
        float(value)
        for value in range(11)
    ]
    assert comparison[
        "Used for Current Run"
    ].tolist().count(True) == 1
    assert comparison.loc[
        comparison["Used for Current Run"],
        "Tolerance (%)",
    ].tolist() == [5.0]


def test_tolerance_comparison_reselects_simpler_models():
    comparison = build_tolerance_comparison(
        _search(),
        configured_tolerance=5.0,
    ).set_index("Tolerance (%)")

    assert int(
        comparison.loc[0.0, "Rank"]
    ) == 7
    assert int(
        comparison.loc[3.0, "Rank"]
    ) == 7
    assert int(
        comparison.loc[4.0, "Rank"]
    ) == 4
    assert int(
        comparison.loc[8.0, "Rank"]
    ) == 4
    assert int(
        comparison.loc[9.0, "Rank"]
    ) == 2


def test_tolerance_comparison_is_final_calibration_sensitivity_only():
    frame = _search()
    frame["Phase"] = "Final calibration search"
    initial = frame.copy()
    initial["Phase"] = "Initial calibration search"
    initial["RMSECV"] = 0.1

    comparison = build_tolerance_comparison(
        pd.concat(
            [initial, frame],
            ignore_index=True,
        ),
        configured_tolerance=5.0,
    )

    assert comparison[
        "Minimum RMSECV"
    ].eq(1.0).all()
    assert comparison[
        "Interpretation"
    ].str.contains(
        "not held-out validation"
    ).all()
