from pathlib import Path

import pandas as pd
import pytest

from soil_mir.services.history import (
    completed_run_keys,
    list_saved_models,
    load_run_config,
    load_saved_result,
    load_saved_run,
    pending_run_keys,
    run_config_session_values,
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



def test_resume_helpers_restore_run_configuration(
    tmp_path,
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = {
        "properties": ["202_STC", "202_STN"],
        "methods": ["kfold"],
        "spectra_dir": "/data/spectra",
        "reference_excel": "/data/reference.xlsx",
        "output_dir": "/data/results",
        "reference_ranges": {
            "202_STC": {
                "min": 0.1,
                "max": None,
            }
        },
        "fallback_exclude_co2": True,
        "analysis_settings": {
            "max_rank": 15,
            "region_search_n_windows": 7,
            "rmsecv_tolerance_pct": 5.0,
            "sg_window": 11,
            "sg_polyorder": 2,
            "random_seed": 42,
            "internal_cv_folds": 10,
            "outer_cv_folds": 5,
            "n_repeats": 30,
            "validation_fraction": 0.2,
            "ks_representation": "raw",
            "ks_pca_variance": 0.99,
            "use_group_stratification": False,
            "wn_min": 600,
            "wn_max": 4000,
            "outer_n_jobs": 4,
            "inner_thread_limit": 1,
        },
    }
    (run_dir / "Run_Config.json").write_text(
        __import__("json").dumps(config),
        encoding="utf-8",
    )

    loaded = load_run_config(run_dir)
    values = run_config_session_values(
        loaded,
        run_dir=run_dir,
    )

    assert values[
        "soil_mir_selected_properties"
    ] == ["202_STC", "202_STN"]
    assert values[
        "soil_mir_validation_methods"
    ] == ["kfold"]
    assert values[
        "soil_mir_wn_range"
    ] == (600, 4000)
    assert values[
        "soil_mir_outer_n_jobs"
    ] == 4
    assert values[
        "soil_mir_inner_thread_limit"
    ] == 1
    assert values[
        "soil_mir_use_group_stratification"
    ] is False
    assert values[
        "soil_mir_exclude_co2"
    ] is True


def test_pending_run_keys_skip_completed_combinations():
    manifest = {
        "properties": [
            "202_STC",
            "202_STN",
        ],
        "methods": [
            "kfold",
            "logo",
        ],
        "results": [
            {
                "property": "202_STC",
                "method": "kfold",
            },
            {
                "property": "202_STN",
                "method": "logo",
            },
        ],
    }

    assert completed_run_keys(
        manifest
    ) == {
        "202_STC::kfold",
        "202_STN::logo",
    }
    assert pending_run_keys(
        manifest
    ) == {
        "202_STC::logo",
        "202_STN::kfold",
    }



def test_saved_model_list_uses_existing_history_models(
    tmp_path,
    monkeypatch,
):
    newest_model = tmp_path / "new.joblib"
    older_model = tmp_path / "old.joblib"
    newest_model.write_bytes(b"model")
    older_model.write_bytes(b"model")

    monkeypatch.setattr(
        "soil_mir.services.history.list_run_history",
        lambda _root: [
            {
                "run_id": "newest",
                "created_at": "2026-09-24T01:00:00+00:00",
                "results": [
                    {
                        "property": "202_STC",
                        "method": "kfold",
                        "final_model": {
                            "rank": 7,
                        },
                        "artifacts": {
                            "model": str(
                                newest_model
                            ),
                        },
                    }
                ],
            },
            {
                "run_id": "older",
                "created_at": "2026-09-23T01:00:00+00:00",
                "results": [
                    {
                        "property": "202_STN",
                        "method": "logo",
                        "final_model": {
                            "rank": 5,
                        },
                        "artifacts": {
                            "model": str(
                                older_model
                            ),
                        },
                    },
                    {
                        "property": "missing",
                        "method": "kfold",
                        "artifacts": {
                            "model": str(
                                tmp_path
                                / "missing.joblib"
                            ),
                        },
                    },
                ],
            },
        ],
    )

    models = list_saved_models(
        tmp_path
    )

    assert [
        item["path"]
        for item in models
    ] == [
        str(newest_model),
        str(older_model),
    ]
    assert (
        models[0]["label"]
        == "newest | 202_STC | K-fold Cross-Validation | rank 7"
    )



def test_saved_model_list_includes_final_only_refits(
    tmp_path,
    monkeypatch,
):
    validated_model = (
        tmp_path / "validated.joblib"
    )
    refit_model = (
        tmp_path / "refit.joblib"
    )
    validated_model.write_bytes(
        b"model"
    )
    refit_model.write_bytes(
        b"model"
    )

    monkeypatch.setattr(
        "soil_mir.services.history.list_run_history",
        lambda _root: [
            {
                "run_id": "run-1",
                "created_at": "2026-09-24T10:00:00+00:00",
                "results": [
                    {
                        "property": "202_STC",
                        "method": "monte_carlo",
                        "final_model": {
                            "rank": 5,
                        },
                        "artifacts": {
                            "model": str(
                                validated_model
                            ),
                        },
                    }
                ],
                "final_refits": [
                    {
                        "property": "202_STC",
                        "method": "monte_carlo",
                        "created_at": "2026-09-24T11:00:00+00:00",
                        "refit_tolerance_pct": 4.0,
                        "source_validation_tolerance_pct": 5.0,
                        "outer_validation_rerun": False,
                        "final_model": {
                            "rank": 3,
                        },
                        "artifacts": {
                            "model": str(
                                refit_model
                            ),
                        },
                    }
                ],
            }
        ],
    )

    models = list_saved_models(
        tmp_path
    )

    assert len(models) == 2
    assert models[0][
        "model_role"
    ] == "final_only_refit"
    assert models[0][
        "refit_tolerance_pct"
    ] == 4.0
    assert "final-only refit 4%" in models[0]["label"]
    assert models[1][
        "model_role"
    ] == "validated_final_model"



def test_old_run_config_defaults_group_stratification_on(
    tmp_path,
):
    run_dir = tmp_path / "old_run"
    run_dir.mkdir()
    config = {
        "properties": ["202_STC"],
        "methods": ["kfold"],
        "spectra_dir": "/data/spectra",
        "reference_excel": "/data/reference.xlsx",
        "analysis_settings": {
            "max_rank": 15,
            "region_search_n_windows": 7,
            "rmsecv_tolerance_pct": 5.0,
            "sg_window": 11,
            "sg_polyorder": 2,
            "random_seed": 42,
            "internal_cv_folds": 10,
            "outer_cv_folds": 5,
            "n_repeats": 30,
            "validation_fraction": 0.2,
            "ks_representation": "raw",
            "ks_pca_variance": 0.99,
            "wn_min": 600,
            "wn_max": 4000,
        },
    }

    values = run_config_session_values(
        config,
        run_dir=run_dir,
    )

    assert values[
        "soil_mir_use_group_stratification"
    ] is True
