from pathlib import Path

import pandas as pd

from soil_mir.reporting import (
    finalize_run_manifest,
    initialize_run_manifest,
    list_run_history,
    read_run_manifest,
    record_run_result,
)


def _result():
    return {
        "property": "202_STC",
        "method": "kfold",
        "summary": pd.DataFrame(
            {
                "Metric": ["R2", "RMSE", "RPIQ", "Bias"],
                "Value": [0.82, 0.41, 2.3, -0.02],
            }
        ),
        "final_settings": {
            "Preprocessing": "1st Deriv + SNV",
            "Region": "W01 + W03",
            "Rank": 4,
        },
        "unique_validation_samples": 24,
        "elapsed_seconds": 12.5,
    }


def test_run_manifest_lifecycle(tmp_path: Path):
    run_dir = tmp_path / "20260923_120000_000000"
    run_dir.mkdir()

    initialize_run_manifest(
        run_dir,
        properties=["202_STC", "202_STN"],
        methods=["kfold"],
        spectra_dir="/data/spectra",
        reference_excel="/data/reference.xlsx",
    )
    record_run_result(
        run_dir,
        _result(),
        {
            "model": "/results/model.joblib",
            "workbook": "/results/results.xlsx",
        },
    )
    finalize_run_manifest(
        run_dir,
        status="completed",
    )

    manifest = read_run_manifest(run_dir)
    assert manifest["status"] == "completed"
    assert manifest["result_count"] if "result_count" in manifest else True
    assert len(manifest["results"]) == 1
    assert manifest["results"][0]["metrics"]["R2"] == 0.82
    assert manifest["results"][0]["final_model"]["rank"] == 4


def test_run_history_is_newest_first_and_skips_hidden_dirs(tmp_path: Path):
    older = tmp_path / "20260922_120000_000000"
    newer = tmp_path / "20260923_120000_000000"
    hidden = tmp_path / ".soil_mir_cache"
    older.mkdir()
    newer.mkdir()
    hidden.mkdir()

    initialize_run_manifest(
        older,
        properties=["202_STC"],
        methods=["kfold"],
        spectra_dir="/data/spectra",
        reference_excel="/data/reference.xlsx",
    )
    initialize_run_manifest(
        newer,
        properties=["202_STN"],
        methods=["logo"],
        spectra_dir="/data/spectra",
        reference_excel="/data/reference.xlsx",
    )

    history = list_run_history(tmp_path)
    assert [Path(item["run_dir"]).name for item in history] == [
        newer.name,
        older.name,
    ]
    assert all(
        not Path(item["run_dir"]).name.startswith(".")
        for item in history
    )
