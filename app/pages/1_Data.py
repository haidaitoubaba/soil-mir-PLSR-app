from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.config import ColumnConfig
from soil_mir.io.opus import inspect_opus_directory
from soil_mir.io.reference import (
    discover_property_sheets,
    load_property_metadata,
    match_reference_files,
    read_property_sheet,
    summarize_property,
)
from soil_mir.services.acceptance import (
    run_data_acceptance,
)
from soil_mir.services.local_paths import (
    choose_local_path,
    detect_local_data_layout,
    load_path_preferences,
    save_path_preferences,
)

st.set_page_config(
    page_title="Data | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Data")
st.caption(
    "Inspect local spectra and reference data before modelling."
)

preferences = load_path_preferences()

initial_paths = {
    "soil_mir_spectra_input": st.session_state.get(
        "soil_mir_spectra_dir",
        preferences.get("spectra_dir", ""),
    ),
    "soil_mir_reference_input": st.session_state.get(
        "soil_mir_reference_excel",
        preferences.get("reference_excel", ""),
    ),
    "soil_mir_output_input": st.session_state.get(
        "soil_mir_output_dir",
        preferences.get("output_dir", ""),
    ),
}
for key, value in initial_paths.items():
    if key not in st.session_state:
        st.session_state[key] = value

detected_layout = detect_local_data_layout()
if detected_layout is not None:
    with st.expander(
        "Detected local dataset (optional)",
        expanded=False,
    ):
        st.write(
            "A possible Soil MIR data layout was detected from "
            f"**{detected_layout.source}**. "
            "Nothing is selected automatically."
        )
        st.code(
            "\n".join(
                [
                    f"Spectra: {detected_layout.spectra_dir}",
                    f"Reference: {detected_layout.reference_excel}",
                    f"Results: {detected_layout.output_dir}",
                ]
            )
        )
        if st.button(
            "Use detected data layout",
            key="use_detected_layout",
        ):
            st.session_state[
                "soil_mir_spectra_input"
            ] = str(detected_layout.spectra_dir)
            st.session_state[
                "soil_mir_reference_input"
            ] = str(detected_layout.reference_excel)
            st.session_state[
                "soil_mir_output_input"
            ] = str(detected_layout.output_dir)
            st.rerun()

st.caption(
    "Choose any local folders/files below. On macOS and Windows, the Browse "
    "buttons open the native system picker; paths can also be typed or pasted."
)

