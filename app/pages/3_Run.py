from __future__ import annotations

import time

import streamlit as st

from soil_mir.services.calibration import (
    load_calibration_dataset,
    run_calibration,
)

st.set_page_config(
    page_title="Run | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Run")
st.caption(
    "Current milestone: final calibration search with "
    "internal CV. Outer validation is not yet wired."
)

required = [
    "soil_mir_spectra_dir",
    "soil_mir_reference_excel",
    "soil_mir_selected_properties",
    "soil_mir_validation_methods",
]
missing = [
    key
    for key in required
    if not st.session_state.get(key)
]
if missing:
    st.warning(
        "Complete Data inspection and save Configuration first."
    )
    st.stop()

properties = st.session_state[
    "soil_mir_selected_properties"
]
methods = st.session_state[
    "soil_mir_validation_methods"
]

st.write(
    f"Properties: **{', '.join(properties)}**"
)
st.write(
    f"Model context(s): **{', '.join(methods)}**"
)
st.info(
    "Scores shown after this run are internal calibration "
    "CV scores used for model selection, not independent "
    "held-out validation performance."
)

internal_cv_folds = st.number_input(
    "Internal CV folds",
    min_value=2,
    max_value=20,
    value=int(
        st.session_state.get(
            "soil_mir_internal_cv_folds",
            10,
        )
    ),
    step=1,
)

if st.button(
    "Run calibration search",
    type="primary",
):
    st.session_state[
        "soil_mir_internal_cv_folds"
    ] = int(internal_cv_folds)
    results = {}
    total = len(properties) * len(methods)
    completed = 0
    progress = st.progress(0.0)

    for property_sheet in properties:
        with st.status(
            f"Loading {property_sheet}",
            expanded=True,
        ) as status:
            dataset = load_calibration_dataset(
                st.session_state["soil_mir_spectra_dir"],
                st.session_state[
                    "soil_mir_reference_excel"
                ],
                property_sheet,
                wn_min=float(
                    st.session_state[
                        "soil_mir_wn_range"
                    ][0]
                ),
                wn_max=float(
                    st.session_state[
                        "soil_mir_wn_range"
                    ][1]
                ),
                fallback_exclude_co2=bool(
                    st.session_state.get(
                        "soil_mir_exclude_co2",
                        False,
                    )
                ),
            )
            st.write(
                f"Loaded {dataset.rows:,} spectra from "
                f"{dataset.unique_samples:,} samples."
            )

            for method in methods:
                started = time.time()
                st.write(
                    f"Optimizing {property_sheet} / {method}..."
                )
                result = run_calibration(
                    dataset,
                    method=method,
                    max_rank=int(
                        st.session_state[
                            "soil_mir_max_rank"
                        ]
                    ),
                    region_search_n_windows=int(
                        st.session_state[
                            "soil_mir_region_windows"
                        ]
                    ),
                    rmsecv_tolerance_pct=float(
                        st.session_state[
                            "soil_mir_tolerance"
                        ]
                    ),
                    sg_window=int(
                        st.session_state[
                            "soil_mir_sg_window"
                        ]
                    ),
                    sg_polyorder=int(
                        st.session_state[
                            "soil_mir_sg_polyorder"
                        ]
                    ),
                    random_seed=int(
                        st.session_state[
                            "soil_mir_random_seed"
                        ]
                    ),
                    internal_cv_folds=int(
                        internal_cv_folds
                    ),
                    wn_min=float(
                        st.session_state[
                            "soil_mir_wn_range"
                        ][0]
                    ),
                    wn_max=float(
                        st.session_state[
                            "soil_mir_wn_range"
                        ][1]
                    ),
                )
                result["elapsed_seconds"] = (
                    time.time() - started
                )
                results[
                    f"{property_sheet}::{method}"
                ] = result
                completed += 1
                progress.progress(
                    completed / total
                )

            status.update(
                label=f"{property_sheet} complete",
                state="complete",
                expanded=False,
            )

    st.session_state["soil_mir_results"] = results
    st.success(
        "Calibration search completed. Open the Results page."
    )
