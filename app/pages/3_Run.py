from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.reporting import (
    create_run_directory,
    export_validation_comparison,
    export_validation_result,
    finalize_run_manifest,
    initialize_run_manifest,
    record_run_result,
    write_json,
)
from soil_mir.services.calibration import (
    load_calibration_dataset,
    preflight_validation_methods,
    run_validation_analysis,
)


st.set_page_config(
    page_title="Run | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Run")
st.caption(
    "Pre-run data checks, nested model selection, and outer validation."
)

required = [
    "soil_mir_spectra_dir",
    "soil_mir_reference_excel",
    "soil_mir_output_dir",
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
        "Complete Data inspection and save Configuration first."
    )
    st.stop()

properties = list(
    st.session_state["soil_mir_selected_properties"]
)
methods = list(
    st.session_state["soil_mir_validation_methods"]
)


def analysis_settings() -> dict:
    return {
        "max_rank": int(
            st.session_state["soil_mir_max_rank"]
        ),
        "region_search_n_windows": int(
            st.session_state["soil_mir_region_windows"]
        ),
        "rmsecv_tolerance_pct": float(
            st.session_state["soil_mir_tolerance"]
        ),
        "sg_window": int(
            st.session_state["soil_mir_sg_window"]
        ),
        "sg_polyorder": int(
            st.session_state["soil_mir_sg_polyorder"]
        ),
        "random_seed": int(
            st.session_state["soil_mir_random_seed"]
        ),
        "internal_cv_folds": int(
            st.session_state["soil_mir_internal_cv_folds"]
        ),
        "outer_cv_folds": int(
            st.session_state.get(
                "soil_mir_outer_cv_folds",
                5,
            )
        ),
        "n_repeats": int(
            st.session_state.get(
                "soil_mir_n_repeats",
                30,
            )
        ),
        "validation_fraction": float(
            st.session_state.get(
                "soil_mir_validation_fraction",
                0.20,
            )
        ),
        "ks_representation": str(
            st.session_state.get(
                "soil_mir_ks_representation",
                "raw",
            )
        ),
        "ks_pca_variance": float(
            st.session_state.get(
                "soil_mir_ks_pca_variance",
                0.99,
            )
        ),
        "wn_min": float(
            st.session_state["soil_mir_wn_range"][0]
        ),
        "wn_max": float(
            st.session_state["soil_mir_wn_range"][1]
        ),
    }


settings = analysis_settings()
cache_root = (
    Path(st.session_state["soil_mir_output_dir"])
    / ".soil_mir_cache"
)

st.write(
    f"Properties: **{', '.join(properties)}**"
)
st.write(
    f"Validation methods: **{', '.join(methods)}**"
)
st.write(
    "Results directory: "
    f"{st.session_state['soil_mir_output_dir']}"
)
st.info(
    "One click first performs real-data preflight checks. "
    "Only if every selected property/method is feasible does the nested validation start."
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
    datasets = {}
    preflight_frames = []

    try:
        with st.status(
            "Pre-run validation",
            expanded=True,
        ) as preflight_status:
            for property_sheet in properties:
                st.write(
                    f"Reading and validating {property_sheet}..."
                )
                dataset = load_calibration_dataset(
                    st.session_state["soil_mir_spectra_dir"],
                    st.session_state["soil_mir_reference_excel"],
                    property_sheet,
                    wn_min=settings["wn_min"],
                    wn_max=settings["wn_max"],
                    fallback_exclude_co2=bool(
                        st.session_state.get(
                            "soil_mir_exclude_co2",
                            False,
                        )
                    ),
                    cache_root=cache_root,
                )
                datasets[property_sheet] = dataset
                st.write(
                    f"{property_sheet}: {dataset.rows:,} spectra, "
                    f"{dataset.unique_samples:,} samples; "
                    f"cache {dataset.cache_hits} reused / "
                    f"{dataset.cache_misses} parsed."
                )

                preflight_frames.append(
                    preflight_validation_methods(
                        dataset,
                        methods=methods,
                        **settings,
                    )
                )

            preflight = pd.concat(
                preflight_frames,
                ignore_index=True,
            )
            st.dataframe(
                preflight,
                use_container_width=True,
                hide_index=True,
            )

            failures = preflight[
                preflight["Status"] != "Pass"
            ]
            if not failures.empty:
                preflight_status.update(
                    label="Pre-run validation failed",
                    state="error",
                    expanded=True,
                )
                st.error(
                    "The analysis did not start because one or more "
                    "validation designs are not feasible."
                )
                st.stop()

            preflight_status.update(
                label="Pre-run validation passed",
                state="complete",
                expanded=False,
            )
    except Exception as exc:
        st.error(
            "The analysis did not start because input validation failed."
        )
        st.exception(exc)
        st.stop()

    run_dir = create_run_directory(
        st.session_state["soil_mir_output_dir"]
    )
    initialize_run_manifest(
        run_dir,
        properties=properties,
        methods=methods,
        spectra_dir=st.session_state["soil_mir_spectra_dir"],
        reference_excel=st.session_state["soil_mir_reference_excel"],
    )
    write_json(
        run_dir / "Run_Config.json",
        {
            "properties": properties,
            "methods": methods,
            "spectra_dir": st.session_state["soil_mir_spectra_dir"],
            "reference_excel": st.session_state["soil_mir_reference_excel"],
            "output_dir": st.session_state["soil_mir_output_dir"],
            "analysis_settings": settings,
        },
    )

    results = {}
    total = len(properties) * len(methods)
    completed = 0
    progress = st.progress(0.0)
    progress_note = st.empty()

    try:
        for property_sheet in properties:
            dataset = datasets[property_sheet]
            with st.status(
                f"Running {property_sheet}",
                expanded=True,
            ) as status:
                for method in methods:
                    st.write(
                        f"Running {property_sheet} / {method}..."
                    )

                    def method_progress(
                        step,
                        step_total,
                        message,
                        property_name=property_sheet,
                        method_name=method,
                    ):
                        within = (
                            step / step_total
                            if step_total
                            else 0.0
                        )
                        progress.progress(
                            min(
                                (completed + within) / total,
                                1.0,
                            )
                        )
                        progress_note.caption(
                            f"{property_name} / {method_name}: {message}"
                        )

                    result = run_validation_analysis(
                        dataset,
                        method=method,
                        **settings,
                        progress_callback=method_progress,
                    )
                    result["artifacts"] = (
                        export_validation_result(
                            result,
                            run_dir,
                        )
                    )
                    record_run_result(
                        run_dir,
                        result,
                        result["artifacts"],
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
    except Exception as exc:
        finalize_run_manifest(
            run_dir,
            status="failed",
            error=str(exc),
        )
        progress_note.caption(
            "Run failed. Completed analyses were preserved."
        )
        st.exception(exc)
        st.stop()

    comparison_path = export_validation_comparison(
        results,
        run_dir,
    )
    finalize_run_manifest(
        run_dir,
        status="completed",
    )
    progress.progress(1.0)
    progress_note.caption("Run complete.")

    st.session_state["soil_mir_results"] = results
    st.session_state["soil_mir_last_run_dir"] = str(
        run_dir
    )
    st.session_state["soil_mir_last_comparison"] = comparison_path
    st.success(
        "Validation completed and saved to "
        f"{run_dir}. Open the Results page."
    )
