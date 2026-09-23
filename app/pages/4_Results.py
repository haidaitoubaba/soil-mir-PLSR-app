from __future__ import annotations

import pandas as pd
import streamlit as st

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
        st.scatter_chart(
            predictions,
            x="Measured",
            y="Predicted",
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
