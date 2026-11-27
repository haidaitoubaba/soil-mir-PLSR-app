"""Create Cleanup v1 sessions from local reference workbooks and OPUS spectra."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
from struct import error as StructError
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from soil_mir.io.opus import OPUS_NATIVE, read_opus_spectrum

from .calibration import apply_transform
from .desktop_session import DesktopReview, compute_pca, fingerprint, record_history
from .offline import offline_html


COLUMNS = ["Sample", "File Name", "Reference Value", "Group"]
TRANSFORMS = {"none", "sqrt", "log", "log10", "cbrt", "boxcox", "yeojohnson"}
OPUS_SUFFIXES = {f".{index}" for index in range(10)}


@dataclass
class SessionInputs:
    workbook: Path
    spectra: Path
    parent: Path
    workbook_hash: str
    frames: dict
    configs: dict
    properties: list

    def preview(self):
        return {"properties": self.properties}


def local_path(value, label, *, directory=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Enter the {label} path.")
    path = Path(value.strip()).expanduser()
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        raise ValueError(f"{label.capitalize()} does not exist: {path}")
    return path.resolve(strict=True)


def opus_paths(folder):
    return sorted(
        path
        for path in folder.iterdir()
        if not path.name.startswith(".") and path.suffix in OPUS_SUFFIXES and path.is_file()
    )


def metadata_text(value, default=""):
    return default if pd.isna(value) else str(value).strip()


def property_metadata(book):
    if "Property Metadata" not in book.sheet_names:
        raise ValueError("Add the Property Metadata sheet to the reference workbook.")
    sheet = book.parse("Property Metadata")
    if not {"Property", "Units", "Transform"} <= set(sheet):
        raise ValueError("Property Metadata requires Property, Units, and Transform columns.")

    configs = {}
    invalid = {}
    for _, row in sheet.iterrows():
        if pd.isna(row["Property"]):
            continue
        name = metadata_text(row["Property"])
        field = metadata_text(row.get("Field"))
        key = f"{field}_{name}" if field else name
        transform = metadata_text(row["Transform"], "none").lower()
        raw_co2 = row.get("Exclude CO2")
        co2 = metadata_text(raw_co2).lower()
        if isinstance(raw_co2, (float, int)) and raw_co2 in (0, 1):
            co2 = str(int(raw_co2))
        config = {
            "transform": transform,
            "units": metadata_text(row["Units"]),
            "exclude_co2": co2 in {"true", "yes", "y", "1"},
            "sg_window": 11,
            "sg_polyorder": 2,
        }
        try:
            if transform not in TRANSFORMS:
                raise ValueError(
                    f"Invalid Transform '{transform}'. Use {', '.join(sorted(TRANSFORMS))}."
                )
            if co2 not in {"", "true", "yes", "y", "1", "false", "no", "n", "0"}:
                raise ValueError(f"Invalid Exclude CO2 value '{co2}'. Use Yes or No.")
            raw_tolerance = row.get("RMSECV Tolerance (%)")
            if metadata_text(raw_tolerance):
                try:
                    tolerance = float(raw_tolerance)
                except (TypeError, ValueError) as exc:
                    raise ValueError("RMSECV Tolerance (%) must be numeric.") from exc
                if (
                    isinstance(raw_tolerance, (bool, np.bool_))
                    or not np.isfinite(tolerance)
                    or tolerance < 0
                ):
                    raise ValueError(
                        "RMSECV Tolerance (%) must be a finite nonnegative percentage."
                    )
            if key in configs:
                raise ValueError("Duplicate Property Metadata rows.")
            configs[key] = config
        except ValueError as exc:
            invalid[key] = str(exc)
    return configs, invalid


def describe_files(names):
    return ", ".join(map(str, names[:8])) + (
        f" and {len(names) - 8} more" if len(names) > 8 else ""
    )


def validate_frame(frame):
    if frame.empty or frame[COLUMNS].isna().any().any():
        raise ValueError("The sheet is empty or has missing required values.")
    for col in ("Sample", "File Name", "Group"):
        if frame[col].astype(str).str.strip().eq("").any():
            raise ValueError(f"Blank {col}.")
    duplicates = frame.loc[frame["File Name"].duplicated(), "File Name"].unique().tolist()
    if duplicates:
        raise ValueError(f"Duplicate reference filenames: {describe_files(duplicates)}.")
    if not np.isfinite(pd.to_numeric(frame["Reference Value"], errors="raise")).all():
        raise ValueError("Non-finite reference values.")
    if (frame.groupby("Sample")[["Reference Value", "Group"]].nunique() > 1).any().any():
        raise ValueError("Inconsistent reference value or group within a sample.")


def inspect_inputs(workbook_path, spectra_path, output_path):
    workbook = local_path(workbook_path, "reference Excel")
    if workbook.suffix.lower() != ".xlsx":
        raise ValueError("Choose the original reference workbook in .xlsx format.")
    spectra = local_path(spectra_path, "OPUS folder", directory=True)
    parent = local_path(output_path, "session output folder", directory=True)
    filenames = {path.name for path in opus_paths(spectra)}
    if not filenames:
        raise ValueError(f"No OPUS files with extensions .0–.9 were found in {spectra}.")
    original = workbook.read_bytes()
    frames, configs, properties = {}, {}, []
    with pd.ExcelFile(BytesIO(original), engine="openpyxl") as book:
        metadata, invalid = property_metadata(book)
        for name in book.sheet_names:
            if not set(COLUMNS) <= set(book.parse(name, nrows=0)):
                continue
            frame = book.parse(name).dropna(how="all").reset_index(drop=True)
            metadata_name = name
            if name.endswith("_OPUS") and name not in metadata and name not in invalid:
                metadata_name = name[:-5]
            config = metadata.get(metadata_name)
            info = {"name": name, "samples": int(frame["Sample"].nunique()), "spectra": len(frame)}
            if config:
                info.update(
                    transform=config["transform"],
                    units=config["units"],
                    excludeCO2=config["exclude_co2"],
                )
            try:
                if metadata_name in invalid:
                    raise ValueError(invalid[metadata_name])
                if config is None:
                    raise ValueError("Missing Property Metadata row.")
                validate_frame(frame)
                apply_transform(frame["Reference Value"].to_numpy(float), config["transform"])
                missing = [file for file in frame["File Name"] if file not in filenames]
                if missing:
                    raise ValueError(
                        f"{len(missing)} missing OPUS file(s): {describe_files(missing)}."
                    )
                frames[name] = frame
                configs[name] = config
            except (ValueError, TypeError, ArithmeticError) as exc:
                info["error"] = str(exc)
            properties.append(info)
    if not properties:
        raise ValueError(
            "No property sheets contain Sample, File Name, Reference Value, and Group."
        )
    return SessionInputs(
        workbook, spectra, parent, sha256(original).hexdigest(), frames, configs, properties
    )


def file_signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_library(folder, required, progress):
    paths = opus_paths(folder)
    if missing := sorted(required - {path.name for path in paths}):
        raise ValueError(f"Missing OPUS files: {describe_files(missing)}.")
    signatures = {path: file_signature(path) for path in paths}
    library, hashes, failures = {}, {}, {}
    for index, path in enumerate(paths, 1):
        if index == 1 or index % 40 == 0 or index == len(paths):
            progress(f"Reading OPUS spectra ({index:,} / {len(paths):,})…")
        try:
            library[path.name] = read_opus_spectrum(path, opus_axis_mode=OPUS_NATIVE)
            if path.name in required:
                hashes[path.name] = fingerprint(path)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            OverflowError,
            StructError,
        ) as exc:
            failures[path.name] = str(exc)
    needed_failures = [
        f"{name} ({reason})" for name, reason in failures.items() if name in required
    ]
    if needed_failures:
        raise ValueError(
            f"{len(needed_failures)} unreadable OPUS file(s): {describe_files(needed_failures)}"
        )
    progress("Aligning spectra on the shared wavenumber grid…")
    return align_library(library), signatures, hashes, failures


def align_library(library):
    for name, (values, axis) in library.items():
        steps = np.diff(axis)
        if (
            len(axis) < 2
            or not np.isfinite(axis).all()
            or not (np.all(steps > 0) or np.all(steps < 0))
        ):
            raise ValueError(f"{name}: wavenumbers must be finite and strictly monotonic.")
        if values.shape != axis.shape or not np.isfinite(values).all():
            raise ValueError(
                f"{name}: spectrum values must be finite and match the wavenumber axis."
            )
    axes = [axis for _, axis in library.values()]
    modal = Counter(map(len, axes)).most_common(1)[0][0]
    axis = next(axis for axis in axes if len(axis) == modal)
    lower, upper = max(a.min() for a in axes), min(a.max() for a in axes)
    grid = axis[(axis >= lower) & (axis <= upper)]
    if len(grid) < 2:
        raise ValueError("Spectra have insufficient shared wavenumber coverage.")
    spectra = {}
    for name, (values, axis) in library.items():
        if np.array_equal(axis, grid):
            spectra[name] = values
        elif axis[0] > axis[-1]:
            spectra[name] = np.interp(grid, axis[::-1], values[::-1])
        else:
            spectra[name] = np.interp(grid, axis, values)
    return spectra, grid


def initial_property(folder, matrix_name, frame, settings, spectra, grid):
    mask = (grid >= 600) & (grid <= 4000)
    if settings["exclude_co2"]:
        mask &= ~((grid >= 2300) & (grid <= 2400))
    axis = grid[mask]
    if len(axis) < 2:
        raise ValueError("Fewer than two wavenumbers remain after applying the spectral range.")
    breaks = np.flatnonzero(np.abs(np.diff(axis)) > 1.5 * np.median(np.abs(np.diff(grid)))) + 1
    config = {**settings, "_segment_lengths": [len(segment) for segment in np.split(axis, breaks)]}
    matrix = np.array([spectra[name][mask] for name in frame["File Name"]])
    rows = frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")
    fitted, variance = compute_pca(matrix, rows)
    path = folder / matrix_name
    np.savez_compressed(path, X=matrix, axis=axis)
    return {
        "frame": rows,
        "config": config,
        "matrix": matrix_name,
        "matrix_sha256": fingerprint(path),
        "decisions": {},
        "pca": {"rows": fitted, "variance": variance, "round": 1},
        "pca_round": 1,
        "pca_dirty": False,
        "pca_done": False,
        "halves": {},
        "diagnostics": {},
        "finished": {"A": False, "B": False},
        "archive": [],
    }


def publish_session(stage, parent):
    target = parent / datetime.now().strftime("session_web_%Y%m%d_%H%M%S_%f")
    target.mkdir()
    try:
        for child in stage.iterdir():
            if child.name != "session.json":
                child.rename(target / child.name)
        (stage / "session.json").rename(target / "session.json")
    except Exception:
        shutil.rmtree(target)
        raise
    return target


def create_session(inputs, selected, progress):
    if (
        not isinstance(selected, list)
        or not selected
        or not all(isinstance(name, str) for name in selected)
    ):
        raise ValueError("Select at least one ready property sheet.")
    if not set(selected) <= inputs.frames.keys():
        raise ValueError("Select only ready property sheets from the input check.")
    names = [name for name in inputs.frames if name in selected]
    if fingerprint(inputs.workbook) != inputs.workbook_hash:
        raise ValueError("The reference Excel changed. Run Check inputs again.")
    required = {file for name in names for file in inputs.frames[name]["File Name"]}
    (spectra, grid), signatures, hashes, failures = read_library(inputs.spectra, required, progress)
    state = {
        "version": 1,
        "source": str(inputs.workbook),
        "source_sha256": inputs.workbook_hash,
        "spectra_dir": str(inputs.spectra),
        "properties": {},
        "history": [],
        "limit": "disable",
        "percent": 1.0,
        "created": datetime.now(timezone.utc).isoformat(),
        "spectra_sha256": hashes,
        "opus_axis_mode": OPUS_NATIVE,
    }
    with TemporaryDirectory(prefix=".mir-new-session-", dir=inputs.parent) as directory:
        stage = Path(directory)
        for index, name in enumerate(names):
            progress(f"Fitting initial PCA for {name} ({index + 1} / {len(names)})…")
            try:
                prop = initial_property(
                    stage,
                    f"spectra_{index}.npz",
                    inputs.frames[name],
                    inputs.configs[name],
                    spectra,
                    grid,
                )
            except (ValueError, TypeError, ArithmeticError) as exc:
                raise ValueError(f"{name}: {exc}") from exc
            state["properties"][name] = prop
            record_history(state, f"{name}: PCA fit 1 completed (web)")
        if failures:
            record_history(
                state,
                f"Skipped {len(failures)} unreferenced unreadable OPUS files: "
                f"{describe_files(list(failures))}",
            )
        record_history(state, "Created Cleanup session from reference Excel and OPUS spectra (web)")
        progress("Verifying inputs and saving the session…")
        with (stage / "session.json").open("x", encoding="utf-8") as file:
            json.dump(state, file, indent=2, allow_nan=False, default=serialize_cell)
            file.write("\n")
        review = DesktopReview(str(stage))
        (stage / "PCA_viewer.html").write_text(
            offline_html(review.all_property_data(), review.active), encoding="utf-8"
        )
        if fingerprint(inputs.workbook) != inputs.workbook_hash:
            raise ValueError("The reference Excel changed. Run Check inputs again.")
        if set(opus_paths(inputs.spectra)) != signatures.keys() or any(
            file_signature(path) != signature for path, signature in signatures.items()
        ):
            raise ValueError("The OPUS folder changed during import. Run Check inputs again.")
        if any(fingerprint(inputs.spectra / name) != digest for name, digest in hashes.items()):
            raise ValueError("An OPUS spectrum changed during import. Run Check inputs again.")
        review.source = publish_session(stage, inputs.parent)
        review.suggested_path = review.destination_suggestion()
    warning = f" Skipped {len(failures)} unreferenced unreadable OPUS files." if failures else ""
    return review, warning


def serialize_cell(value):
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(f"Unsupported reference workbook cell value: {type(value).__name__}.")
