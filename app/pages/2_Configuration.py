from __future__ import annotations

import streamlit as st

from soil_mir.config import (
    SpectralConfig,
    ValidationConfig,
)

st.set_page_config(
    page_title="Configure | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Configuration")
st.caption(
    "Choose modelling and validation settings. "
    "Property metadata remains property-specific."
)

available_properties = st.session_state.get(
    "soil_mir_properties",
    [],
)
if not available_properties:
    st.warning(
        "Inspect a spectra folder and reference workbook "
        "on the Data page first."
    )
    st.stop()

default_properties = [
    prop
    for prop in (
        "202_STC",
        "202_STN",
    )
    if prop in available_properties
] or available_properties[:1]

selected_properties = st.multiselect(
    "Properties",
    available_properties,
    default=st.session_state.get(
        "soil_mir_selected_properties",
        default_properties,
    ),
)

st.subheader("Basic settings")
left, right = st.columns(2)

with left:
    wn_range = st.slider(
        "Spectral range (cm⁻¹)",
        min_value=400,
        max_value=4000,
        value=st.session_state.get(
            "soil_mir_wn_range",
            (600, 4000),
        ),
        step=25,
    )
    exclude_co2 = st.checkbox(
        "Exclude CO₂ region (2300–2400 cm⁻¹)",
        value=st.session_state.get(
            "soil_mir_exclude_co2",
            False,
        ),
        help=(
            "Property Metadata takes precedence when "
            "a property-specific setting is available."
        ),
    )
    max_rank = st.number_input(
        "Maximum PLS rank",
        min_value=1,
        max_value=50,
        value=st.session_state.get(
            "soil_mir_max_rank",
            15,
        ),
        step=1,
    )

with right:
    validation_methods = st.multiselect(
        "Validation methods",
        [
            "kfold",
            "monte_carlo",
            "loso",
            "logo",
            "kennard_stone",
        ],
        default=st.session_state.get(
            "soil_mir_validation_methods",
            ["kfold"],
        ),
    )
    region_windows = st.number_input(
        "Region search windows",
        min_value=1,
        max_value=16,
        value=st.session_state.get(
            "soil_mir_region_windows",
            7,
        ),
        step=1,
        help=(
            "Backward search cost grows quickly as "
            "the number of windows increases."
        ),
    )
    tolerance = st.number_input(
        "RMSECV tolerance (%)",
        min_value=0.0,
        value=float(
            st.session_state.get(
                "soil_mir_tolerance",
                5.0,
            )
        ),
        step=0.5,
    )

st.subheader("Validation settings")
validation_left, validation_right = st.columns(2)

with validation_left:
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
    outer_cv_folds = st.number_input(
        "Outer K-fold folds",
        min_value=2,
        max_value=20,
        value=int(
            st.session_state.get(
                "soil_mir_outer_cv_folds",
                5,
            )
        ),
        step=1,
        disabled=(
            "kfold"
            not in validation_methods
        ),
    )
    n_repeats = st.number_input(
        "Monte Carlo repeats",
        min_value=1,
        max_value=500,
        value=int(
            st.session_state.get(
                "soil_mir_n_repeats",
                30,
            )
        ),
        step=1,
        disabled=(
            "monte_carlo"
            not in validation_methods
        ),
    )

with validation_right:
    validation_fraction = st.number_input(
        "Holdout fraction",
        min_value=0.05,
        max_value=0.95,
        value=float(
            st.session_state.get(
                "soil_mir_validation_fraction",
                0.20,
            )
        ),
        step=0.05,
        disabled=(
            not any(
                method in validation_methods
                for method in (
                    "monte_carlo",
                    "kennard_stone",
                )
            )
        ),
    )
    ks_representation = st.selectbox(
        "Kennard–Stone representation",
        [
            "raw",
            "derivative_snv",
            "pca",
        ],
        index=[
            "raw",
            "derivative_snv",
            "pca",
        ].index(
            st.session_state.get(
                "soil_mir_ks_representation",
                "raw",
            )
        ),
        disabled=(
            "kennard_stone"
            not in validation_methods
        ),
    )
    ks_pca_variance = st.number_input(
        "KS PCA retained variance",
        min_value=0.50,
        max_value=0.999,
        value=float(
            st.session_state.get(
                "soil_mir_ks_pca_variance",
                0.99,
            )
        ),
        step=0.01,
        disabled=(
            "kennard_stone"
            not in validation_methods
            or ks_representation != "pca"
        ),
    )

with st.expander("Advanced spectral settings"):
    sg_window = st.number_input(
        "Savitzky–Golay window",
        min_value=3,
        value=st.session_state.get(
            "soil_mir_sg_window",
            11,
        ),
        step=2,
    )
    sg_polyorder = st.number_input(
        "Savitzky–Golay polynomial order",
        min_value=0,
        value=st.session_state.get(
            "soil_mir_sg_polyorder",
            2,
        ),
        step=1,
    )
    random_seed = st.number_input(
        "Random seed",
        min_value=0,
        value=st.session_state.get(
            "soil_mir_random_seed",
            42,
        ),
        step=1,
    )

if st.button(
    "Validate and save configuration",
    type="primary",
):
    try:
        spectral = SpectralConfig(
            wn_min=float(wn_range[0]),
            wn_max=float(wn_range[1]),
            exclude_co2=exclude_co2,
            sg_window=int(sg_window),
            sg_polyorder=int(sg_polyorder),
        )
        validation = ValidationConfig(
            methods=tuple(
                validation_methods
            ),
            max_rank=int(max_rank),
            region_search_n_windows=int(
                region_windows
            ),
            rmsecv_tolerance_pct=float(
                tolerance
            ),
            random_seed=int(
                random_seed
            ),
        )
        spectral.validate()
        validation.validate()

        if not selected_properties:
            raise ValueError(
                "Select at least one property."
            )
        if not validation_methods:
            raise ValueError(
                "Select at least one validation method."
            )
        if not 0 < float(
            validation_fraction
        ) < 1:
            raise ValueError(
                "Holdout fraction must be between 0 and 1."
            )
    except Exception as exc:
        st.error(str(exc))
    else:
        values = {
            "soil_mir_selected_properties": (
                selected_properties
            ),
            "soil_mir_wn_range": tuple(
                wn_range
            ),
            "soil_mir_exclude_co2": (
                exclude_co2
            ),
            "soil_mir_max_rank": int(
                max_rank
            ),
            "soil_mir_validation_methods": (
                validation_methods
            ),
            "soil_mir_region_windows": int(
                region_windows
            ),
            "soil_mir_tolerance": float(
                tolerance
            ),
            "soil_mir_sg_window": int(
                sg_window
            ),
            "soil_mir_sg_polyorder": int(
                sg_polyorder
            ),
            "soil_mir_random_seed": int(
                random_seed
            ),
            "soil_mir_internal_cv_folds": int(
                internal_cv_folds
            ),
            "soil_mir_outer_cv_folds": int(
                outer_cv_folds
            ),
            "soil_mir_n_repeats": int(
                n_repeats
            ),
            "soil_mir_validation_fraction": float(
                validation_fraction
            ),
            "soil_mir_ks_representation": (
                ks_representation
            ),
            "soil_mir_ks_pca_variance": float(
                ks_pca_variance
            ),
        }
        st.session_state.update(
            values
        )
        st.success(
            "Configuration is valid and saved "
            "for this session."
        )
