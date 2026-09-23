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
    "Internal calibration-search results. "
    "Independent outer validation will be added next."
)

results = st.session_state.get("soil_mir_results")
if not results:
    st.warning(
        "No calibration run is available in this session."
    )
    st.stop()

summary_rows = []
for key, result in results.items():
    best = result["best"]
    summary_rows.append(
        {
            "Property": result["property"],
            "Context": result["method"],
            "Preprocessing": best["Preprocessing"],
            "Region": best["Region"],
            "Rank": int(best["Rank"]),
            "RMSECV": float(best["RMSECV"]),
            "R² CV": float(best["R2_CV"]),
            "RPIQ CV": float(best["RPIQ_CV"]),
            "Bias CV": float(best["Bias_CV"]),
            "Tolerance (%)": float(
                best["Tolerance (%)"]
            ),
            "Elapsed (s)": round(
                float(
                    result.get(
                        "elapsed_seconds",
                        0.0,
                    )
                ),
                1,
            ),
        }
    )

st.subheader("Calibration selection summary")
st.dataframe(
    pd.DataFrame(summary_rows),
    use_container_width=True,
    hide_index=True,
)

st.warning(
    "These are internal CV model-selection metrics. "
    "Do not interpret them as independent external "
    "validation performance."
)

for key, result in results.items():
    best = result["best"]
    with st.expander(
        f"{result['property']} — {result['method']}",
        expanded=True,
    ):
        a, b, c, d = st.columns(4)
        a.metric("RMSECV", f"{best['RMSECV']:.4g}")
        b.metric("R² CV", f"{best['R2_CV']:.3f}")
        c.metric("RPIQ CV", f"{best['RPIQ_CV']:.3f}")
        d.metric("Selected rank", int(best["Rank"]))

        st.write(
            f"**Preprocessing:** {best['Preprocessing']}"
        )
        st.write(
            f"**Region:** {best['Region']}"
        )
        st.write(
            "**Selected intervals:** "
            f"{result['bundle']['regions_label']}"
        )

        search = result["search"].copy()
        selected_first = search.sort_values(
            ["Selected", "RMSECV"],
            ascending=[False, True],
        )
        st.dataframe(
            selected_first,
            use_container_width=True,
            hide_index=True,
        )
