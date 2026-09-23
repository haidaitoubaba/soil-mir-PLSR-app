from __future__ import annotations

import json
import re
from pathlib import Path


PROFILE_VERSION = 1
PROFILE_DIRNAME = ".soil_mir_profiles"


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
