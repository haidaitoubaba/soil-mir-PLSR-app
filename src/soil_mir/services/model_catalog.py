"""Lightweight model discovery and explicit selected-model metadata preview."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.methods import validation_method_label
from soil_mir.reporting import list_run_history
from soil_mir.services.prediction import load_model_bundle
from soil_mir.services.run_alias import alias_info, run_display_label


METRIC_NAMES = ("R2", "RMSE", "RPD", "RPIQ", "Bias", "MAE", "CCC")
NOT_RECORDED = "Not recorded"


def _model_id(root, run_id, property_name, method, role, tolerance, path):
    fields = [str(root), run_id, property_name, method, role, tolerance, str(path)]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()


def list_model_catalog(output_root, manifests=None):
    """Index available artifacts; never deserialize a model while listing runs."""
    if not output_root:
        return []
    root = Path(output_root).expanduser().resolve()
    history = list_run_history(root) if manifests is None else manifests
    entries = []
    for manifest in history:
        run_id = str(manifest.get("run_id", ""))
        run_dir = Path(manifest.get("run_dir") or root / run_id).resolve()
        if not run_id or run_dir.parent != root or run_dir.name != run_id:
            continue
        alias, alias_error = alias_info({**manifest, "run_dir": run_dir})
        results = manifest.get("results", [])
        for role, records in (
            ("validated_final_model", results),
            ("final_only_refit", manifest.get("final_refits", [])),
        ):
            for record in records:
                artifacts = record.get("artifacts", {})
                path = Path(artifacts.get("model", "")).expanduser().resolve()
                if not path.is_file():
                    continue
                property_name = str(record.get("property", ""))
                method = str(record.get("method", ""))
                tolerance = (record.get("refit_tolerance_pct")
                             if role == "final_only_refit" else None)
                source = record
                if role == "final_only_refit":
                    matches = [item for item in results if item.get("property") == property_name
                               and item.get("method") == method]
                    source = matches[0] if len(matches) == 1 else {}
                identity = _model_id(root, run_id, property_name, method, role, tolerance, path)
                variant = ("Validated final model" if role == "validated_final_model"
                           else f"Final-only refit {tolerance}%")
                entries.append({
                    "id": identity, "path": str(path), "run_id": run_id,
                    "run_dir": str(run_dir), "root": str(root),
                    "run_name": alias, "run_label": run_display_label(run_id, alias),
                    "run_status": manifest.get("status", ""), "run_created": manifest.get("created_at"),
                    "alias_error": alias_error, "property": property_name, "method": method,
                    "model_role": role, "variant": variant, "refit_tolerance_pct": tolerance,
                    "source_validation_tolerance_pct": record.get(
                        "source_validation_tolerance_pct"
                    ),
                    "created_at": record.get("created_at", manifest.get("created_at", "")),
                    "final_model": record.get("final_model", {}),
                    "source_metrics": source.get("metrics", {}),
                    "source_workbook": source.get("artifacts", {}).get("workbook", ""),
                    "validation_samples": source.get("validation_samples"),
                    "spectra_dir": manifest.get("spectra_dir"),
                    "reference_excel": manifest.get("reference_excel"),
                    "record": record,
                })
    return sorted(entries, key=lambda item: item["created_at"], reverse=True)


def catalog_options(entries, run_id=None, property_name=None, method=None):
    """Return actual combinations rather than a Cartesian product."""
    matches = [item for item in entries
               if (run_id is None or item["run_id"] == run_id)
               and (property_name is None or item["property"] == property_name)
               and (method is None or item["method"] == method)]
    return matches


def model_file_identity(path):
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    if not resolved.is_file():
        raise ValueError("Selected model is not a file.")
    return str(resolved), stat.st_size, stat.st_mtime_ns


def _display(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return NOT_RECORDED
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return NOT_RECORDED
    return value


def preview_model(path, entry=None):
    """Load only a deliberately selected trusted local model; no writes."""
    bundle = load_model_bundle(path)
    entry = entry or {}
    if entry and model_file_identity(path)[0] != model_file_identity(entry["path"])[0]:
        raise ValueError("Model path does not match the selected catalog artifact.")
    for bundle_key, entry_key in (("property_name", "property"), ("validation_method", "method")):
        if bundle.get(bundle_key) and entry.get(entry_key) and (
            bundle[bundle_key] != entry[entry_key]
        ):
            raise ValueError(f"Saved model {bundle_key} disagrees with its run history.")
    axis = np.asarray(bundle["wavenumbers"], dtype=float)
    valid_axis = axis.ndim == 1 and axis.size and np.all(np.isfinite(axis))
    role = bundle.get("artifact_role") or entry.get("model_role")
    if entry.get("model_role") and bundle.get("artifact_role") and (
        entry["model_role"] != bundle["artifact_role"]
    ):
        raise ValueError("Saved model role disagrees with its run history.")
    fields = {
        "Property": bundle.get("property_name") or entry.get("property"),
        "Units": bundle.get("units"),
        "Validation method": validation_method_label(
            bundle.get("validation_method") or entry.get("method")
        ) if bundle.get("validation_method") or entry.get("method") else None,
        "Model role": role,
        "PLS rank": bundle.get("selected_rank", entry.get("final_model", {}).get("rank")),
        "Fitted PLS rank": bundle.get("fitted_rank"),
        "Preprocessing": bundle.get("selected_preprocessing",
                                    entry.get("final_model", {}).get("preprocessing")),
        "Response transformation": bundle.get("response_transform"),
        "Transform parameter": bundle.get("response_transform_parameter"),
        "Selected region": bundle.get(
            "selected_region", entry.get("final_model", {}).get("region")
        ),
        "Wavenumber minimum (cm⁻¹)": float(axis.min()) if valid_axis else None,
        "Wavenumber maximum (cm⁻¹)": float(axis.max()) if valid_axis else None,
        "Spectral points": int(axis.size) if valid_axis else None,
        "Grid spacing median (cm⁻¹)": (
            float(np.median(np.abs(np.diff(axis)))) if valid_axis and axis.size > 1 else None
        ),
        "Axis direction": (
            "Increasing" if np.all(np.diff(axis) > 0)
            else "Decreasing" if np.all(np.diff(axis) < 0) else "Non-monotonic"
        ) if valid_axis and axis.size > 1 else None,
        "Selected intervals": str(bundle["selected_regions_cm1"])
        if bundle.get("selected_regions_cm1") is not None else None,
        "CO₂ excluded": bundle.get("exclude_co2"),
        "OPUS axis mode (recorded)": bundle.get("opus_axis_mode"),
        "Training samples": bundle.get("training_sample_count"),
        "Training spectra": bundle.get("training_spectrum_count"),
        "RMSECV tolerance (%)": bundle.get("rmsecv_tolerance_pct"),
        "Refit tolerance (%)": bundle.get("refit_tolerance_pct", entry.get("refit_tolerance_pct")),
        "Source run ID": entry.get("run_id") or bundle.get("source_run_id"),
        "Run name": entry.get("run_name"),
        "Run created": entry.get("run_created"),
        "Model created": entry.get("created_at"),
        "Source validation tolerance (%)": bundle.get(
            "source_validation_tolerance_pct", entry.get("source_validation_tolerance_pct")
        ),
        "Reference workbook": entry.get("reference_excel"),
        "Calibration spectra": entry.get("spectra_dir"),
    }
    metrics = dict(entry.get("source_metrics", {}))
    # Old manifests may omit some metrics; read the exact source workbook only.
    source = Path(entry.get("source_workbook") or "")
    note = ""
    if source.is_file() and any(key not in metrics for key in METRIC_NAMES):
        try:
            summary = pd.read_excel(source, sheet_name="Summary")
            if {"Metric", "Value"} <= set(summary.columns):
                for key, value in zip(summary["Metric"], summary["Value"]):
                    metrics.setdefault(key, value)
        except (OSError, ValueError, KeyError) as exc:
            note = f"Historical summary unavailable: {exc}"
    return {
        "fields": {key: _display(value) for key, value in fields.items()},
        "metrics": {key: _display(metrics.get(key)) for key in METRIC_NAMES},
        "validation_samples": _display(entry.get("validation_samples")),
        "source_only": role == "final_only_refit",
        "note": note,
    }
