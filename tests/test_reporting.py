from pathlib import Path

import joblib
import pandas as pd

from soil_mir.reporting import (
    create_run_directory,
    export_validation_comparison,
    export_validation_result,
    safe_name,
)


def test_safe_name():
    assert safe_name(
        "202 STC / K-fold"
    ) == "202_STC_K-fold"


def _result():
    return {
        "property": "202_STC",
        "method": "kfold",
        "summary": pd.DataFrame(
            {
                "Metric": ["R2", "RMSE", "RPIQ", "Bias"],
                "Value": [0.8, 0.5, 2.1, -0.02],
            }
        ),
        "folds": pd.DataFrame(
            {
                "Outer Split": [1, 2],
                "Validation RMSE": [0.45, 0.55],
            }
        ),
        "predictions": pd.DataFrame(
            {
                "Sample Key": ["A", "B"],
                "Measured": [1.0, 2.0],
                "Predicted": [1.1, 1.8],
                "Residual": [-0.1, 0.2],
            }
        ),
        "assignments": pd.DataFrame(
            {
                "Sample Key": ["A", "B"],
                "Set": ["Validation", "Validation"],
            }
        ),
        "optimization_results": pd.DataFrame(
            {
                "Region": ["Full range"],
                "RMSECV": [0.5],
            }
        ),
        "final_search": pd.DataFrame(
            {
                "Selected": [True],
                "Region": ["Full range"],
                "Preprocessing": ["1st Derivative"],
                "Rank": [2],
                "RMSECV": [0.5],
                "Status": ["Success"],
            }
        ),
        "final_settings": {
            "Region": "Full range",
            "Preprocessing": "1st Derivative",
            "Rank": 2,
        },
        "final_model": {
            "property_name": "202_STC",
            "units": "g C/kg soil",
            "training_sample_count": 12,
            "training_spectrum_count": 24,
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
        "unique_validation_samples": 2,
        "elapsed_seconds": 3.5,
    }


def test_export_validation_result(tmp_path: Path):
    run_dir = create_run_directory(tmp_path)
    result = _result()

    artifacts = export_validation_result(
        result,
        run_dir,
    )

    for key in (
        "model",
        "workbook",
        "plots_pdf",
        "metadata",
        "config",
        "split_info",
    ):
        assert Path(artifacts[key]).is_file()

    assert Path(artifacts["plots_pdf"]).stat().st_size > 0

    model = joblib.load(artifacts["model"])
    assert model["software_name"] == "soil-mir-app"
    assert model["software_version"]
    assert model["git_commit"]
    assert model["created_at"]

    workbook = pd.ExcelFile(artifacts["workbook"])
    assert "Summary" in workbook.sheet_names
    assert "Validation Predictions" in workbook.sheet_names
    assert "Final Model Selection" in workbook.sheet_names


def test_export_validation_comparison(tmp_path: Path):
    run_dir = create_run_directory(tmp_path)
    result = _result()

    path = Path(
        export_validation_comparison(
            {"202_STC::kfold": result},
            run_dir,
        )
    )

    assert path.name == "Validation_Comparison.xlsx"
    assert path.is_file()
    frame = pd.read_excel(path)
    assert frame.loc[0, "Property"] == "202_STC"
    assert frame.loc[0, "Method"] == "kfold"
    assert frame.loc[0, "R2"] == 0.8
