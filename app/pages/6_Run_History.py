from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.reporting import list_run_history
from soil_mir.services.local_paths import choose_local_path, load_path_preferences, open_local_folder
from soil_mir.services.model_catalog import list_model_catalog
from soil_mir.services.profiles import profile_widget_updates
from soil_mir.services.run_alias import alias_info, run_display_label, set_run_alias
from soil_mir.ui_models import render_model_preview, select_catalog_model, use_in_predict
from soil_mir.ui_state import remember_widget, request_section, reset_remembered, section_navigation
from soil_mir.methods import (
    format_analysis_key,
    validation_method_label,
)
from soil_mir.services.history import (
    DELETABLE_RUN_STATUSES,
    delete_saved_run,
    load_run_config,
    load_saved_run,
    pending_run_keys,
    run_config_session_values,
)


st.set_page_config(
    page_title="Run History | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Run History")
st.caption(
    "Inspect completed and interrupted analyses saved in the local results directory."
)


section = section_navigation("history")
prefs = load_path_preferences()
root_default = st.session_state.get("rc6_history_root") or st.session_state.get(
    "soil_mir_output_dir", prefs.get("output_dir", "")
)
path_col, browse_col = st.columns([5, 1])
if browse_col.button("Browse", key="history_root_browse"):
    try:
        chosen = choose_local_path("directory", prompt="Choose Results directory")
        if chosen:
            reset_remembered("history_root", str(chosen))
    except Exception as exc:
        st.error(str(exc))
output_dir = remember_widget(path_col, "text_input", "Results directory",
                             key="history_root", value=root_default)
if not output_dir.strip():
    st.info("Choose the Results directory used on the Data page.")
    st.stop()
output_dir = str(Path(output_dir).expanduser().resolve())
st.session_state.rc6_history_root = output_dir
history = list_run_history(output_dir)
if not history:
    st.info("No saved run manifests were found in this directory.")
    st.stop()

root_key = hashlib.sha256(output_dir.encode()).hexdigest()[:16]
aliases = {}
for item in history:
    aliases[item["run_id"]] = alias_info(item)
