from pathlib import Path

import joblib
import pandas as pd

from soil_mir.reporting import (
    create_run_directory,
    export_final_refit,
    export_validation_comparison,
    export_validation_result,
    initialize_run_manifest,
    read_run_manifest,
    record_final_refit,
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
            "rmsecv_tolerance_pct": 5.0,
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
    assert "Tolerance Comparison" in workbook.sheet_names

    tolerance = pd.read_excel(
        artifacts["workbook"],
        sheet_name="Tolerance Comparison",
    )
    assert tolerance["Tolerance (%)"].tolist() == list(
        range(11)
    )
    current = tolerance[
        tolerance["Used for Current Run"]
    ]
    assert current["Tolerance (%)"].tolist() == [5]


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



def _final_refit():
    return {
        "property": "202_STC",
        "method": "monte_carlo",
        "refit_tolerance_pct": 4.0,
        "final_model": {
            "property_name": "202_STC",
            "units": "g C/kg soil",
            "training_sample_count": 12,
            "training_spectrum_count": 24,
        },
        "final_settings": {
            "Region": "W01",
            "Regions (cm-1)": "600-1200",
            "Spectral Points": 100,
            "Preprocessing": "1st Derivative",
            "Rank": 3,
            "RMSECV": 0.52,
        },
        "final_search": pd.DataFrame(
            [
                {
                    "Region": "W01",
                    "Regions (cm-1)": "600-1200",
                    "Spectral Points": 100,
                    "Preprocessing": "1st Derivative",
                    "Rank": 5,
                    "RMSECV": 0.50,
                    "Status": "Success",
                },
                {
                    "Region": "W01",
                    "Regions (cm-1)": "600-1200",
                    "Spectral Points": 100,
                    "Preprocessing": "1st Derivative",
                    "Rank": 3,
                    "RMSECV": 0.52,
                    "Status": "Success",
                },
            ]
        ),
        "config": {
            "method": "monte_carlo",
            "rmsecv_tolerance_pct": 4.0,
        },
    }


def test_export_and_record_final_refit_do_not_replace_validation_result(
    tmp_path: Path,
):
    run_dir = create_run_directory(
        tmp_path
    )
    initialize_run_manifest(
        run_dir,
        properties=["202_STC"],
        methods=["monte_carlo"],
        spectra_dir="/data/spectra",
        reference_excel="/data/reference.xlsx",
    )

    refit = _final_refit()
    artifacts = export_final_refit(
        refit,
        run_dir,
        source_validation_tolerance_pct=5.0,
    )
    record_final_refit(
        run_dir,
        refit,
        artifacts,
        source_validation_tolerance_pct=5.0,
    )

    assert Path(
        artifacts["model"]
    ).is_file()
    assert Path(
        artifacts["workbook"]
    ).is_file()
    workbook = pd.ExcelFile(
        artifacts["workbook"]
    )
    assert "Tolerance Comparison" in workbook.sheet_names
    assert "Final Model Selection" in workbook.sheet_names

    model = joblib.load(
        artifacts["model"]
    )
    assert model[
        "artifact_role"
    ] == "final_only_refit"
    assert model[
        "outer_validation_rerun"
    ] is False
    assert model[
        "source_validation_tolerance_pct"
    ] == 5.0
    assert model[
        "refit_tolerance_pct"
    ] == 4.0

    manifest = read_run_manifest(
        run_dir
    )
    assert manifest["results"] == []
    assert len(
        manifest["final_refits"]
    ) == 1
    saved = manifest[
        "final_refits"
    ][0]
    assert saved[
        "refit_tolerance_pct"
    ] == 4.0
    assert saved[
        "source_validation_tolerance_pct"
    ] == 5.0
    assert saved[
        "outer_validation_rerun"
    ] is False
