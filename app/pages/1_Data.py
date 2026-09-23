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

st.set_page_config(page_title="Data | Soil MIR PLSR", page_icon="🌱", layout="wide")
st.title("Data")
st.caption("Inspect local spectra and reference data before modelling.")

spectra_text = st.text_input("OPUS spectra directory", placeholder="/path/to/data/spectra/Complete")
reference_text = st.text_input("Reference workbook", placeholder="/path/to/reference_value.xlsx")

if st.button("Inspect data", type="primary", use_container_width=False):
    if not spectra_text or not reference_text:
        st.error("Select both the spectra directory and reference workbook.")
        st.stop()

    spectra_path = Path(spectra_text).expanduser()
    reference_path = Path(reference_text).expanduser()

    try:
        spectra = inspect_opus_directory(spectra_path)
        properties = discover_property_sheets(reference_path)
        metadata = load_property_metadata(reference_path)
    except Exception as exc:
        st.exception(exc)
        st.stop()

    st.session_state["soil_mir_spectra_dir"] = str(spectra_path)
    st.session_state["soil_mir_reference_excel"] = str(reference_path)
    st.session_state["soil_mir_properties"] = properties

    a, b, c = st.columns(3)
    a.metric("OPUS files", f"{spectra.file_count:,}")
    b.metric("Property sheets", len(properties))
    c.metric("Spectra size", f"{spectra.total_bytes / (1024**2):.1f} MB")

    preferred = [name for name in ("202_STC", "202_STN") if name in properties]
    selected = st.multiselect(
        "Properties to inspect",
        properties,
        default=preferred or properties[: min(2, len(properties))],
    )

    if selected:
        columns = ColumnConfig()
        rows = []
        for sheet in selected:
            summary = summarize_property(reference_path, sheet, columns, metadata)
            frame = read_property_sheet(reference_path, sheet, columns)
            match = match_reference_files(frame, set(spectra.filenames), columns)
            rows.append(
                {
                    "Property": summary.sheet,
                    "Rows": summary.rows,
                    "Unique samples": summary.unique_samples,
                    "Groups": summary.groups,
                    "Reference min": summary.reference_min,
                    "Reference max": summary.reference_max,
                    "Units": summary.units,
                    "Transform": summary.transform,
                    "Matched spectra": match["matched_files"],
                    "Missing spectra": len(match["missing_files"]),
                    "Match rate": match["match_rate"],
                }
            )

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        for sheet in selected:
            frame = read_property_sheet(reference_path, sheet, columns)
            match = match_reference_files(frame, set(spectra.filenames), columns)
            if match["missing_files"]:
                with st.expander(f"{sheet}: missing spectra ({len(match['missing_files'])})"):
                    st.code("\n".join(match["missing_files"][:200]))
            else:
                st.success(f"{sheet}: every referenced spectrum was found.")
