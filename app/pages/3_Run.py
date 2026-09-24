from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.reporting import (
    create_run_directory,
    export_validation_comparison,
    export_validation_result,
    finalize_run_manifest,
    initialize_run_manifest,
    record_run_failure,
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
    "Preflight first, then nested model selection and outer validation."
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
reference_ranges = st.session_state.get(
    "soil_mir_reference_ranges",
    {},
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
            st.session_state[
                "soil_mir_internal_cv_folds"
            ]
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
            st.session_state[
                "soil_mir_wn_range"
            ][0]
        ),
        "wn_max": float(
            st.session_state[
                "soil_mir_wn_range"
            ][1]
        ),
    }


settings = analysis_settings()
cache_root = (
    Path(
        st.session_state[
            "soil_mir_output_dir"
        ]
    )
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

if "loso" in methods:
    st.warning(
        "LOSO can be computationally expensive because "
        "it fits one nested model per sample."
    )
if "monte_carlo" in methods:
    st.warning(
        "Monte Carlo runtime grows with the number of repeats."
    )


preflight_payload = {
    "spectra_dir": st.session_state[
        "soil_mir_spectra_dir"
    ],
    "reference_excel": st.session_state[
        "soil_mir_reference_excel"
    ],
    "output_dir": st.session_state[
        "soil_mir_output_dir"
    ],
    "properties": properties,
    "methods": methods,
    "settings": settings,
    "reference_ranges": reference_ranges,
    "fallback_exclude_co2": bool(
        st.session_state.get(
            "soil_mir_exclude_co2",
            False,
        )
    ),
}
preflight_signature = json.dumps(
    preflight_payload,
    sort_keys=True,
    default=str,
)

if (
    st.session_state.get(
        "soil_mir_preflight_signature"
    )
    != preflight_signature
):
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

st.subheader("1. Preflight")
st.caption(
    "Preflight loads the selected real data, applies any reference-value "
    "filters, verifies spectral coverage, and checks whether every selected "
    "validation design is feasible. It does not fit the nested PLSR models."
)

preflight_exists = (
    st.session_state.get(
        "soil_mir_preflight_signature"
    )
    == preflight_signature
    and "soil_mir_preflight_table"
    in st.session_state
)

if st.button(
    (
        "Re-run preflight check"
        if preflight_exists
        else "Run preflight check"
    ),
    type="secondary",
):
    datasets = {}
    preflight_frames = []
    try:
        with st.status(
            "Running preflight",
            expanded=True,
        ) as preflight_status:
            for property_sheet in properties:
                st.write(
                    f"Reading and validating {property_sheet}..."
                )
                property_range = (
                    reference_ranges.get(
                        property_sheet,
                        {},
                    )
                )
                dataset = load_calibration_dataset(
                    st.session_state[
                        "soil_mir_spectra_dir"
                    ],
                    st.session_state[
                        "soil_mir_reference_excel"
                    ],
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
                    ref_min=property_range.get(
                        "min"
                    ),
                    ref_max=property_range.get(
                        "max"
                    ),
                )
                datasets[property_sheet] = dataset
                st.write(
                    f"{property_sheet}: "
                    f"{dataset.rows:,} spectra, "
                    f"{dataset.unique_samples:,} samples, "
                    f"{len(dataset.wavenumbers):,} retained spectral points; "
                    f"cache {dataset.cache_hits} reused / "
                    f"{dataset.cache_misses} parsed."
                )
                if (
                    dataset.endpoint_trimmed_points
                ):
                    st.write(
                        "Shared-grid alignment trimmed "
                        f"{dataset.endpoint_trimmed_points} "
                        "endpoint point(s) from the modal OPUS grid; "
                        "no extrapolation was used."
                    )
                if (
                    dataset.excluded_reference_rows
                ):
                    st.write(
                        "Reference filter excluded "
                        f"{dataset.excluded_reference_rows:,} rows from "
                        f"{dataset.excluded_reference_samples:,} samples."
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
            failures = preflight[
                preflight["Status"]
                != "Pass"
            ]
            passed = failures.empty

            st.session_state[
                "soil_mir_preflight_table"
            ] = preflight
            st.session_state[
                "soil_mir_preflight_datasets"
            ] = datasets
            st.session_state[
                "soil_mir_preflight_passed"
            ] = passed
            st.session_state[
                "soil_mir_preflight_signature"
            ] = preflight_signature

            preflight_status.update(
                label=(
                    "Preflight passed"
                    if passed
                    else "Preflight failed"
                ),
                state=(
                    "complete"
                    if passed
                    else "error"
                ),
                expanded=not passed,
            )
    except Exception as exc:
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
        st.error(
            "Preflight could not be completed."
        )
        st.exception(exc)

preflight_exists = (
    st.session_state.get(
        "soil_mir_preflight_signature"
    )
    == preflight_signature
    and "soil_mir_preflight_table"
    in st.session_state
)
preflight_passed = bool(
    st.session_state.get(
        "soil_mir_preflight_passed",
        False,
    )
)

if preflight_exists:
    st.dataframe(
        st.session_state[
            "soil_mir_preflight_table"
        ],
        use_container_width=True,
        hide_index=True,
    )
    if preflight_passed:
        st.success(
            "Preflight passed. Review the table above, then start validation."
        )
    else:
        st.error(
            "Preflight failed. Validation is blocked until every selected "
            "property/method combination passes."
        )
else:
    st.info(
        "Run the preflight check before starting validation."
    )

st.subheader("2. Validation")
st.caption(
    "Start validation only after preflight passes. Progress reports the "
    "current property, validation method, outer split, and final all-data refit."
)

start_validation = st.button(
    "Start validation",
    type="primary",
    disabled=not (
        preflight_exists
        and preflight_passed
    ),
)

if start_validation:
    datasets = st.session_state.get(
        "soil_mir_preflight_datasets",
        {},
    )
    if set(datasets) != set(properties):
        st.error(
            "Preflight data are no longer available. Re-run preflight."
        )
        st.stop()

    run_dir = create_run_directory(
        st.session_state[
            "soil_mir_output_dir"
        ]
    )
    initialize_run_manifest(
        run_dir,
        properties=properties,
        methods=methods,
        spectra_dir=st.session_state[
            "soil_mir_spectra_dir"
        ],
        reference_excel=st.session_state[
            "soil_mir_reference_excel"
        ],
    )
    write_json(
        run_dir / "Run_Config.json",
        {
            "properties": properties,
            "methods": methods,
            "spectra_dir": st.session_state[
                "soil_mir_spectra_dir"
            ],
            "reference_excel": (
                st.session_state[
                    "soil_mir_reference_excel"
                ]
            ),
            "output_dir": st.session_state[
                "soil_mir_output_dir"
            ],
            "analysis_settings": settings,
            "reference_ranges": (
                reference_ranges
            ),
        },
    )

    results = {}
    total = len(properties) * len(methods)
    completed = 0
    failed_count = 0
    progress = st.progress(0.0)
    progress_note = st.empty()

    for property_sheet in properties:
        dataset = datasets[property_sheet]
        property_failures = 0
        with st.status(
            f"Running {property_sheet}",
            expanded=True,
        ) as status:
            for method in methods:
                status.update(
                    label=(
                        f"{property_sheet} / {method}: "
                        "starting nested validation"
                    ),
                    state="running",
                    expanded=True,
                )
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
                            (
                                completed
                                + within
                            )
                            / total,
                            1.0,
                        )
                    )
                    detail = (
                        f"{property_name} / "
                        f"{method_name}: {message}"
                    )
                    progress_note.caption(
                        detail
                    )
                    status.update(
                        label=detail,
                        state="running",
                        expanded=True,
                    )

                try:
                    result = run_validation_analysis(
                        dataset,
                        method=method,
                        **settings,
                        progress_callback=(
                            method_progress
                        ),
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
                        result[
                            "artifacts"
                        ],
                    )
                    results[
                        f"{property_sheet}::{method}"
                    ] = result
                except Exception as exc:
                    failed_count += 1
                    property_failures += 1
                    record_run_failure(
                        run_dir,
                        property_name=(
                            property_sheet
                        ),
                        method=method,
                        error=str(exc),
                    )
                    st.error(
                        f"{property_sheet} / "
                        f"{method} failed: {exc}"
                    )
                finally:
                    completed += 1
                    progress.progress(
                        completed / total
                    )

            if property_failures:
                status.update(
                    label=(
                        f"{property_sheet} finished with "
                        f"{property_failures} error(s)"
                    ),
                    state="error",
                    expanded=True,
                )
            else:
                status.update(
                    label=(
                        f"{property_sheet} complete"
                    ),
                    state="complete",
                    expanded=False,
                )

    if not results:
        finalize_run_manifest(
            run_dir,
            status="failed",
            error=(
                "Every selected analysis failed."
            ),
        )
        progress_note.caption(
            "Run failed. No analysis completed successfully."
        )
        st.error(
            "Every selected property/method analysis failed. "
            "See the errors above and Run History for details."
        )
        st.stop()

    comparison_path = (
        export_validation_comparison(
            results,
            run_dir,
        )
    )
    final_status = (
        "completed_with_errors"
        if failed_count
        else "completed"
    )
    finalize_run_manifest(
        run_dir,
        status=final_status,
    )
    progress.progress(1.0)
    progress_note.caption(
        (
            "Run complete."
            if not failed_count
            else (
                f"Run finished with {failed_count} failed "
                "analysis combination(s). Successful results were preserved."
            )
        )
    )

    st.session_state[
        "soil_mir_results"
    ] = results
    st.session_state[
        "soil_mir_last_run_dir"
    ] = str(run_dir)
    st.session_state[
        "soil_mir_last_comparison"
    ] = comparison_path

    if failed_count:
        st.warning(
            "Validation finished with some errors. Successful analyses "
            f"were saved to {run_dir}. Open Results or Run History."
        )
    else:
        st.success(
            "Validation completed and saved to "
            f"{run_dir}. Open the Results page."
        )
