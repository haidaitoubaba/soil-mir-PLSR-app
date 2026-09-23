from pathlib import Path

import pandas as pd
import pytest

from soil_mir.services.history import (
    load_saved_result,
    load_saved_run,
)


def _write_workbook(path: Path):
    with pd.ExcelWriter(
        path,
        engine="openpyxl",
    ) as writer:
        pd.DataFrame(
            {
                "Metric": [
                    "R2",
                    "RMSE",
                    "RPIQ",
                    "Bias",
                ],
                "Value": [
                    0.8,
                    0.5,
                    2.0,
                    -0.1,
                ],
            }
        ).to_excel(
            writer,
            sheet_name="Summary",
            index=False,
        )
        pd.DataFrame(
            {
                "Outer Split": [1, 2],
                "Validation RMSE": [0.4, 0.6],
            }
        ).to_excel(
            writer,
            sheet_name="Outer Results",
            index=False,
        )
        pd.DataFrame(
            {
                "Sample Key": ["A", "B"],
                "Measured": [1.0, 2.0],
                "Predicted": [1.1, 1.8],
            }
        ).to_excel(
            writer,
            sheet_name="Validation Predictions",
            index=False,
        )
        pd.DataFrame(
            {
                "Region": ["Full range"],
                "Preprocessing": ["1st Derivative"],
                "Rank": [2],
                "RMSECV": [0.5],
                "Status": ["Success"],
                "Selected": [True],
            }
        ).to_excel(
            writer,
            sheet_name="Final Calibration Search",
            index=False,
        )
        pd.DataFrame(
            [
                {
                    "Region": "Full range",
                    "Preprocessing": "1st Derivative",
                    "Rank": 2,
                }
            ]
        ).to_excel(
            writer,
            sheet_name="Final Model Selection",
            index=False,
        )


def test_saved_result_reconstructs_results_view(tmp_path):
    workbook = tmp_path / "results.xlsx"
    _write_workbook(workbook)

    result = load_saved_result(
        {
            "property": "202_STC",
            "method": "kfold",
            "validation_samples": 2,
            "elapsed_seconds": 3.5,
            "artifacts": {
                "workbook": str(workbook),
            },
        }
    )

    assert result["property"] == "202_STC"
    assert result["method"] == "kfold"
    assert result["loaded_from_history"] is True
    assert result["unique_validation_samples"] == 2
    assert "Residual" in result["predictions"].columns
    assert result["final_settings"]["Rank"] == 2


def test_saved_run_loads_multiple_results(tmp_path):
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    _write_workbook(first)
    _write_workbook(second)

    loaded = load_saved_run(
        {
            "results": [
                {
                    "property": "202_STC",
                    "method": "kfold",
                    "artifacts": {
                        "workbook": str(first),
                    },
                },
                {
                    "property": "202_STN",
                    "method": "logo",
                    "artifacts": {
                        "workbook": str(second),
                    },
                },
            ]
        }
    )

    assert set(loaded) == {
        "202_STC::kfold",
        "202_STN::logo",
    }


def test_saved_result_rejects_missing_workbook(tmp_path):
    with pytest.raises(
        FileNotFoundError,
        match="workbook not found",
    ):
        load_saved_result(
            {
                "property": "202_STC",
                "method": "kfold",
                "artifacts": {
                    "workbook": str(
                        tmp_path / "missing.xlsx"
                    )
                },
            }
        )