by_id = {item["run_id"]: item for item in history}
visible = history
if section == "Run Library":
    query = remember_widget(st, "text_input", "Search run name, ID, property or method",
                            key=f"history_query_{root_key}").strip().casefold()
    states = list(dict.fromkeys(item.get("status", "") for item in history))
    statuses = remember_widget(st, "multiselect", "Status filter",
                               key=f"history_status_{root_key}", options=states)
    properties = sorted({prop for item in history for prop in item.get("properties", [])})
    props = remember_widget(st, "multiselect", "Property filter",
                            key=f"history_property_filter_{root_key}", options=properties)
    methods = sorted({method for item in history for method in item.get("methods", [])})
    selected_methods = remember_widget(
        st, "multiselect", "Validation method filter", key=f"history_method_filter_{root_key}",
        options=methods, format_func=validation_method_label,
    )
    visible = []
    for item in history:
        alias = aliases[item["run_id"]][0]
        searchable = " ".join([
            alias, item["run_id"], *item.get("properties", []),
            *map(validation_method_label, item.get("methods", [])),
        ]).casefold()
        if (query and query not in searchable) or (statuses and item.get("status") not in statuses):
            continue
        if props and not set(props).intersection(item.get("properties", [])):
            continue
        if selected_methods and not set(selected_methods).intersection(item.get("methods", [])):
            continue
        visible.append(item)
    rows = []
    for manifest in visible:
        results = manifest.get("results", [])
        rows.append(
            {
                "Run name": aliases[manifest["run_id"]][0] or "—",
                "Run ID": manifest.get("run_id", ""),
                "Created": manifest.get("created_at", ""),
                "Status": manifest.get("status", ""),
                "Properties": ", ".join(
                    manifest.get("properties", [])
                ),
                "Methods": ", ".join(
                    validation_method_label(
                        method
                    )
                    for method in manifest.get(
                        "methods",
                        [],
                    )
                ),
                "Completed analyses": len(results),
                "Pending analyses": len(
                    pending_run_keys(
                        manifest
                    )
                ),
                "Failed analyses": len(manifest.get("failures", [])),
                "Final-only refits": len(
                    manifest.get(
                        "final_refits",
                        [],
                    )
                ),
                "Directory": manifest.get("run_dir", ""),
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )

options = [""] + [item["run_id"] for item in visible]
run_id = remember_widget(
    st, "selectbox", "Select run", key=f"history_selected_{root_key}",
    options=options,
    format_func=lambda value: (
        run_display_label(value, aliases[value][0]) if value else "Choose a run"
    ),
)
if not run_id:
    st.info("Select a run in the library to inspect or manage it.")
    st.stop()
manifest = by_id[run_id]
run_dir = Path(manifest["run_dir"]).resolve()
alias, alias_error = aliases[run_id]
run_status = manifest.get("status", "")
run_key = hashlib.sha256(str(run_dir).encode()).hexdigest()[:16]
st.caption(f"Run: {run_display_label(run_id, alias)} | {run_status}")
if alias_error:
    st.warning(f"Run display name unavailable: {alias_error}")

if section == "Run Library":
    name = st.text_input("Custom run name", value=alias, key=f"history_alias_{run_key}",
                         max_chars=100, help="Blank clears the display name; Run ID stays unchanged.")
    if st.button("Save run name"):
        try:
            set_run_alias(output_dir, run_dir, name)
        except (OSError, ValueError) as exc:
            st.error(f"Cannot save run name: {exc}")
        else:
            st.rerun()
    for col, target in zip(st.columns(3), ("Run Details", "Saved Models", "Management")):
        if col.button(f"Open {target}"):
            request_section("history", target)
            st.rerun()

elif section == "Run Details":
    st.write(
        f"**Run directory:** {manifest.get('run_dir', '')}"
    )
    st.write(
        f"**Spectra:** {manifest.get('spectra_dir', '')}"
    )
    st.write(
        f"**Reference workbook:** "
        f"{manifest.get('reference_excel', '')}"
    )
    try:
        saved_qc = load_run_config(manifest["run_dir"]).get("qc_manifest")
        if saved_qc:
            st.caption(f"QC selection: {saved_qc['manifest_id'][:12]}")
    except (OSError, ValueError, KeyError):
        pass
    error = manifest.get("error", "")
    if error:
        st.error(error)
    if manifest.get("results"):
        if st.button(
            "Open this run in Results",
            key=f"open_history_{manifest.get('run_id')}",
        ):
            try:
                loaded = load_saved_run(manifest)
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state["soil_mir_results"] = loaded
                st.session_state["soil_mir_last_run_dir"] = (
                    manifest.get("run_dir", "")
                )
                comparison = (
                    Path(manifest.get("run_dir", ""))
                    / "Validation_Comparison.xlsx"
                )
                st.session_state[
                    "soil_mir_last_comparison"
                ] = (
                    str(comparison)
                    if comparison.is_file()
                    else ""
                )
                request_section("results", "Overview")
                st.switch_page("pages/4_Results.py")

    result_rows = []
    for result in manifest.get("results", []):
        metrics = result.get("metrics", {})
        model = result.get("final_model", {})
        result_rows.append(
            {
                "Property": result.get("property", ""),
                "Method": validation_method_label(
                    result.get(
                        "method",
                        "",
                    )
                ),
                "R²": metrics.get("R2"),
                "RMSE": metrics.get("RMSE"),
                "RPIQ": metrics.get("RPIQ"),
                "Bias": metrics.get("Bias"),
                "Preprocessing": model.get(
                    "preprocessing",
                    "",
                ),
                "Region": model.get("region", ""),
                "Rank": model.get("rank"),
                "Validation samples": result.get(
                    "validation_samples"
                ),
                "Elapsed (s)": result.get(
                    "elapsed_seconds"
                ),
            }
        )

    if result_rows:
        st.dataframe(
            pd.DataFrame(result_rows),
            use_container_width=True,
            hide_index=True,
        )

    try:
        config = load_run_config(run_dir)
        with st.expander("Saved run configuration"):
            st.json(config)
    except (OSError, ValueError) as exc:
        st.caption(f"Saved configuration unavailable: {exc}")
    if st.button("Open run folder"):
        try:
            open_local_folder(run_dir)
        except Exception as exc:
            st.error(str(exc))

elif section == "Saved Models":

    entries = list_model_catalog(output_dir, manifests=[manifest])
    if entries:
        st.dataframe(pd.DataFrame([
            {"Property": item["property"], "Method": validation_method_label(item["method"]),
             "Variant": item["variant"], "Rank": item["final_model"].get("rank"),
             "Created": item["created_at"], "Model": item["path"]} for item in entries
        ]), hide_index=True)
    selected = select_catalog_model(entries, f"history_model_{run_key}", fixed_run=run_id)
    if selected is not None:
        path = Path(selected["path"])
        preview = render_model_preview(path, selected, "rc6_history_preview")
        if preview is not None and st.button("Use selected model in Predict"):
            use_in_predict(selected)
        st.code(str(path))
        if path.is_file():
            st.download_button("Download selected model", data=path.read_bytes(),
                               file_name=path.name, mime="application/octet-stream")
        workbook = Path(selected["record"].get("artifacts", {}).get("workbook", ""))
        if workbook.is_file():
            st.download_button(
                "Download selected result / refit workbook", data=workbook.read_bytes(),
                file_name=workbook.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if st.button("Open model folder"):
            try:
                open_local_folder(path.parent)
            except Exception as exc:
                st.error(str(exc))

elif section == "Management":

    st.subheader("Run management")
    pending = pending_run_keys(
        manifest
    )
    if pending:
        st.write(
            "**Pending analyses:** "
            + ", ".join(
                format_analysis_key(
                    key
                )
                for key in sorted(
                    pending
                )
            )
        )
        if st.button(
            "Resume incomplete run",
            disabled=bool(st.session_state.get("soil_mir_active_validation_job")),
            key=(
                f"resume_history_"
                f"{manifest.get('run_id')}"
            ),
            type="primary",
        ):
            try:
                config = load_run_config(
                    manifest.get(
                        "run_dir",
                        "",
                    )
                )
                session_values = (
                    run_config_session_values(
                        config,
                        run_dir=manifest.get(
                            "run_dir",
                            "",
                        ),
                    )
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state.update(session_values)
                st.session_state.update(profile_widget_updates(
                    session_values, session_values.get("soil_mir_selected_properties", [])
                ))
                st.session_state.rc6_configuration_dirty = False
                st.session_state[
                    "soil_mir_resume_run_dir"
                ] = manifest.get(
                    "run_dir",
                    "",
                )
                for key in (
                    "soil_mir_preflight_table",
                    "soil_mir_preflight_datasets",
                    "soil_mir_preflight_passed",
                    "soil_mir_preflight_signature",
                ):
                    st.session_state.pop(
                        key,
                        None,
                    )
                request_section("run", "Preflight")
                st.switch_page("pages/3_Run.py")
    failures = manifest.get("failures", [])
    if failures:
        st.subheader("Failed analyses")
        st.dataframe(
            pd.DataFrame(failures),
            use_container_width=True,
            hide_index=True,
        )

    delete_state_key = f"soil_mir_confirm_delete_run_{run_key}"
    if run_status in DELETABLE_RUN_STATUSES:
        if not st.session_state.get(delete_state_key):
            if st.button("🗑 Delete this run", key=f"delete_history_{run_key}"):
                st.session_state[delete_state_key] = True
                st.rerun()
        else:
            st.warning(
                f"Permanently delete run {run_id}? This removes its saved results, models, "
                "refits, plots, reports, display name and resume information."
            )
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Delete permanently", type="primary",
                                  key=f"confirm_delete_history_{run_key}"):
                try:
                    deleted = delete_saved_run(output_dir, run_dir)
                except Exception as exc:
                    st.error(f"Could not delete run: {exc}")
                else:
                    st.session_state.pop(delete_state_key, None)
                    last_run = st.session_state.get("soil_mir_last_run_dir")
                    if last_run and Path(last_run).expanduser().resolve() == deleted:
                        for key in ("soil_mir_results", "soil_mir_last_run_dir",
                                    "soil_mir_last_comparison"):
                            st.session_state.pop(key, None)
                    resume_path = st.session_state.get("soil_mir_resume_run_dir")
                    if resume_path and Path(resume_path).expanduser().resolve() == deleted:
                        st.session_state.pop("soil_mir_resume_run_dir", None)
                    current = st.session_state.get("soil_mir_predict_model_input", "")
                    model_paths = {
                        str(Path(item["artifacts"]["model"]).expanduser().resolve())
                        for item in manifest.get("results", []) + manifest.get("final_refits", [])
                        if item.get("artifacts", {}).get("model")
                    }
                    if current and (
                        Path(current).expanduser().resolve().is_relative_to(deleted)
                        or str(Path(current).expanduser().resolve()) in model_paths
                    ):
                        for key in ("soil_mir_predict_model_input",
                                    "soil_mir_predict_selected_history_model",
                                    "rc6_predict_preview", "soil_mir_predict_compatibility"):
                            st.session_state.pop(key, None)
                        st.session_state.rc6_predict_selection_removed = True
                    reset_remembered(f"history_selected_{root_key}", "")
                    request_section("history", "Run Library")
                    st.rerun()
            if cancel_col.button("Cancel", key=f"cancel_delete_history_{run_key}"):
                st.session_state.pop(delete_state_key, None)
                st.rerun()
    else:
        st.caption(f"This run cannot be deleted while its status is {run_status or 'unknown'}.")
