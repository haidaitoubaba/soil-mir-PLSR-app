from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.plotting import (
    measured_vs_predicted_figure,
    residual_distribution_figure,
    residual_figure,
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
            "Method": result["method"],
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
    with st.expander(
        f"{result['property']} — {result['method']}",
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
                    f"{result['method']}"
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
                f"{result['method']} residuals"
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
                    f"{result['method']} residual distribution"
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
