from __future__ import annotations

import streamlit as st

from soil_mir.services.calibration import (
    load_calibration_dataset,
    run_validation_analysis,
)

st.set_page_config(
    page_title="Run | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Run")
st.caption(
    "Nested model selection and outer validation."
)

required = [
    "soil_mir_spectra_dir",
    "soil_mir_reference_excel",
    "soil_mir_selected_properties",
    "soil_mir_validation_methods",
    "soil_mir_internal_cv_folds",
]
missing = [
    key
    for key in required
    if not st.session_state.get(key)
]
if missing:
    st.warning(
        "Complete Data inspection and save "
        "Configuration first."
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
    f"Validation methods: **{', '.join(methods)}**"
)
st.info(
    "Each outer split performs its own internal "
    "preprocessing/region/rank selection. "
    "The final model is refit separately using all "
    "eligible samples after validation."
)

if "loso" in methods:
    st.warning(
        "LOSO can be computationally expensive because "
        "it fits one nested model per sample."
    )
if "monte_carlo" in methods:
    st.warning(
        "Monte Carlo runtime grows with the number of repeats."
    )

if st.button(
    "Run validation",
    type="primary",
):
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
                st.session_state[
                    "soil_mir_spectra_dir"
                ],
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
            st.write(
                f"Transform: {dataset.transform}; "
                f"CO₂ excluded: {dataset.exclude_co2}"
            )

            for method in methods:
                st.write(
                    f"Running {property_sheet} / {method}..."
                )
                result = run_validation_analysis(
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
                        st.session_state[
                            "soil_mir_internal_cv_folds"
                        ]
                    ),
                    outer_cv_folds=int(
                        st.session_state.get(
                            "soil_mir_outer_cv_folds",
                            5,
                        )
                    ),
                    n_repeats=int(
                        st.session_state.get(
                            "soil_mir_n_repeats",
                            30,
                        )
                    ),
                    validation_fraction=float(
                        st.session_state.get(
                            "soil_mir_validation_fraction",
                            0.20,
                        )
                    ),
                    ks_representation=str(
                        st.session_state.get(
                            "soil_mir_ks_representation",
                            "raw",
                        )
                    ),
                    ks_pca_variance=float(
                        st.session_state.get(
                            "soil_mir_ks_pca_variance",
                            0.99,
                        )
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

    st.session_state[
        "soil_mir_results"
    ] = results
    st.success(
        "Validation completed. Open the Results page."
    )
