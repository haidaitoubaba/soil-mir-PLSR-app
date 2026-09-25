from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.methods import (
    validation_method_label,
)

from soil_mir.plotting import (
    measured_vs_predicted_figure,
    residual_distribution_figure,
    residual_figure,
)
from soil_mir.regions import (
    build_tolerance_comparison,
)
from soil_mir.services.history import (
    load_run_config,
    run_config_session_values,
)
from soil_mir.services.local_paths import (
    open_local_folder,
)
from soil_mir.services.profiles import (
    profile_widget_updates,
)
from soil_mir.services.refit import (
    refit_saved_run_tolerance,
)

st.set_page_config(
    page_title="Results | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Results")
st.caption(
    "Outer validation results and final all-data model selection."
)

results = st.session_state.get(
    "soil_mir_results"
)
if not results:
    st.warning(
        "No validation run is available in this session."
    )
    st.stop()

last_run = st.session_state.get(
    "soil_mir_last_run_dir"
)
if last_run:
    st.success(
        f"Saved locally: {last_run}"
    )
    if st.button(
        "Open results folder",
        key="open_validation_results_folder",
        type="secondary",
    ):
        try:
            open_local_folder(
                last_run
            )
        except Exception as exc:
            st.error(
                f"Could not open results folder: {exc}"
            )
    comparison = st.session_state.get(
        "soil_mir_last_comparison"
    )
    if comparison:
        comparison_path = Path(comparison)
        if comparison_path.is_file():
            st.download_button(
                "Download validation comparison workbook",
                data=comparison_path.read_bytes(),
                file_name=comparison_path.name,
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
            )

summary_rows = []
for result in results.values():
    summary = result["summary"].set_index(
        "Metric"
    )
    final_settings = result[
        "final_settings"
    ]
    summary_rows.append(
        {
            "Property": result["property"],
            "Method": validation_method_label(
                result["method"]
            ),
            "R²": float(
                summary.loc["R2", "Value"]
            ),
            "RMSE": float(
                summary.loc["RMSE", "Value"]
            ),
            "RPIQ": float(
                summary.loc["RPIQ", "Value"]
            ),
            "Bias": float(
                summary.loc["Bias", "Value"]
            ),
            "Final preprocessing": (
                final_settings[
                    "Preprocessing"
                ]
            ),
            "Final region": (
                final_settings["Region"]
            ),
            "Final rank": int(
                final_settings["Rank"]
            ),
            "Validation samples": int(
                result[
                    "unique_validation_samples"
                ]
            ),
            "Elapsed (s)": round(
                float(
                    result["elapsed_seconds"]
                ),
                1,
            ),
        }
    )

st.subheader("Validation comparison")
st.dataframe(
    pd.DataFrame(summary_rows),
    use_container_width=True,
    hide_index=True,
)

st.info(
    "Validation metrics come from outer predictions. "
    "Final model settings are selected separately on "
    "all eligible data and are not themselves a held-out score."
)

