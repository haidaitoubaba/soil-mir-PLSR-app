from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.config import ColumnConfig


VALID_TRANSFORMS = {"none", "sqrt", "log", "log10", "cbrt", "boxcox", "yeojohnson"}


@dataclass(frozen=True)
class PropertySummary:
    sheet: str
    rows: int
    unique_samples: int
    groups: int | None
    group_column_present: bool
    missing_group_values: int
    missing_reference_values: int
    zero_reference_values: int
    negative_reference_values: int
    duplicate_rows: int
    reference_min: float | None
    reference_max: float | None
    units: str = ""
    transform: str = "none"
    exclude_co2: bool | None = None


def validate_reference_frame(frame: pd.DataFrame, columns: ColumnConfig) -> None:
    missing = [name for name in columns.required if name not in frame.columns]
    if missing:
        raise ValueError(f"Reference sheet is missing columns: {missing}")

    values = frame[columns.reference_value].dropna()
    try:
        numeric = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Nonempty reference values must be numeric") from exc
    if not np.isfinite(numeric).all():
        raise ValueError("Reference values must be finite")

    labelled = frame[columns.reference_value].notna()
    if frame.loc[labelled, columns.sample_id].isna().any():
        raise ValueError("Every nonempty reference value must have a sample ID")


def discover_property_sheets(
    workbook_path: str | Path,
    columns: ColumnConfig | None = None,
    skip_sheets: tuple[str, ...] = ("Lookup table", "Transformation", "Property Metadata"),
) -> list[str]:
    columns = columns or ColumnConfig()
    workbook_path = Path(workbook_path)
    with pd.ExcelFile(workbook_path) as workbook:
        valid: list[str] = []
        for sheet in workbook.sheet_names:
            if sheet in skip_sheets:
                continue
            header = set(workbook.parse(sheet_name=sheet, nrows=0).columns)
            if all(col in header for col in columns.required):
                valid.append(sheet)
    if not valid:
        raise ValueError("No property sheets with the required columns were found")
    return valid


def _parse_optional_bool(value: object) -> bool | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    raise ValueError(f"Cannot interpret boolean metadata value: {value!r}")


def load_property_metadata(
    workbook_path: str | Path,
    metadata_sheet: str = "Property Metadata",
) -> dict[str, dict[str, object]]:
    workbook_path = Path(workbook_path)
    with pd.ExcelFile(workbook_path) as workbook:
        if metadata_sheet not in workbook.sheet_names:
            return {}
        frame = workbook.parse(metadata_sheet)

    required = {"Property", "Units", "Transform"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Metadata sheet is missing columns: {sorted(missing)}")

    result: dict[str, dict[str, object]] = {}
    for _, row in frame.iterrows():
        if pd.isna(row["Property"]):
            continue
        prop = str(row["Property"]).strip()
        if "Field" in frame.columns and not pd.isna(row.get("Field")):
            raw_field = row.get("Field")
            if isinstance(raw_field, (int, np.integer)):
                field = str(int(raw_field))
            elif isinstance(raw_field, (float, np.floating)) and float(raw_field).is_integer():
                field = str(int(raw_field))
            else:
                field = str(raw_field).strip()
            if field:
                prop = f"{field}_{prop}"

        transform_raw = row.get("Transform")
        transform = "none" if pd.isna(transform_raw) else str(transform_raw).strip().lower()
        if transform not in VALID_TRANSFORMS:
            raise ValueError(f"Invalid transform {transform!r} for {prop}")
        units = "" if pd.isna(row.get("Units")) else str(row.get("Units")).strip()
        result[prop] = {
            "units": units,
            "transform": transform,
            "exclude_co2": _parse_optional_bool(row.get("Exclude CO2")),
        }
    return result


def read_property_sheet(
    workbook_path: str | Path,
    sheet: str,
    columns: ColumnConfig | None = None,
) -> pd.DataFrame:
    columns = columns or ColumnConfig()
    frame = pd.read_excel(workbook_path, sheet_name=sheet)
    validate_reference_frame(frame, columns)
    return frame


def summarize_property(
    workbook_path: str | Path,
    sheet: str,
    columns: ColumnConfig | None = None,
    metadata: dict[str, dict[str, object]] | None = None,
) -> PropertySummary:
    columns = columns or ColumnConfig()
    frame = read_property_sheet(workbook_path, sheet, columns)
    numeric = pd.to_numeric(frame[columns.reference_value], errors="coerce")
    nonempty = numeric.dropna()
    meta = (metadata or {}).get(sheet, {})
    group_column_present = columns.group in frame.columns
    if group_column_present:
        group_values = (
            frame[columns.group]
            .where(frame[columns.group].notna(), "")
            .astype(str)
            .str.strip()
        )
        groups = int(
            group_values[group_values != ""].nunique()
        )
        missing_group_values = int(
            (group_values == "").sum()
        )
    else:
        groups = None
        missing_group_values = 0

    return PropertySummary(
        sheet=sheet,
        rows=len(frame),
        unique_samples=int(frame[columns.sample_id].nunique(dropna=True)),
        groups=groups,
        group_column_present=group_column_present,
        missing_group_values=missing_group_values,
        missing_reference_values=int(numeric.isna().sum()),
        zero_reference_values=int((numeric == 0).sum()),
        negative_reference_values=int((numeric < 0).sum()),
        duplicate_rows=int(frame.duplicated().sum()),
        reference_min=float(nonempty.min()) if len(nonempty) else None,
        reference_max=float(nonempty.max()) if len(nonempty) else None,
        units=str(meta.get("units", "")),
        transform=str(meta.get("transform", "none")),
        exclude_co2=meta.get("exclude_co2"),
    )


def match_reference_files(
    frame: pd.DataFrame,
    available_filenames: set[str],
    columns: ColumnConfig | None = None,
) -> dict[str, object]:
    columns = columns or ColumnConfig()
    requested = frame[columns.reference_file].dropna().astype(str)
    unique_requested = set(requested)
    missing = sorted(unique_requested - available_filenames)
    matched = unique_requested & available_filenames
    return {
        "reference_rows": len(frame),
        "referenced_files": len(unique_requested),
        "matched_files": len(matched),
        "missing_files": missing,
        "match_rate": 1.0 if not unique_requested else len(matched) / len(unique_requested),
    }
