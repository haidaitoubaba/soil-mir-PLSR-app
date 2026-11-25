"""UI-only source linkage; no changes to scientific QC or manifest methods."""
from __future__ import annotations

import os
from pathlib import Path


def canonical_directory(value):
    if not value or not str(value).strip():
        return ""
    try:
        return os.path.normcase(str(Path(value).expanduser().resolve()))
    except (OSError, RuntimeError, ValueError):
        return ""


def applied_directory(state):
    # The dedicated key is written ONLY by successful Data inspection.
    if "rc7_data_applied_spectra_dir" in state:
        return state["rc7_data_applied_spectra_dir"]
    identity = state.get("rc6_data_inspected_identity")
    return identity[0] if identity else ""


def source_mode(state):
    explicit = state.get("rc7_qc_source_mode")
    if explicit in ("linked", "independent"):
        return explicit
    return "linked" if applied_directory(state) else "independent"


def effective_directory(state):
    return (applied_directory(state) if source_mode(state) == "linked"
            else state.get("rc6_value_qc_dir", ""))


def invalidate_source(state, reason):
    """Keep historical data/files, but never let a stale batch act as current."""
    if state.get("qc_config") or state.get("qc_data") is not None:
        state["rc7_qc_stale_reason"] = reason
    state.pop("qc_frozen", None)
    state.pop("qc_saved_folder", None)
    state.pop("qc_export_folder", None)
    state.pop("qc_review_notice", None)


def guard_source(state, directory):
    """Called before every section, including direct access to non-Setup."""
    config = state.get("qc_config")
    if config and canonical_directory(config[0]) != canonical_directory(directory):
        invalidate_source(state, "The spectral source changed.")
    return state.get("rc7_qc_stale_reason", "")


def record_data_inspection(state, directory):
    """Only a successful Inspect may publish a new canonical Data source."""
    old = applied_directory(state)
    state["rc7_data_applied_spectra_dir"] = str(Path(directory).expanduser().resolve())
    if source_mode(state) == "linked":
        new = applied_directory(state)
        if canonical_directory(old) != canonical_directory(new):
            guard_source(state, new)


def choose_source(state, mode):
    if mode not in ("linked", "independent"):
        raise ValueError("Unknown QC source mode.")
    state["rc7_qc_source_mode"] = mode
    guard_source(state, effective_directory(state))


def completed_batch(state):
    state.pop("rc7_qc_stale_reason", None)
    state.pop("qc_saved_folder", None)
    state.pop("qc_export_folder", None)
    state.pop("qc_review_notice", None)
