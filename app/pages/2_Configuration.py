from __future__ import annotations

import math

import streamlit as st

from soil_mir.config import (
    SpectralConfig,
    ValidationConfig,
)
from soil_mir.services.profiles import (
    list_profiles,
    load_profile,
    save_profile,
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

PROFILE_SESSION_KEYS = {
    "soil_mir_selected_properties",
    "soil_mir_wn_range",
    "soil_mir_exclude_co2",
    "soil_mir_max_rank",
    "soil_mir_validation_methods",
    "soil_mir_region_windows",
    "soil_mir_tolerance",
    "soil_mir_sg_window",
    "soil_mir_sg_polyorder",
    "soil_mir_random_seed",
    "soil_mir_internal_cv_folds",
    "soil_mir_outer_cv_folds",
    "soil_mir_n_repeats",
    "soil_mir_validation_fraction",
    "soil_mir_ks_representation",
    "soil_mir_ks_pca_variance",
    "soil_mir_reference_ranges",
}

output_dir = st.session_state.get(
    "soil_mir_output_dir",
    "",
)
if output_dir:
    with st.expander("Saved configuration profiles"):
        profiles = list_profiles(output_dir)
        if profiles:
            selected_profile = st.selectbox(
                "Profile",
                list(profiles),
            )
            if st.button(
                "Load selected profile",
                key="load_configuration_profile",
            ):
                try:
                    loaded = load_profile(
                        profiles[selected_profile]
                    )
                except Exception as exc:
                    st.error(str(exc))
                else:
                    allowed = {
                        key: value
                        for key, value in loaded.items()
                        if key in PROFILE_SESSION_KEYS
                    }
                    if "soil_mir_selected_properties" in allowed:
                        allowed[
                            "soil_mir_selected_properties"
                        ] = [
                            prop
                            for prop in allowed[
                                "soil_mir_selected_properties"
                            ]
                            if prop in available_properties
                        ]
                    if "soil_mir_wn_range" in allowed:
                        allowed["soil_mir_wn_range"] = tuple(
                            allowed["soil_mir_wn_range"]
                        )
                    st.session_state.update(allowed)
                    st.rerun()
        else:
            st.caption(
                "No saved profiles yet. Validate settings below, "
                "then save the configuration as a profile."
            )

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

saved_reference_ranges = st.session_state.get(
    "soil_mir_reference_ranges",
    {},
)
reference_range_inputs = {}
with st.expander("Reference-value filters (optional)"):
    st.caption(
        "Leave a field blank for no limit. "
        "Limits are applied separately to each property before validation."
    )
    for property_name in selected_properties:
        saved = saved_reference_ranges.get(
            property_name,
            {},
        )
        left_range, right_range = st.columns(2)
        with left_range:
            ref_min_text = st.text_input(
                f"{property_name} minimum",
                value=(
                    ""
                    if saved.get("min") is None
                    else str(saved.get("min"))
                ),
                key=f"ref_min_{property_name}",
            )
        with right_range:
            ref_max_text = st.text_input(
                f"{property_name} maximum",
                value=(
                    ""
                    if saved.get("max") is None
                    else str(saved.get("max"))
                ),
                key=f"ref_max_{property_name}",
            )
        reference_range_inputs[property_name] = {
            "min": ref_min_text,
            "max": ref_max_text,
        }


def parsed_reference_ranges() -> dict:
    parsed = {}
    for property_name, values in reference_range_inputs.items():
        bounds = {}
        for bound in ("min", "max"):
            text = str(values[bound]).strip()
            if not text:
                bounds[bound] = None
                continue
            try:
                value = float(text)
            except ValueError as exc:
                raise ValueError(
                    f"{property_name} {bound} must be numeric or blank."
                ) from exc
            if not math.isfinite(value):
                raise ValueError(
                    f"{property_name} {bound} must be finite or blank."
                )
            bounds[bound] = value

        if (
            bounds["min"] is not None
            and bounds["max"] is not None
            and bounds["min"] > bounds["max"]
        ):
            raise ValueError(
                f"{property_name} minimum must not exceed maximum."
            )
        parsed[property_name] = bounds
    return parsed


def current_values() -> dict:
    return {
    "soil_mir_selected_properties": selected_properties,
    "soil_mir_wn_range": tuple(wn_range),
    "soil_mir_exclude_co2": exclude_co2,
    "soil_mir_max_rank": int(max_rank),
    "soil_mir_validation_methods": validation_methods,
    "soil_mir_region_windows": int(region_windows),
    "soil_mir_tolerance": float(tolerance),
    "soil_mir_sg_window": int(sg_window),
    "soil_mir_sg_polyorder": int(sg_polyorder),
    "soil_mir_random_seed": int(random_seed),
    "soil_mir_internal_cv_folds": int(internal_cv_folds),
    "soil_mir_outer_cv_folds": int(outer_cv_folds),
    "soil_mir_n_repeats": int(n_repeats),
    "soil_mir_validation_fraction": float(validation_fraction),
    "soil_mir_ks_representation": ks_representation,
    "soil_mir_ks_pca_variance": float(ks_pca_variance),
    "soil_mir_reference_ranges": parsed_reference_ranges(),
    }


def validate_current_configuration() -> dict:
    spectral = SpectralConfig(
        wn_min=float(wn_range[0]),
        wn_max=float(wn_range[1]),
        exclude_co2=exclude_co2,
        sg_window=int(sg_window),
        sg_polyorder=int(sg_polyorder),
    )
    validation = ValidationConfig(
        methods=tuple(validation_methods),
        max_rank=int(max_rank),
        region_search_n_windows=int(region_windows),
        rmsecv_tolerance_pct=float(tolerance),
        random_seed=int(random_seed),
    )
    spectral.validate()
    validation.validate()

    if not selected_properties:
        raise ValueError("Select at least one property.")
    if not validation_methods:
        raise ValueError("Select at least one validation method.")
    if not 0 < float(validation_fraction) < 1:
        raise ValueError(
            "Holdout fraction must be between 0 and 1."
        )
    return current_values()


if st.button(
    "Validate and save configuration",
    type="primary",
):
    try:
        values = validate_current_configuration()
    except Exception as exc:
        st.error(str(exc))
    else:
        st.session_state.update(values)
        st.success(
            "Configuration is valid and saved for this session."
        )

if output_dir:
    st.subheader("Save profile")
    profile_name = st.text_input(
        "Profile name",
        value="",
        placeholder="e.g. STC-STN nested kfold",
    )
    if st.button(
        "Save current settings as profile",
        disabled=not profile_name.strip(),
    ):
        try:
            values = validate_current_configuration()
            path = save_profile(
                output_dir,
                profile_name,
                values,
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            st.session_state.update(values)
            st.success(
                f"Saved configuration profile: {path.name}"
            )
