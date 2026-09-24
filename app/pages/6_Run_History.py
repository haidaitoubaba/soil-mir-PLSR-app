from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.reporting import list_run_history
from soil_mir.services.history import (
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
                manifest.get("methods", [])
            ),
            "Completed analyses": len(results),
            "Pending analyses": len(
                pending_run_keys(
                    manifest
                )
            ),
            "Failed analyses": len(manifest.get("failures", [])),
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

        pending = pending_run_keys(
            manifest
        )
        if pending:
            st.write(
                "**Pending analyses:** "
                + ", ".join(
                    sorted(pending)
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
                    "Method": result.get("method", ""),
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
                st.markdown(
                    f"**{property_name} / {method} artifacts**"
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
                        f"Download {property_name} {method} workbook",
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
                            f"Download {property_name} {method} model",
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
                            f"Use {property_name} {method} in Predict",
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
