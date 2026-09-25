from __future__ import annotations

import json
import re
from pathlib import Path


PROFILE_VERSION = 1
PROFILE_DIRNAME = ".soil_mir_profiles"

PROFILE_WIDGET_KEYS = {
    "soil_mir_selected_properties": "cfg_selected_properties",
    "soil_mir_wn_range": "cfg_wn_range",
    "soil_mir_exclude_co2": "cfg_exclude_co2",
    "soil_mir_max_rank": "cfg_max_rank",
    "soil_mir_validation_methods": "cfg_validation_methods",
    "soil_mir_use_group_stratification": "cfg_use_group_stratification",
    "soil_mir_region_windows": "cfg_region_windows",
    "soil_mir_tolerance": "cfg_tolerance",
    "soil_mir_sg_window": "cfg_sg_window",
    "soil_mir_sg_polyorder": "cfg_sg_polyorder",
    "soil_mir_random_seed": "cfg_random_seed",
    "soil_mir_internal_cv_folds": "cfg_internal_cv_folds",
    "soil_mir_outer_cv_folds": "cfg_outer_cv_folds",
    "soil_mir_n_repeats": "cfg_n_repeats",
    "soil_mir_validation_fraction": "cfg_validation_fraction",
    "soil_mir_ks_representation": "cfg_ks_representation",
    "soil_mir_ks_pca_variance": "cfg_ks_pca_variance",
    "soil_mir_outer_n_jobs": "cfg_outer_n_jobs",
    "soil_mir_inner_thread_limit": "cfg_inner_thread_limit",
}


def profile_widget_updates(
    settings: dict,
    available_properties: list[str] | tuple[str, ...],
) -> dict:
    """Translate saved configuration values into explicit Streamlit widget state."""
    updates = {}
    for config_key, widget_key in PROFILE_WIDGET_KEYS.items():
        if config_key not in settings:
            continue
        value = settings[config_key]
        if config_key == "soil_mir_wn_range":
            value = tuple(value)
        updates[widget_key] = value

    ranges = settings.get(
        "soil_mir_reference_ranges",
        {},
    )
    for property_name in available_properties:
        bounds = ranges.get(property_name, {})
        for bound in ("min", "max"):
            value = bounds.get(bound)
            updates[
                f"ref_{bound}_{property_name}"
            ] = (
                ""
                if value is None
                else str(value)
            )
    return updates


def _safe_profile_name(name: str) -> str:
    cleaned = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(name).strip(),
    ).strip("_.")
    if not cleaned:
        raise ValueError("Profile name must contain letters or numbers.")
    return cleaned


def profile_directory(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser() / PROFILE_DIRNAME


def list_profiles(output_dir: str | Path) -> dict[str, Path]:
    directory = profile_directory(output_dir)
    if not directory.is_dir():
        return {}
    return {
        path.stem: path
        for path in sorted(directory.glob("*.json"))
        if path.is_file()
    }


def save_profile(
    output_dir: str | Path,
    name: str,
    settings: dict,
) -> Path:
    directory = profile_directory(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_profile_name(name)
    path = directory / f"{safe_name}.json"
    payload = {
        "version": PROFILE_VERSION,
        "name": safe_name,
        "settings": dict(settings),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def delete_profile(
    output_dir: str | Path,
    name: str,
) -> Path:
    """Delete exactly one saved configuration profile."""
    safe_name = _safe_profile_name(name)
    path = (
        profile_directory(output_dir)
        / f"{safe_name}.json"
    )
    if not path.is_file():
        raise FileNotFoundError(
            f"Configuration profile not found: {path}"
        )
    path.unlink()
    return path


def load_profile(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Configuration profile not found: {path}"
        )
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Configuration profile is not valid JSON: {path}"
        ) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("version") != PROFILE_VERSION
        or not isinstance(payload.get("settings"), dict)
    ):
        raise ValueError(
            f"Unsupported configuration profile: {path}"
        )
    return dict(payload["settings"])
