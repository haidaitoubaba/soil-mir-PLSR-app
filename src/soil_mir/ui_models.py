"""Shared model selector and explicit preview for History and Predict."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.methods import validation_method_label
from soil_mir.services.model_catalog import model_file_identity, preview_model
from soil_mir.ui_state import remember_widget, request_section, reset_remembered


def select_catalog_model(entries, prefix, *, preferred=None, fixed_run=None):
    """Choose actual hierarchical combinations; an empty choice never applies a model."""
    if not entries:
        st.info("No available models in this Results directory.")
        return None
    run_labels = {}
    for item in entries:
        run_labels[item["run_id"]] = (
            f"{item['run_label']} | {item['run_status']} | {item['run_created'] or ''}"
        )
    if preferred is not None:
        reset_remembered(f"{prefix}_run", preferred["run_id"])
        reset_remembered(f"{prefix}_property_{preferred['run_id']}", preferred["property"])
        reset_remembered(
            f"{prefix}_method_{preferred['run_id']}_{preferred['property']}", preferred["method"]
        )
        reset_remembered(
            f"{prefix}_variant_{preferred['run_id']}_{preferred['property']}_{preferred['method']}",
            preferred["id"],
        )
    if fixed_run is None:
        run_id = remember_widget(
            st, "selectbox", "Calibration run", key=f"{prefix}_run",
            options=[""] + list(run_labels),
            format_func=lambda item: run_labels.get(item, "Choose a run"),
        )
    else:
        run_id = fixed_run
    if not run_id:
        return None
    candidates = [item for item in entries if item["run_id"] == run_id]
    properties = list(dict.fromkeys(item["property"] for item in candidates))
    prop = remember_widget(
        st, "selectbox", "Soil property", key=f"{prefix}_property_{run_id}",
        options=[""] + properties, format_func=lambda item: item or "Choose a property",
    )
    if not prop:
        return None
    candidates = [item for item in candidates if item["property"] == prop]
    methods = list(dict.fromkeys(item["method"] for item in candidates))
    method = remember_widget(
        st, "selectbox", "Validation method", key=f"{prefix}_method_{run_id}_{prop}",
        options=[""] + methods,
        format_func=lambda item: validation_method_label(item) if item else "Choose a method",
    )
    if not method:
        return None
    candidates = [item for item in candidates if item["method"] == method]
    by_id = {item["id"]: item for item in candidates}
    labels = {
        key: f"{item['variant']} | rank {item['final_model'].get('rank', 'Not recorded')} | "
        f"{item['created_at']}" for key, item in by_id.items()
    }
    selected = remember_widget(
        st, "selectbox", "Model variant", key=f"{prefix}_variant_{run_id}_{prop}_{method}",
        options=[""] + list(by_id), format_func=lambda item: labels.get(item, "Choose a model"),
    )
    return by_id.get(selected)


def render_model_preview(path, entry, key, *, automatic=False):
    """Do not deserialize arbitrary joblib files merely because they are listed."""
    st.caption("Only preview or use a trusted local .joblib file (pickle can execute code).")
    try:
        signature = model_file_identity(path)
    except (OSError, ValueError) as exc:
        st.error(f"Model unavailable: {exc}")
        return None
    # Include the recorded display/validation metadata, not just the model file identity.
    metadata_identity = repr(entry) if entry else None
    identity = (signature, entry.get("id") if entry else None, metadata_identity)
    previous = st.session_state.get(key)
    if automatic or st.button("Preview selected model", key=f"{key}_preview"):
        if not previous or previous[0] != identity:
            try:
                preview = preview_model(path, entry)
            except Exception as exc:
                st.session_state.pop(key, None)
                st.error(f"Model preview failed: {exc}")
                return None
            st.session_state[key] = (identity, preview)
    previous = st.session_state.get(key)
    if previous is None or previous[0] != identity:
        st.caption("Confirm the model preview to read its saved parameters.")
        return None
    preview = previous[1]
    st.subheader("Model metadata")
    st.dataframe(pd.DataFrame({
        "Field": list(preview["fields"]), "Value": [str(x) for x in preview["fields"].values()]
    }), hide_index=True)
    st.subheader("Historical validation performance")
    if preview["source_only"]:
        st.info("Source outer-validation metrics only; this final-only refit was not revalidated.")
    if preview["note"]:
        st.warning(preview["note"])
    metrics = {**preview["metrics"], "Validation samples": preview["validation_samples"]}
    st.dataframe(pd.DataFrame({
        "Metric": list(metrics), "Value": [str(x) for x in metrics.values()]
    }), hide_index=True)
    return preview


def use_in_predict(entry):
    st.session_state.soil_mir_predict_model_input = entry["path"]
    st.session_state.soil_mir_predict_selected_history_model = dict(entry)
    st.session_state.rc6_predict_root = entry["root"]
    st.session_state.soil_mir_predict_output_input = str(Path(entry["root"]))
    st.session_state.rc6_predict_incoming = True
    request_section("predict", "Model")
    st.switch_page("pages/5_Predict.py")