for result in results.values():
    method_label = validation_method_label(
        result["method"]
    )
    with st.expander(
        f"{result['property']} — {method_label}",
        expanded=True,
    ):
        summary = result["summary"].set_index(
            "Metric"
        )
        a, b, c, d = st.columns(4)
        a.metric(
            "R²",
            f"{summary.loc['R2', 'Value']:.3f}",
        )
        b.metric(
            "RMSE",
            f"{summary.loc['RMSE', 'Value']:.4g}",
        )
        c.metric(
            "RPIQ",
            f"{summary.loc['RPIQ', 'Value']:.3f}",
        )
        d.metric(
            "Bias",
            f"{summary.loc['Bias', 'Value']:.4g}",
        )

        final_settings = result[
            "final_settings"
        ]
        st.write(
            "**Final model:** "
            f"{final_settings['Preprocessing']} | "
            f"{final_settings['Region']} | "
            f"rank {int(final_settings['Rank'])}"
        )
        split_info = result.get(
            "split_info",
            {},
        )
        if "group_stratification_used" in split_info:
            requested_text = (
                "Required"
                if result["method"] == "logo"
                else (
                    "Yes"
                    if split_info.get(
                        "group_stratification_requested",
                        False,
                    )
                    else "No"
                )
            )
            used_text = (
                "Yes"
                if split_info.get(
                    "group_stratification_used",
                    False,
                )
                else "No"
            )
            st.caption(
                "Group stratification requested: "
                f"**{requested_text}** · used: "
                f"**{used_text}**"
            )

        tolerance_comparison = result.get(
            "tolerance_comparison"
        )
        if tolerance_comparison is None:
            configured_tolerance = float(
                result.get(
                    "config",
                    {},
                ).get(
                    "rmsecv_tolerance_pct",
                    0.0,
                )
            )
            tolerance_comparison = build_tolerance_comparison(
                result["final_search"],
                configured_tolerance,
            )
            result[
                "tolerance_comparison"
            ] = tolerance_comparison

        st.subheader(
            "Tolerance comparison (0–10%)"
        )
        st.caption(
            "Each row re-applies an integer RMSECV tolerance to the same "
            "completed final calibration search. This compares final-model "
            "selection sensitivity; it does not rerun outer validation."
        )
        st.dataframe(
            tolerance_comparison,
            use_container_width=True,
            hide_index=True,
        )

        tolerance_options = [
            int(value)
            for value in tolerance_comparison[
                "Tolerance (%)"
            ].tolist()
        ]
        source_tolerance = float(
            result.get(
                "config",
                {},
            ).get(
                "rmsecv_tolerance_pct",
                0.0,
            )
        )
        default_tolerance = (
            int(source_tolerance)
            if (
                float(source_tolerance).is_integer()
                and int(source_tolerance)
                in tolerance_options
            )
            else tolerance_options[0]
        )
        result_key = (
            f"{result['property']}::"
            f"{result['method']}"
        )
        selected_tolerance = st.selectbox(
            "Tolerance to use",
            tolerance_options,
            index=tolerance_options.index(
                default_tolerance
            ),
            format_func=lambda value: (
                f"{value}%"
            ),
            key=(
                "tolerance_choice_"
                f"{result_key}"
            ),
            help=(
                "Choose one of the 0–10% sensitivity rows above. "
                "This does not change the original saved validation run."
            ),
        )

        use_col, refit_col = st.columns(2)
        with use_col:
            if st.button(
                "Use this tolerance in Configuration",
                key=(
                    "use_tolerance_"
                    f"{result_key}"
                ),
                use_container_width=True,
                disabled=not bool(
                    last_run
                ),
            ):
                try:
                    source_config = (
                        load_run_config(
                            last_run
                        )
                    )
                    session_values = (
                        run_config_session_values(
                            source_config,
                            run_dir=last_run,
                        )
                    )
                    session_values[
                        "soil_mir_tolerance"
                    ] = float(
                        selected_tolerance
                    )
                    widget_values = (
                        profile_widget_updates(
                            session_values,
                            session_values.get(
                                "soil_mir_selected_properties",
                                [],
                            ),
                        )
                    )
                    widget_values[
                        "cfg_tolerance"
                    ] = float(
                        selected_tolerance
                    )
                    st.session_state.update(
                        session_values
                    )
                    st.session_state.update(
                        widget_values
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
                except Exception as exc:
                    st.error(
                        "Could not load the source run configuration."
                    )
                    st.exception(exc)
                else:
                    st.success(
                        f"Configuration now uses {selected_tolerance}% tolerance "
                        "with the source run's other settings. "
                        "Preflight must be run again before a full validation rerun."
                    )

        refit_state_key = (
            "soil_mir_final_refit_"
            f"{result_key}_"
            f"{selected_tolerance}"
        )
        with refit_col:
            if st.button(
                "Refit final model only",
                key=(
                    "refit_tolerance_"
                    f"{result_key}"
                ),
                type="primary",
                use_container_width=True,
                disabled=not bool(
                    last_run
                ),
                help=(
                    "Re-run only the final all-data calibration search/refit "
                    "at the selected tolerance. Outer validation is not rerun."
                ),
            ):
                try:
                    with st.status(
                        (
                            f"Refitting {result['property']} / "
                            f"{method_label} at "
                            f"{selected_tolerance}%"
                        ),
                        expanded=True,
                    ) as refit_status:
                        st.write(
                            "Reloading the source run's calibration data and settings..."
                        )
                        refit = (
                            refit_saved_run_tolerance(
                                last_run,
                                property_name=(
                                    result[
                                        "property"
                                    ]
                                ),
                                method=result[
                                    "method"
                                ],
                                tolerance_pct=float(
                                    selected_tolerance
                                ),
                            )
                        )
                        refit_status.update(
                            label=(
                                "Final-only refit complete"
                            ),
                            state="complete",
                            expanded=False,
                        )
                    st.session_state[
                        refit_state_key
                    ] = {
                        "property": refit[
                            "property"
                        ],
                        "method": refit[
                            "method"
                        ],
                        "tolerance": refit[
                            "refit_tolerance_pct"
                        ],
                        "source_tolerance": refit[
                            "source_validation_tolerance_pct"
                        ],
                        "final_settings": dict(
                            refit[
                                "final_settings"
                            ]
                        ),
                        "artifacts": dict(
                            refit[
                                "artifacts"
                            ]
                        ),
                        "source_run_dir": refit[
                            "source_run_dir"
                        ],
                    }
                except Exception as exc:
                    st.error(
                        "Final-only refit failed."
                    )
                    st.exception(exc)

        st.caption(
            "A final-only refit does not replace the outer-validation metrics "
            f"shown above. Those metrics remain from the original "
            f"{source_tolerance:g}% validation run."
        )

        refit_state = st.session_state.get(
            refit_state_key
        )
        if refit_state:
            refit_settings = refit_state[
                "final_settings"
            ]
            refit_artifacts = refit_state[
                "artifacts"
            ]
            st.success(
                (
                    f"Saved {refit_state['tolerance']:g}% final-only refit: "
                    f"{refit_settings['Preprocessing']} | "
                    f"{refit_settings['Region']} | "
                    f"rank {int(refit_settings['Rank'])}"
                )
            )
            st.code(
                refit_artifacts[
                    "directory"
                ]
            )
            refit_model = Path(
                refit_artifacts["model"]
            )
            refit_workbook = Path(
                refit_artifacts[
                    "workbook"
                ]
            )
            download_model_col, download_search_col, predict_col = (
                st.columns(3)
            )
            with download_model_col:
                if refit_model.is_file():
                    st.download_button(
                        "Download refit model",
                        data=refit_model.read_bytes(),
                        file_name=(
                            refit_model.name
                        ),
                        mime=(
                            "application/octet-stream"
                        ),
                        key=(
                            "download_refit_model_"
                            f"{result_key}_"
                            f"{selected_tolerance}"
                        ),
                        use_container_width=True,
                    )
            with download_search_col:
                if refit_workbook.is_file():
                    st.download_button(
                        "Download refit selection",
                        data=(
                            refit_workbook.read_bytes()
                        ),
                        file_name=(
                            refit_workbook.name
                        ),
                        mime=(
                            "application/vnd.openxmlformats-"
                            "officedocument.spreadsheetml.sheet"
                        ),
                        key=(
                            "download_refit_search_"
                            f"{result_key}_"
                            f"{selected_tolerance}"
                        ),
                        use_container_width=True,
                    )
            with predict_col:
                if (
                    refit_model.is_file()
                    and st.button(
                        "Use refit model in Predict",
                        key=(
                            "predict_refit_"
                            f"{result_key}_"
                            f"{selected_tolerance}"
                        ),
                        use_container_width=True,
                    )
                ):
                    st.session_state[
                        "soil_mir_predict_model_input"
                    ] = str(
                        refit_model
                    )
                    st.session_state[
                        "soil_mir_predict_selected_history_model"
                    ] = {
                        "run_id": Path(
                            refit_state[
                                "source_run_dir"
                            ]
                        ).name,
                        "property": result[
                            "property"
                        ],
                        "method": result[
                            "method"
                        ],
                        "path": str(
                            refit_model
                        ),
                        "model_role": (
                            "final_only_refit"
                        ),
                        "refit_tolerance_pct": float(
                            selected_tolerance
                        ),
                    }
                    st.switch_page(
                        "pages/5_Predict.py"
                    )

        predictions = result[
            "predictions"
        ][
            [
                "Measured",
                "Predicted",
            ]
        ]
        st.subheader(
            "Measured vs predicted"
        )
        measured_plot = (
            measured_vs_predicted_figure(
                predictions["Measured"],
                predictions["Predicted"],
                title=(
                    f"{result['property']} — "
                    f"{method_label}"
                ),
                predicted_label=(
                    "Validation predicted"
                ),
            )
        )
        st.pyplot(
            measured_plot,
            clear_figure=True,
            use_container_width=False,
        )

        residuals = result["predictions"][
            ["Predicted", "Residual"]
        ]
        st.subheader("Residuals")
        residual_plot = residual_figure(
            residuals["Predicted"],
            residuals["Residual"],
            title=(
                f"{result['property']} — "
                f"{method_label} residuals"
            ),
            predicted_label=(
                "Validation predicted"
            ),
        )
        st.pyplot(
            residual_plot,
            clear_figure=True,
            use_container_width=False,
        )

        st.subheader(
            "Residual distribution"
        )
        residual_histogram = (
            residual_distribution_figure(
                residuals["Residual"],
                title=(
                    f"{result['property']} — "
                    f"{method_label} residual distribution"
                ),
            )
        )
        st.pyplot(
            residual_histogram,
            clear_figure=True,
            use_container_width=False,
        )

        final_search = result["final_search"]
        selected_path = final_search[
            (final_search["Region"] == final_settings["Region"])
            & (
                final_search["Preprocessing"]
                == final_settings["Preprocessing"]
            )
            & (final_search["Status"] == "Success")
        ][["Rank", "RMSECV"]].sort_values("Rank")
        if not selected_path.empty:
            st.subheader("Selected model rank path")
            st.line_chart(
                selected_path,
                x="Rank",
                y="RMSECV",
            )

        folds = result["folds"]
        if (
            "Validation RMSE" in folds.columns
            and folds["Validation RMSE"].notna().any()
        ):
            st.subheader("Outer-split RMSE")
            st.bar_chart(
                folds,
                x="Outer Split",
                y="Validation RMSE",
            )

        st.subheader(
            "Saved artifacts"
        )
        artifacts = result.get(
            "artifacts",
            {},
        )
        if artifacts:
            st.code(
                artifacts["directory"]
            )
            workbook = Path(
                artifacts["workbook"]
            )
            model = Path(
                artifacts["model"]
            )
            plots_pdf = Path(
                artifacts.get("plots_pdf", "")
            )
            metadata = Path(
                artifacts.get("metadata", "")
            )
            if workbook.is_file():
                st.download_button(
                    "Download results workbook",
                    data=workbook.read_bytes(),
                    file_name=workbook.name,
                    mime=(
                        "application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet"
                    ),
                    key=(
                        f"workbook_{result['property']}_"
                        f"{result['method']}"
                    ),
                )
            if model.is_file():
                st.download_button(
                    "Download final model",
                    data=model.read_bytes(),
                    file_name=model.name,
                    mime="application/octet-stream",
                    key=(
                        f"model_{result['property']}_"
                        f"{result['method']}"
                    ),
                )
            if plots_pdf.is_file():
                st.download_button(
                    "Download validation plots PDF",
                    data=plots_pdf.read_bytes(),
                    file_name=plots_pdf.name,
                    mime="application/pdf",
                    key=(
                        f"plots_{result['property']}_"
                        f"{result['method']}"
                    ),
                )
            if metadata.is_file():
                st.download_button(
                    "Download model metadata",
                    data=metadata.read_bytes(),
                    file_name=metadata.name,
                    mime="application/json",
                    key=(
                        f"metadata_{result['property']}_"
                        f"{result['method']}"
                    ),
                )

        st.subheader(
            "Validation summary"
        )
        st.dataframe(
            result["summary"],
            use_container_width=True,
            hide_index=True,
        )

        st.subheader(
            "Outer split details"
        )
        st.dataframe(
            result["folds"],
            use_container_width=True,
            hide_index=True,
        )

        st.subheader(
            "Validation predictions"
        )
        st.dataframe(
            result["predictions"],
            use_container_width=True,
            hide_index=True,
        )

        with st.expander(
            "Final calibration search"
        ):
            st.dataframe(
                result["final_search"],
                use_container_width=True,
                hide_index=True,
            )
