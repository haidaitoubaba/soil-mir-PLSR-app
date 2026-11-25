"""Local display-only run aliases, independent of scientific artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unicodedata

from soil_mir.reporting import read_run_manifest


ALIAS_FILE = ".soil_mir_run_alias.json"
MAX_ALIAS_LENGTH = 100


def validated_alias(value: str) -> str:
    text = str(value).strip()
    if len(text) > MAX_ALIAS_LENGTH:
        raise ValueError(f"Run name must be at most {MAX_ALIAS_LENGTH} characters.")
    if any(unicodedata.category(char).startswith("C") for char in text):
        raise ValueError("Run name must not contain control or formatting characters.")
    return text


def _run_path(output_root, run_dir):
    root = Path(output_root).expanduser().resolve()
    path = Path(run_dir).expanduser().resolve()
    if path.parent != root or not path.is_dir():
        raise ValueError("Choose an existing direct child run of the Results directory.")
    manifest = read_run_manifest(path)
    if manifest.get("run_id") != path.name:
        raise ValueError("Run ID does not match the selected directory.")
    return path


def read_run_alias(run_dir) -> str:
    path = Path(run_dir) / ALIAS_FILE
    if not path.is_file():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict) or payload.get("version") != 1
        or not isinstance(payload.get("name"), str)
    ):
        raise ValueError("Invalid run display-name metadata.")
    return validated_alias(payload["name"])


def run_display_label(run_id, alias=""):
    return f"{alias} | {run_id}" if alias else str(run_id)


def set_run_alias(output_root, run_dir, name: str) -> str:
    """Atomically save a display name without modifying a manifest or model."""
    folder = _run_path(output_root, run_dir)
    value = validated_alias(name)
    target = folder / ALIAS_FILE
    if not value:
        target.unlink(missing_ok=True)
        return ""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=folder, prefix=".run-alias-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"version": 1, "name": value}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return value


def alias_info(manifest: dict) -> tuple[str, str]:
    """Keep a run discoverable if its optional alias metadata is unreadable."""
    try:
        return read_run_alias(manifest["run_dir"]), ""
    except (KeyError, OSError, ValueError) as exc:
        return "", str(exc)
