from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from soil_mir.plotting import (
    measured_vs_predicted_figure,
)

import joblib
import numpy as np
import pandas as pd


def safe_name(value: str) -> str:
    cleaned = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(value).strip(),
    ).strip("_")
    return cleaned or "result"


def create_run_directory(output_base: str | Path) -> Path:
    root = Path(output_base).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_json(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def public_config(cfg: dict) -> dict:
    return {
        key: value
        for key, value in cfg.items()
        if not key.startswith("_")
    }


def reproducibility_metadata() -> dict:
    try:
        software_version = version("soil-mir-app")
    except PackageNotFoundError:
        software_version = "unknown"

    git_commit = (
        os.environ.get("SOIL_MIR_GIT_COMMIT")
        or os.environ.get("CI_COMMIT_SHA")
        or ""
    )
    if not git_commit:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[2],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            git_commit = "unknown"
        else:
            git_commit = completed.stdout.strip() or "unknown"

    return {
        "software_name": "soil-mir-app",
        "software_version": software_version,
        "git_commit": git_commit,
        "created_at": _utc_now(),
    }


def _export_validation_plots(
    result: dict,
    pdf_path: Path,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    predictions = result["predictions"]
    measured = predictions["Measured"].to_numpy(dtype=float)
    predicted = predictions["Predicted"].to_numpy(dtype=float)
    residual = measured - predicted
    title = f"{result['property']} — {result['method']}"

    with PdfPages(pdf_path) as pdf:
        fig = measured_vs_predicted_figure(
            measured,
            predicted,
            title=(
                f"{title} — measured vs predicted"
            ),
            predicted_label=(
                "Validation predicted"
            ),
        )
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 6))
        ax.scatter(predicted, residual, alpha=0.7)
        ax.axhline(0, linestyle="--")
        ax.set_xlabel("Validation predicted")
        ax.set_ylabel("Residual (measured - predicted)")
        ax.set_title(f"{title} — residuals")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 6))
        ax.hist(
            residual,
            bins=min(12, max(len(residual), 1)),
        )
        ax.set_xlabel("Residual (measured - predicted)")
        ax.set_ylabel("Validation predictions")
        ax.set_title(f"{title} — residual distribution")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)


def export_validation_result(
    result: dict,
    run_dir: str | Path,
) -> dict[str, str]:
    run_dir = Path(run_dir)
    target = (
        run_dir
        / safe_name(result["property"])
        / safe_name(result["method"])
    )
    target.mkdir(parents=True, exist_ok=True)

    stem = (
        f"PLSR_{safe_name(result['method'])}_"
        f"{safe_name(result['property'])}"
    )
    model_path = target / f"{stem}_Final_Model.joblib"
    workbook_path = target / f"{stem}_Results.xlsx"
    plots_path = target / f"{stem}_Plots.pdf"
    metadata_path = target / "Model_Metadata.json"
    config_path = target / "Resolved_Config.json"
    split_path = target / "Split_Info.json"

    metadata = reproducibility_metadata()
    result["final_model"].update(metadata)
    joblib.dump(
        result["final_model"],
        model_path,
        compress=3,
    )

    final_settings = result["final_settings"]
    write_json(
        metadata_path,
        {
            **metadata,
            "property": result["property"],
            "units": result["final_model"].get("units", ""),
            "validation_method": result["method"],
            "training_samples": result["final_model"].get(
                "training_sample_count"
            ),
            "training_spectra": result["final_model"].get(
                "training_spectrum_count"
            ),
            "preprocessing": final_settings["Preprocessing"],
            "region": final_settings["Region"],
            "rank": int(final_settings["Rank"]),
        },
    )
    write_json(
        config_path,
        public_config(result["config"]),
    )
    write_json(
        split_path,
        result["split_info"],
    )

    region_windows = pd.DataFrame(
        result["config"].get("_region_windows", [])
    )
    final_selection = pd.DataFrame(
        [final_settings]
    )
    settings = pd.DataFrame(
        [
            {"Setting": key, "Value": str(value)}
            for key, value in public_config(
                result["config"]
            ).items()
        ]
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        result["summary"].to_excel(
            writer,
            sheet_name="Summary",
            index=False,
        )
        result["folds"].to_excel(
            writer,
            sheet_name="Outer Results",
            index=False,
        )
        result["predictions"].to_excel(
            writer,
            sheet_name="Validation Predictions",
            index=False,
        )
        result["assignments"].to_excel(
            writer,
            sheet_name="Split Assignments",
            index=False,
        )
        result["optimization_results"].to_excel(
            writer,
            sheet_name="Optimization Results",
            index=False,
        )
        result["final_search"].to_excel(
            writer,
            sheet_name="Final Calibration Search",
            index=False,
        )
        final_selection.to_excel(
            writer,
            sheet_name="Final Model Selection",
            index=False,
        )
        region_windows.to_excel(
            writer,
            sheet_name="Region Windows",
            index=False,
        )
        settings.to_excel(
            writer,
            sheet_name="Resolved Settings",
            index=False,
        )

    _export_validation_plots(
        result,
        plots_path,
    )

    return {
        "directory": str(target),
        "model": str(model_path),
        "workbook": str(workbook_path),
        "plots_pdf": str(plots_path),
        "metadata": str(metadata_path),
        "config": str(config_path),
        "split_info": str(split_path),
    }


def export_validation_comparison(
    results: dict[str, dict],
    run_dir: str | Path,
) -> str:
    rows = []
    for result in results.values():
        summary = result["summary"].set_index("Metric")
        settings = result["final_settings"]
        rows.append(
            {
                "Property": result["property"],
                "Method": result["method"],
                "R2": float(summary.loc["R2", "Value"]),
                "RMSE": float(summary.loc["RMSE", "Value"]),
                "RPIQ": float(summary.loc["RPIQ", "Value"]),
                "Bias": float(summary.loc["Bias", "Value"]),
                "Final Preprocessing": settings["Preprocessing"],
                "Final Region": settings["Region"],
                "Final Rank": int(settings["Rank"]),
                "Validation Samples": int(
                    result["unique_validation_samples"]
                ),
                "Elapsed Seconds": float(
                    result["elapsed_seconds"]
                ),
            }
        )

    path = Path(run_dir) / "Validation_Comparison.xlsx"
    pd.DataFrame(rows).to_excel(
        path,
        index=False,
    )
    return str(path)


RUN_MANIFEST_NAME = "Run_Manifest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_run_manifest(
    run_dir: str | Path,
    *,
    properties: list[str],
    methods: list[str],
    spectra_dir: str,
    reference_excel: str,
) -> dict:
    run_dir = Path(run_dir)
    manifest = {
        "version": 1,
        "run_id": run_dir.name,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "running",
        "spectra_dir": str(spectra_dir),
        "reference_excel": str(reference_excel),
        "properties": list(properties),
        "methods": list(methods),
        "results": [],
        "failures": [],
        "error": "",
    }
    write_json(run_dir / RUN_MANIFEST_NAME, manifest)
    return manifest


