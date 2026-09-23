from __future__ import annotations

from pathlib import Path

from soil_mir.config import ColumnConfig
from soil_mir.io.opus import inspect_opus_directory
from soil_mir.io.reference import (
    discover_property_sheets,
    load_property_metadata,
    match_reference_files,
    read_property_sheet,
    summarize_property,
)


def inspect_project_inputs(
    spectra_dir: str | Path,
    reference_excel: str | Path,
    selected_sheets: list[str] | None = None,
) -> dict[str, object]:
    columns = ColumnConfig()
    spectra = inspect_opus_directory(spectra_dir)
    properties = discover_property_sheets(reference_excel, columns)
    metadata = load_property_metadata(reference_excel)
    sheets = selected_sheets or properties

    summaries = []
    matching = {}
    available = set(spectra.filenames)
    for sheet in sheets:
        if sheet not in properties:
            raise ValueError(f"Unknown property sheet: {sheet}")
        summaries.append(summarize_property(reference_excel, sheet, columns, metadata))
        frame = read_property_sheet(reference_excel, sheet, columns)
        matching[sheet] = match_reference_files(frame, available, columns)

    return {
        "spectra": spectra,
        "property_sheets": properties,
        "metadata": metadata,
        "summaries": summaries,
        "matching": matching,
    }
