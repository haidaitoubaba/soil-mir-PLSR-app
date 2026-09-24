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



def load_run_config(
    run_dir: str | Path,
) -> dict:
    path = Path(run_dir) / "Run_Config.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Run configuration not found: {path}"
        )
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Run configuration is not valid JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"Run configuration must be a JSON object: {path}"
        )
    return payload


def run_config_session_values(
    config: dict,
    *,
    run_dir: str | Path,
) -> dict:
    settings = config.get(
        "analysis_settings",
        {},
    )
    if not isinstance(settings, dict):
        raise ValueError(
            "Run configuration analysis_settings must be an object."
        )

    required = (
        "properties",
        "methods",
        "spectra_dir",
        "reference_excel",
    )
    missing = [
        key
        for key in required
        if not config.get(key)
    ]
    if missing:
        raise ValueError(
            "Run configuration is missing: "
            + ", ".join(missing)
        )

    run_path = Path(run_dir)
    output_dir = config.get(
        "output_dir",
        str(run_path.parent),
    )

    mapping = {
        "max_rank": "soil_mir_max_rank",
        "region_search_n_windows": "soil_mir_region_windows",
        "rmsecv_tolerance_pct": "soil_mir_tolerance",
        "sg_window": "soil_mir_sg_window",
        "sg_polyorder": "soil_mir_sg_polyorder",
        "random_seed": "soil_mir_random_seed",
        "internal_cv_folds": "soil_mir_internal_cv_folds",
        "outer_cv_folds": "soil_mir_outer_cv_folds",
        "n_repeats": "soil_mir_n_repeats",
        "validation_fraction": "soil_mir_validation_fraction",
        "ks_representation": "soil_mir_ks_representation",
        "ks_pca_variance": "soil_mir_ks_pca_variance",
        "outer_n_jobs": "soil_mir_outer_n_jobs",
        "inner_thread_limit": "soil_mir_inner_thread_limit",
    }
    values = {
        "soil_mir_spectra_dir": str(
            config["spectra_dir"]
        ),
        "soil_mir_reference_excel": str(
            config["reference_excel"]
        ),
        "soil_mir_output_dir": str(
            output_dir
        ),
        "soil_mir_selected_properties": list(
            config["properties"]
        ),
        "soil_mir_validation_methods": list(
            config["methods"]
        ),
        "soil_mir_reference_ranges": dict(
            config.get(
                "reference_ranges",
                {},
            )
        ),
        "soil_mir_exclude_co2": bool(
            config.get(
                "fallback_exclude_co2",
                False,
            )
        ),
    }
    for source, target in mapping.items():
        if source in settings:
            values[target] = settings[source]

    if (
        "wn_min" in settings
        and "wn_max" in settings
    ):
        values["soil_mir_wn_range"] = (
            settings["wn_min"],
            settings["wn_max"],
        )

    # Runs created before parallelism was added were sequential.
    values.setdefault(
        "soil_mir_outer_n_jobs",
        1,
    )
    values.setdefault(
        "soil_mir_inner_thread_limit",
        1,
    )
    return values


def completed_run_keys(
    manifest: dict,
) -> set[str]:
    return {
        (
            f"{record.get('property', '')}::"
            f"{record.get('method', '')}"
        )
        for record in manifest.get(
            "results",
            [],
        )
        if record.get("property")
        and record.get("method")
    }


def requested_run_keys(
    manifest: dict,
) -> set[str]:
    return {
        f"{property_name}::{method}"
        for property_name in manifest.get(
            "properties",
            [],
        )
        for method in manifest.get(
            "methods",
            [],
        )
    }


def pending_run_keys(
    manifest: dict,
) -> set[str]:
    return (
        requested_run_keys(manifest)
        - completed_run_keys(manifest)
    )