def read_run_manifest(run_dir: str | Path) -> dict:
    path = Path(run_dir) / RUN_MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError(f"Unsupported run manifest: {path}")
    return payload


def record_run_result(
    run_dir: str | Path,
    result: dict,
    artifacts: dict[str, str],
) -> dict:
    manifest = read_run_manifest(run_dir)
    summary = result["summary"].set_index("Metric")
    final_settings = result["final_settings"]
    record = {
        "property": result["property"],
        "method": result["method"],
        "metrics": {
            metric: float(summary.loc[metric, "Value"])
            for metric in ("R2", "RMSE", "RPIQ", "Bias")
        },
        "final_model": {
            "preprocessing": final_settings["Preprocessing"],
            "region": final_settings["Region"],
            "rank": int(final_settings["Rank"]),
        },
        "validation_samples": int(result["unique_validation_samples"]),
        "elapsed_seconds": float(result["elapsed_seconds"]),
        "artifacts": dict(artifacts),
    }
    manifest["results"].append(record)
    manifest["updated_at"] = _utc_now()
    write_json(Path(run_dir) / RUN_MANIFEST_NAME, manifest)
    return manifest


def record_run_failure(
    run_dir: str | Path,
    *,
    property_name: str,
    method: str,
    error: str,
) -> dict:
    manifest = read_run_manifest(run_dir)
    failures = manifest.setdefault("failures", [])
    failures.append(
        {
            "property": str(property_name),
            "method": str(method),
            "error": str(error),
            "recorded_at": _utc_now(),
        }
    )
    manifest["updated_at"] = _utc_now()
    write_json(Path(run_dir) / RUN_MANIFEST_NAME, manifest)
    return manifest


def finalize_run_manifest(
    run_dir: str | Path,
    *,
    status: str,
    error: str = "",
) -> dict:
    valid_statuses = {
        "completed",
        "completed_with_errors",
        "failed",
        "cancelled",
    }
    if status not in valid_statuses:
        raise ValueError(
            "Run status must be completed, completed_with_errors, "
            "failed, or cancelled."
        )
    manifest = read_run_manifest(run_dir)
    manifest["status"] = status
    manifest["error"] = str(error)
    manifest["updated_at"] = _utc_now()
    manifest["finished_at"] = _utc_now()
    write_json(Path(run_dir) / RUN_MANIFEST_NAME, manifest)
    return manifest


def list_run_history(output_base: str | Path) -> list[dict]:
    root = Path(output_base).expanduser()
    if not root.is_dir():
        return []

    history = []
    for run_dir in root.iterdir():
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            continue
        path = run_dir / RUN_MANIFEST_NAME
        if not path.is_file():
            continue
        try:
            manifest = read_run_manifest(run_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        manifest = dict(manifest)
        manifest["run_dir"] = str(run_dir)
        manifest["result_count"] = len(manifest.get("results", []))
        history.append(manifest)

    return sorted(
        history,
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )
