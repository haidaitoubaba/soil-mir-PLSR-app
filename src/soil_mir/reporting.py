from __future__ import annotations

import json
import re
from datetime import datetime
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
    Path(path).write_text(
        json.dumps(
            payload,
            indent=2,
            default=_json_default,
        ),
        encoding="utf-8",
    )


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
