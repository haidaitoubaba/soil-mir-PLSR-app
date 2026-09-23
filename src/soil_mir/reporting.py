from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

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
    config_path = target / "Resolved_Config.json"
    split_path = target / "Split_Info.json"

    joblib.dump(
        result["final_model"],
        model_path,
        compress=3,
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
        [result["final_settings"]]
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

    return {
        "directory": str(target),
        "model": str(model_path),
        "workbook": str(workbook_path),
        "config": str(config_path),
        "split_info": str(split_path),
    }


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


def finalize_run_manifest(
    run_dir: str | Path,
    *,
    status: str,
    error: str = "",
) -> dict:
    if status not in {"completed", "failed", "cancelled"}:
        raise ValueError("Run status must be completed, failed, or cancelled.")
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
