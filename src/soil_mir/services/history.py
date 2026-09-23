from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REQUIRED_SHEETS = {
    "Summary",
    "Outer Results",
    "Validation Predictions",
    "Final Calibration Search",
    "Final Model Selection",
}


def _read_optional_json(path_value: str | None) -> dict:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_saved_result(record: dict) -> dict:
    artifacts = record.get("artifacts", {})
    workbook_path = Path(artifacts.get("workbook", ""))
    if not workbook_path.is_file():
        raise FileNotFoundError(
            f"Saved results workbook not found: {workbook_path}"
        )

    with pd.ExcelFile(workbook_path) as workbook:
        missing = REQUIRED_SHEETS - set(workbook.sheet_names)
        if missing:
            raise ValueError(
                "Saved results workbook is missing sheets: "
                f"{sorted(missing)}"
            )
        summary = workbook.parse("Summary")
        folds = workbook.parse("Outer Results")
        predictions = workbook.parse("Validation Predictions")
        final_search = workbook.parse("Final Calibration Search")
        final_selection = workbook.parse("Final Model Selection")
        assignments = (
            workbook.parse("Split Assignments")
            if "Split Assignments" in workbook.sheet_names
            else pd.DataFrame()
        )
        optimization = (
            workbook.parse("Optimization Results")
            if "Optimization Results" in workbook.sheet_names
            else pd.DataFrame()
        )

    if final_selection.empty:
        raise ValueError(
            "Saved results workbook has no final model selection row."
        )
    if not {"Metric", "Value"} <= set(summary.columns):
        raise ValueError(
            "Saved results summary must contain Metric and Value columns."
        )
    if not {"Measured", "Predicted"} <= set(predictions.columns):
        raise ValueError(
            "Saved validation predictions must contain Measured and Predicted columns."
        )
    if "Residual" not in predictions.columns:
        predictions["Residual"] = (
            predictions["Measured"] - predictions["Predicted"]
        )

    unique_samples = record.get("validation_samples")
    if unique_samples is None and "Sample Key" in predictions.columns:
        unique_samples = int(
            predictions["Sample Key"].nunique()
        )

    return {
        "property": record.get("property", ""),
        "method": record.get("method", ""),
        "summary": summary,
        "folds": folds,
        "predictions": predictions,
        "assignments": assignments,
        "optimization_results": optimization,
        "final_search": final_search,
        "final_settings": final_selection.iloc[0].to_dict(),
        "final_model": {},
        "split_info": _read_optional_json(
            artifacts.get("split_info")
        ),
        "config": _read_optional_json(
            artifacts.get("config")
        ),
        "unique_validation_samples": int(
            unique_samples or 0
        ),
        "elapsed_seconds": float(
            record.get("elapsed_seconds", 0.0)
        ),
        "artifacts": dict(artifacts),
        "loaded_from_history": True,
    }


def load_saved_run(manifest: dict) -> dict[str, dict]:
    loaded = {}
    for record in manifest.get("results", []):
        result = load_saved_result(record)
        key = (
            f"{result['property']}::"
            f"{result['method']}"
        )
        loaded[key] = result

    if not loaded:
        raise ValueError(
            "This run has no completed result artifacts to reopen."
        )
    return loaded
