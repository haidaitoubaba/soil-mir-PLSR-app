from pathlib import Path

import pandas as pd

from soil_mir.reporting import (
    create_run_directory,
    export_validation_result,
    safe_name,
)


def test_safe_name():
    assert safe_name(
        "202 STC / K-fold"
    ) == "202_STC_K-fold"


def test_export_validation_result(tmp_path: Path):
    run_dir = create_run_directory(tmp_path)
    result = {
        "property": "202_STC",
        "method": "kfold",
        "summary": pd.DataFrame(
            {
                "Metric": ["R2", "RMSE"],
                "Value": [0.8, 0.5],
            }
        ),
        "folds": pd.DataFrame(
            {"Outer Split": [1]}
        ),
        "predictions": pd.DataFrame(
            {
                "Sample Key": ["A"],
                "Measured": [1.0],
                "Predicted": [1.1],
            }
        ),
        "assignments": pd.DataFrame(
            {
                "Sample Key": ["A"],
                "Set": ["Validation"],
            }
        ),
        "optimization_results": pd.DataFrame(
            {
                "Region": ["Full range"],
                "RMSECV": [0.5],
            }
        ),
        "final_search": pd.DataFrame(
            {"Selected": [True]}
        ),
        "final_settings": {
            "Region": "Full range",
            "Preprocessing": "1st Derivative",
            "Rank": 2,
        },
        "final_model": {
            "property_name": "202_STC"
        },
        "split_info": {
            "method": "kfold"
        },
        "config": {
            "method": "kfold",
            "_region_windows": [
                {
                    "Window": "W01",
                    "Actual Lower": 600.0,
                    "Actual Upper": 4000.0,
                }
            ],
        },
    }

    artifacts = export_validation_result(
        result,
        run_dir,
    )

    assert Path(artifacts["model"]).is_file()
    assert Path(artifacts["workbook"]).is_file()
    assert Path(artifacts["config"]).is_file()
    assert Path(artifacts["split_info"]).is_file()

    workbook = pd.ExcelFile(artifacts["workbook"])
    assert "Summary" in workbook.sheet_names
    assert (
        "Validation Predictions"
        in workbook.sheet_names
    )
    assert (
        "Final Model Selection"
        in workbook.sheet_names
    )
