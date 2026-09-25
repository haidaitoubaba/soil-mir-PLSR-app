from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.reporting import list_run_history
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

output_dir = st.text_input(
    "Results directory",
    value=st.session_state.get(
        "soil_mir_output_dir",
        "",
    ),
    placeholder="/path/to/soil_mir_results",
)

if not output_dir:
    st.info(
        "Choose the same results directory used on the Data page."
    )
    st.stop()

history = list_run_history(
    Path(output_dir).expanduser()
)
if not history:
    st.info(
        "No saved run manifests were found in this directory."
    )
    st.stop()

rows = []
for manifest in history:
    results = manifest.get("results", [])
    rows.append(
        {
            "Run": manifest.get("run_id", ""),
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

for manifest in history:
    label = (
        f"{manifest.get('run_id', 'run')} — "
        f"{manifest.get('status', 'unknown')}"
    )
    with st.expander(label):
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
        error = manifest.get("error", "")
        if error:
            st.error(error)

        run_id = manifest.get(
            "run_id",
            "run",
        )
        run_status = manifest.get(
            "status",
            "",
        )
        delete_state_key = (
            "soil_mir_confirm_delete_run_"
            f"{run_id}"
        )

        if run_status in DELETABLE_RUN_STATUSES:
            if not st.session_state.get(
                delete_state_key,
                False,
            ):
                if st.button(
                    "🗑 Delete this run",
                    key=f"delete_history_{run_id}",
                ):
                    st.session_state[
                        delete_state_key
                    ] = True
                    st.rerun()
            else:
                st.warning(
                    f"Permanently delete run {run_id}? "
                    "This removes all validation results, models, "
                    "refits, plots, reports, and resume information "
                    "stored in this run directory."
                )
                confirm_col, cancel_col = st.columns(
                    2
                )
                with confirm_col:
                    if st.button(
                        "Delete permanently",
                        key=(
                            "confirm_delete_history_"
                            f"{run_id}"
                        ),
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            deleted_path = delete_saved_run(
                                output_dir,
                                manifest.get(
                                    "run_dir",
                                    "",
                                ),
                            )
                        except Exception as exc:
                            st.error(
                                f"Could not delete run: {exc}"
                            )
                        else:
                            st.session_state.pop(
                                delete_state_key,
                                None,
                            )
                            deleted_text = str(
                                deleted_path
                            )
                            if (
                                st.session_state.get(
                                    "soil_mir_last_run_dir"
                                )
                                == deleted_text
                            ):
                                st.session_state.pop(
                                    "soil_mir_results",
                                    None,
                                )
                                st.session_state.pop(
                                    "soil_mir_last_run_dir",
                                    None,
                                )
                                st.session_state.pop(
                                    "soil_mir_last_comparison",
                                    None,
                                )
                            if (
                                st.session_state.get(
                                    "soil_mir_resume_run_dir"
                                )
                                == deleted_text
                            ):
                                st.session_state.pop(
                                    "soil_mir_resume_run_dir",
                                    None,
                                )
                            selected_model = (
                                st.session_state.get(
                                    "soil_mir_predict_selected_history_model",
                                    {},
                                )
                            )
                            if (
                                isinstance(
                                    selected_model,
                                    dict,
                                )
                                and selected_model.get(
                                    "run_id"
                                )
                                == run_id
                            ):
                                st.session_state.pop(
                                    "soil_mir_predict_selected_history_model",
                                    None,
                                )
                            st.success(
                                f"Deleted run {run_id}."
                            )
                            st.rerun()
                with cancel_col:
                    if st.button(
                        "Cancel",
                        key=(
                            "cancel_delete_history_"
                            f"{run_id}"
                        ),
                        use_container_width=True,
                    ):
                        st.session_state.pop(
                            delete_state_key,
                            None,
                        )
                        st.rerun()
        else:
            st.caption(
                "This run cannot be deleted while its status is "
                f"{run_status or 'unknown'}."
            )

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
                    st.session_state.update(
                        session_values
                    )
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
                    st.switch_page(
                        "pages/3_Run.py"
                    )

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

        failures = manifest.get("failures", [])
        if failures:
            st.subheader("Failed analyses")
            st.dataframe(
                pd.DataFrame(failures),
                use_container_width=True,
                hide_index=True,
            )

        final_refits = manifest.get(
            "final_refits",
            [],
        )
        if final_refits:
            st.subheader(
                "Final-only tolerance refits"
            )
            refit_rows = []
            for refit in final_refits:
                model = refit.get(
                    "final_model",
                    {},
                )
                refit_rows.append(
                    {
                        "Property": refit.get(
                            "property",
                            "",
                        ),
                        "Method": validation_method_label(
                            refit.get(
                                "method",
                                "",
                            )
                        ),
                        "Tolerance (%)": refit.get(
                            "refit_tolerance_pct"
                        ),
                        "Source validation tolerance (%)": refit.get(
                            "source_validation_tolerance_pct"
                        ),
                        "Preprocessing": model.get(
                            "preprocessing",
                            "",
                        ),
                        "Region": model.get(
                            "region",
                            "",
                        ),
                        "Rank": model.get(
                            "rank"
                        ),
                        "Outer validation rerun": refit.get(
                            "outer_validation_rerun",
                            False,
                        ),
                    }
                )
            st.dataframe(
                pd.DataFrame(
                    refit_rows
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "These models were refit on all calibration data only. "
                "They do not have new outer-validation metrics."
            )

            for refit in final_refits:
                artifacts = refit.get(
                    "artifacts",
                    {},
                )
                model_path = Path(
                    artifacts.get(
                        "model",
                        "",
                    )
                )
                workbook = Path(
                    artifacts.get(
                        "workbook",
                        "",
                    )
                )
                if not model_path.is_file():
                    continue
                property_name = refit.get(
                    "property",
                    "property",
                )
                method = refit.get(
                    "method",
                    "method",
                )
                tolerance = float(
                    refit.get(
                        "refit_tolerance_pct",
                        0.0,
                    )
                )
                method_label = (
                    validation_method_label(
                        method
                    )
                )
                st.markdown(
                    f"**{property_name} / {method_label} — "
                    f"final-only refit {tolerance:g}%**"
                )
                refit_download_col, refit_predict_col = st.columns(
                    2
                )
                with refit_download_col:
                    st.download_button(
                        "Download refit model",
                        data=(
                            model_path.read_bytes()
                        ),
                        file_name=(
                            model_path.name
                        ),
                        mime="application/octet-stream",
                        key=(
                            "history_refit_model_"
                            f"{manifest.get('run_id')}_"
                            f"{property_name}_"
                            f"{method}_"
                            f"{tolerance:g}"
                        ),
                        use_container_width=True,
                    )
                    if workbook.is_file():
                        st.download_button(
                            "Download refit selection",
                            data=(
                                workbook.read_bytes()
                            ),
                            file_name=(
                                workbook.name
                            ),
                            mime=(
                                "application/vnd.openxmlformats-"
                                "officedocument.spreadsheetml.sheet"
                            ),
                            key=(
                                "history_refit_workbook_"
                                f"{manifest.get('run_id')}_"
                                f"{property_name}_"
                                f"{method}_"
                                f"{tolerance:g}"
                            ),
                            use_container_width=True,
                        )
                with refit_predict_col:
                    if st.button(
                        "Use refit model in Predict",
                        key=(
                            "history_refit_predict_"
                            f"{manifest.get('run_id')}_"
                            f"{property_name}_"
                            f"{method}_"
                            f"{tolerance:g}"
                        ),
                        use_container_width=True,
                    ):
                        st.session_state[
                            "soil_mir_predict_model_input"
                        ] = str(
                            model_path
                        )
                        st.session_state[
                            "soil_mir_predict_output_input"
                        ] = str(
                            Path(
                                output_dir
                            ).expanduser()
                        )
                        st.session_state[
                            "soil_mir_predict_selected_history_model"
                        ] = {
                            "run_id": manifest.get(
                                "run_id",
                                "",
                            ),
                            "property": property_name,
                            "method": method,
                            "path": str(
                                model_path
                            ),
                            "model_role": (
                                "final_only_refit"
                            ),
                            "refit_tolerance_pct": tolerance,
                        }
                        st.switch_page(
                            "pages/5_Predict.py"
                        )

        for result in manifest.get("results", []):
            artifacts = result.get("artifacts", {})
            property_name = result.get(
                "property",
                "property",
            )
            method = result.get(
                "method",
                "method",
            )
            if artifacts:
                method_label = (
                    validation_method_label(
                        method
                    )
                )
                st.markdown(
                    f"**{property_name} / {method_label} artifacts**"
                )
                st.code(
                    artifacts.get(
                        "directory",
                        "",
                    )
                )
                workbook = Path(
                    artifacts.get(
                        "workbook",
                        "",
                    )
                )
                model_path = Path(
                    artifacts.get(
                        "model",
                        "",
                    )
                )
                if workbook.is_file():
                    st.download_button(
                        f"Download {property_name} {method_label} workbook",
                        data=workbook.read_bytes(),
                        file_name=workbook.name,
                        mime=(
                            "application/vnd.openxmlformats-"
                            "officedocument.spreadsheetml.sheet"
                        ),
                        key=(
                            f"history_workbook_"
                            f"{manifest.get('run_id')}_"
                            f"{property_name}_{method}"
                        ),
                    )
                if model_path.is_file():
                    model_download_col, model_predict_col = st.columns(
                        2
                    )
                    with model_download_col:
                        st.download_button(
                            f"Download {property_name} {method_label} model",
                            data=model_path.read_bytes(),
                            file_name=model_path.name,
                            mime="application/octet-stream",
                            key=(
                                f"history_model_"
                                f"{manifest.get('run_id')}_"
                                f"{property_name}_{method}"
                            ),
                            use_container_width=True,
                        )
                    with model_predict_col:
                        if st.button(
                            f"Use {property_name} {method_label} in Predict",
                            key=(
                                f"history_predict_"
                                f"{manifest.get('run_id')}_"
                                f"{property_name}_{method}"
                            ),
                            use_container_width=True,
                        ):
                            st.session_state[
                                "soil_mir_predict_model_input"
                            ] = str(model_path)
                            st.session_state[
                                "soil_mir_predict_output_input"
                            ] = str(
                                Path(output_dir).expanduser()
                            )
                            st.session_state[
                                "soil_mir_predict_selected_history_model"
                            ] = {
                                "run_id": manifest.get(
                                    "run_id",
                                    "",
                                ),
                                "property": property_name,
                                "method": method,
                                "path": str(model_path),
                            }
                            st.switch_page(
                                "pages/5_Predict.py"
                            )
