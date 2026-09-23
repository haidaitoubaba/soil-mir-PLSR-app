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
from soil_mir.services.local_paths import (
    detect_local_data_layout,
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

detected_layout = None
if not (
    st.session_state.get("soil_mir_spectra_dir")
    or st.session_state.get("soil_mir_reference_excel")
):
    detected_layout = detect_local_data_layout()

default_spectra = st.session_state.get(
    "soil_mir_spectra_dir",
    "",
)
default_reference = st.session_state.get(
    "soil_mir_reference_excel",
    "",
)
default_output = st.session_state.get(
    "soil_mir_output_dir",
    "",
)

if detected_layout is not None:
    default_spectra = default_spectra or str(
        detected_layout.spectra_dir
    )
    default_reference = default_reference or str(
        detected_layout.reference_excel
    )
    default_output = default_output or str(
        detected_layout.output_dir
    )
    st.success(
        "Detected local Soil MIR data layout from "
        f"{detected_layout.source}."
    )

spectra_text = st.text_input(
    "OPUS spectra directory",
    value=default_spectra,
    placeholder="/path/to/data/spectra/Complete",
)
reference_text = st.text_input(
    "Reference workbook",
    value=default_reference,
    placeholder="/path/to/reference_value.xlsx",
)

if not default_output and reference_text:
    default_output = str(
        Path(reference_text)
        .expanduser()
        .parent
        / "soil_mir_results"
    )

output_text = st.text_input(
    "Results directory",
    value=default_output,
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

    preferred = [
        name
        for name in (
            "202_STC",
            "202_STN",
        )
        if name in properties
    ]
    selected = st.multiselect(
        "Properties to inspect",
        properties,
        default=st.session_state.get(
            "soil_mir_data_selected_properties",
            preferred
            or properties[
                : min(2, len(properties))
            ],
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