spectra_path_col, spectra_choose_col = st.columns(
    [5, 1]
)
with spectra_choose_col:
    if st.button(
        "Browse…",
        key="browse_spectra",
        use_container_width=True,
    ):
        try:
            selected = choose_local_path(
                "directory",
                prompt="Choose OPUS spectra folder",
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            if selected is not None:
                st.session_state[
                    "soil_mir_spectra_input"
                ] = str(selected)
with spectra_path_col:
    spectra_text = st.text_input(
        "OPUS spectra directory",
        key="soil_mir_spectra_input",
        placeholder="/path/to/data/spectra/Complete",
    )

reference_path_col, reference_choose_col = st.columns(
    [5, 1]
)
with reference_choose_col:
    if st.button(
        "Browse…",
        key="browse_reference",
        use_container_width=True,
    ):
        try:
            selected = choose_local_path(
                "file",
                prompt="Choose reference Excel workbook",
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            if selected is not None:
                st.session_state[
                    "soil_mir_reference_input"
                ] = str(selected)
with reference_path_col:
    reference_text = st.text_input(
        "Reference workbook",
        key="soil_mir_reference_input",
        placeholder="/path/to/reference_value.xlsx",
    )

output_path_col, output_choose_col = st.columns(
    [5, 1]
)
with output_choose_col:
    if st.button(
        "Browse…",
        key="browse_output",
        use_container_width=True,
    ):
        try:
            selected = choose_local_path(
                "directory",
                prompt="Choose results folder",
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            if selected is not None:
                st.session_state[
                    "soil_mir_output_input"
                ] = str(selected)
with output_path_col:
    output_text = st.text_input(
        "Results directory",
        key="soil_mir_output_input",
        placeholder="/path/to/soil_mir_results",
    )

if st.button(
    "Inspect data",
    type="primary",
    use_container_width=False,
):
    if (
        not spectra_text
        or not reference_text
        or not output_text
    ):
        st.error(
            "Select spectra, reference workbook, "
            "and results directory."
        )
        st.stop()

    spectra_path = Path(
        spectra_text
    ).expanduser()
    reference_path = Path(
        reference_text
    ).expanduser()
    output_path = Path(
        output_text
    ).expanduser()

    try:
        spectra = inspect_opus_directory(
            spectra_path
        )
        properties = discover_property_sheets(
            reference_path
        )
        metadata = load_property_metadata(
            reference_path
        )
        output_path.mkdir(
            parents=True,
            exist_ok=True,
        )
    except Exception as exc:
        st.exception(exc)
    else:
        source_signature = (
            str(spectra_path.resolve()),
            str(reference_path.resolve()),
        )
        previous_signature = st.session_state.get(
            "soil_mir_data_source_signature"
        )
        if (
            previous_signature is not None
            and previous_signature
            != source_signature
        ):
            st.session_state[
                "soil_mir_data_selected_properties"
            ] = []
            st.session_state[
                "soil_mir_selected_properties"
            ] = []
            st.session_state.pop(
                "cfg_selected_properties",
                None,
            )
            st.session_state.pop(
                "soil_mir_reference_ranges",
                None,
            )
            for key in list(
                st.session_state.keys()
            ):
                if (
                    key.startswith("ref_min_")
                    or key.startswith("ref_max_")
                ):
                    st.session_state.pop(
                        key,
                        None,
                    )
        st.session_state[
            "soil_mir_data_source_signature"
        ] = source_signature

        st.session_state[
            "soil_mir_spectra_dir"
        ] = str(spectra_path)
        st.session_state[
            "soil_mir_reference_excel"
        ] = str(reference_path)
        st.session_state[
            "soil_mir_output_dir"
        ] = str(output_path)
        st.session_state[
            "soil_mir_properties"
        ] = properties
        st.session_state[
            "soil_mir_metadata"
        ] = metadata
        st.session_state[
            "soil_mir_spectra_summary"
        ] = {
            "file_count": spectra.file_count,
            "total_bytes": spectra.total_bytes,
            "filenames": spectra.filenames,
        }
        try:
            save_path_preferences(
                spectra_path,
                reference_path,
                output_path,
            )
        except OSError as exc:
            st.warning(
                "Data inspection succeeded, but the last-used paths "
                f"could not be saved: {exc}"
            )

properties = st.session_state.get(
    "soil_mir_properties",
    [],
)
spectra_summary = st.session_state.get(
    "soil_mir_spectra_summary"
)
reference_path_text = st.session_state.get(
    "soil_mir_reference_excel"
)

if (
    properties
    and spectra_summary
    and reference_path_text
):
    a, b, c = st.columns(3)
    a.metric(
        "OPUS files",
        f"{spectra_summary['file_count']:,}",
    )
    b.metric(
        "Property sheets",
        len(properties),
    )
    c.metric(
        "Spectra size",
        (
            f"{spectra_summary['total_bytes'] / (1024**2):.1f} MB"
        ),
    )

    remembered_selection = [
        name
        for name in st.session_state.get(
            "soil_mir_data_selected_properties",
            [],
        )
        if name in properties
    ]
    selected = st.multiselect(
        "Properties to inspect",
        properties,
        default=remembered_selection,
        placeholder="Choose one or more properties",
        help=(
            "Properties are never selected automatically. "
            "Choose the sheets you want to inspect."
        ),
    )
    st.session_state[
        "soil_mir_data_selected_properties"
    ] = selected

    if selected:
        columns = ColumnConfig()
        metadata = st.session_state.get(
            "soil_mir_metadata",
            {},
        )
        available = set(
            spectra_summary["filenames"]
        )
        reference_path = Path(
            reference_path_text
        )
        rows = []
        zero_reference_details = []

        for sheet in selected:
            summary = summarize_property(
                reference_path,
                sheet,
                columns,
                metadata,
            )
            frame = read_property_sheet(
                reference_path,
                sheet,
                columns,
            )
            match = match_reference_files(
                frame,
                available,
                columns,
            )
            numeric_reference = pd.to_numeric(
                frame[columns.reference_value],
                errors="coerce",
            )
            zero_samples = sorted(
                frame.loc[
                    numeric_reference == 0,
                    columns.sample_id,
                ]
                .dropna()
                .astype(str)
                .unique()
            )
            if zero_samples:
                zero_reference_details.append(
                    (
                        sheet,
                        zero_samples,
                    )
                )
            rows.append(
                {
                    "Property": summary.sheet,
                    "Rows": summary.rows,
                    "Unique samples": (
                        summary.unique_samples
                    ),
                    "Groups": summary.groups,
                    "Missing refs": (
                        summary.missing_reference_values
                    ),
                    "Zero refs": (
                        summary.zero_reference_values
                    ),
                    "Zero ref samples": "; ".join(
                        zero_samples
                    ),
                    "Negative refs": (
                        summary.negative_reference_values
                    ),
                    "Duplicate rows": (
                        summary.duplicate_rows
                    ),
                    "Reference min": (
                        summary.reference_min
                    ),
                    "Reference max": (
                        summary.reference_max
                    ),
                    "Units": summary.units,
                    "Transform": summary.transform,
                    "Matched spectra": (
                        match["matched_files"]
                    ),
                    "Missing spectra": len(
                        match["missing_files"]
                    ),
                    "Match rate": (
                        match["match_rate"]
                    ),
                }
            )

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

        if zero_reference_details:
            detail_text = "; ".join(
                (
                    f"{sheet}: "
                    + ", ".join(samples)
                )
                for sheet, samples
                in zero_reference_details
            )
            st.warning(
                "Zero reference values detected and retained: "
                f"{detail_text}. "
                "They are not removed automatically. "
                "Use the property-specific reference filter in "
                "Configuration only if these zeros are known "
                "placeholders or invalid measurements."
            )

        for sheet in selected:
            frame = read_property_sheet(
                reference_path,
                sheet,
                columns,
            )
            match = match_reference_files(
                frame,
                available,
                columns,
            )
            if match["missing_files"]:
                with st.expander(
                    f"{sheet}: missing spectra "
                    f"({len(match['missing_files'])})"
                ):
                    st.code(
                        "\n".join(
                            match[
                                "missing_files"
                            ][:200]
                        )
                    )
            else:
                st.success(
                    f"{sheet}: every referenced "
                    "spectrum was found."
                )


        st.subheader("Full local data acceptance")
        st.caption(
            "This check actually parses every referenced OPUS file "
            "for the selected properties, verifies the retained spectral "
            "grid, and writes a reusable acceptance report. "
            "The first run builds the local OPUS cache; later properties "
            "and runs reuse unchanged spectra."
        )
        if st.button(
            "Run full data acceptance check",
            type="secondary",
        ):
            try:
                with st.status(
                    "Checking real OPUS data",
                    expanded=True,
                ) as acceptance_status:
                    acceptance = run_data_acceptance(
                        st.session_state[
                            "soil_mir_spectra_dir"
                        ],
                        st.session_state[
                            "soil_mir_reference_excel"
                        ],
                        st.session_state[
                            "soil_mir_output_dir"
                        ],
                        properties=list(selected),
                    )
                    acceptance_status.update(
                        label="Full data acceptance passed",
                        state="complete",
                        expanded=False,
                    )
            except Exception as exc:
                st.error(
                    "Full local data acceptance failed."
                )
                st.exception(exc)
            else:
                st.success(
                    "All selected reference rows and OPUS files "
                    "passed the full local data check."
                )
                st.dataframe(
                    acceptance["properties"],
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "Raw coverage shows the full range present across the "
                    "loaded OPUS axes. Shared coverage is the no-extrapolation "
                    "intersection used for alignment. Final coverage is the "
                    "configured modelling range after optional CO₂ exclusion."
                )
                if not acceptance["alignment"].empty:
                    st.subheader(
                        "Cross-property file alignment"
                    )
                    st.dataframe(
                        acceptance["alignment"],
                        use_container_width=True,
                        hide_index=True,
                    )
                st.write(
                    "Acceptance report: "
                    f"{acceptance['report_path']}"
                )
