"""Reference-free batch QC, with one shared result for UI and reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.io.cache import load_opus_spectra_cached
from soil_mir.io.opus import list_opus_files, read_opus_spectrum
from soil_mir.services.qc_manifest import digest_file, resolve_groups
from soil_mir.qc import (
    REGIONS, align_group, classify_pair, diagnose,
    group_issues, mad_threshold, pair_metrics,
)


def file_inventory(directory):
    return tuple(
        (path.name, path.stat().st_size, path.stat().st_mtime_ns)
        for path in list_opus_files(directory)
    )


@dataclass
class Batch:
    directory: str
    inventory: tuple
    pattern: str
    batch_label: str
    expected: int
    lower: float
    upper: float
    exclude_co2: bool
    regions: tuple
    groups: dict
    unmatched: list
    raw: dict
    errors: dict
    aligned: dict
    pair_data: dict
    mapping: dict | None = None
    content_hashes: dict | None = None


def prepare_batch(
    directory, *, pattern="Auto", batch_label="", expected=3,
    lower=600., upper=4000., exclude_co2=False, regions=REGIONS,
    cache_root=None, progress=None, mapping=None,
):
    directory = str(Path(directory).expanduser().resolve())
    inventory = file_inventory(directory)
    if not inventory:
        raise ValueError("No OPUS files with numeric extensions were found.")
    names = [name for name, _, _ in inventory]
    content_hashes = {name: digest_file(Path(directory) / name) for name in names}
    groups, unmatched, detected = resolve_groups(names, pattern, mapping)
    if not np.isfinite([lower, upper]).all() or lower >= upper:
        raise ValueError("QC spectral minimum must be below maximum.")
    group_issues([], expected)
    raw, errors, aligned, pair_data = {}, {}, {}, {}
    if progress:
        progress(0., "Reading OPUS spectra")
    # A broken file must never prevent valid groups from being evaluated.
    try:
        raw, _ = load_opus_spectra_cached(
            directory, names, cache_root, require_absorbance=True,
            **({"content_hashes": content_hashes} if cache_root else {}),
        )
    except Exception:
        for name in names:
            try:
                raw[name] = read_opus_spectrum(Path(directory) / name, require_absorbance=True)
            except Exception as exc:
                errors[name] = str(exc)
    # Reject unusable individual scans before any attribution.
    for name, (values, axis) in raw.items():
        mask = (axis >= lower) & (axis <= upper)
        if exclude_co2:
            mask &= (axis < 2300) | (axis > 2400)
        retained = values[mask]
        if axis.min() > lower or axis.max() < upper:
            errors[name] = "Requested range not fully covered"
        elif len(retained) < 2 or np.linalg.norm(retained - retained.mean()) <= 1e-12:
            errors[name] = "Constant spectrum or insufficient valid spectral points"
    count = max(1, len(groups))
    for i, (sample, scans) in enumerate(groups.items(), 1):
        available = {s.filename: raw[s.filename] for s in scans
                     if s.filename in raw and s.filename not in errors}
        axis, spectra = None, {}
        group_error = ""
        if available:
            try:
                axis, spectra = align_group(available, lower, upper)
                aligned[sample] = (axis, spectra)
            except ValueError as exc:
                group_error = str(exc)
        entries = []
        for a, b in combinations(sorted(scans, key=lambda s: s.filename), 2):
            metrics, error = None, group_error
            if a.filename in errors or b.filename in errors:
                error = "; ".join(errors[n] for n in (a.filename, b.filename) if n in errors)
            elif a.filename in spectra and b.filename in spectra:
                try:
                    metrics = pair_metrics(
                        spectra[a.filename], spectra[b.filename], axis,
                        exclude_co2=exclude_co2, regions=regions,
                    )
                except ValueError as exc:
                    error = str(exc)
            else:
                error = error or "Spectrum unavailable"
            entries.append((a, b, metrics, error))
        pair_data[sample] = (entries, group_error)
        if progress:
            progress(i / count, f"Comparing sample {i}/{count}")
    if file_inventory(directory) != inventory:
        raise ValueError("Files changed during QC. Please rerun.")
    return Batch(
        directory, inventory, detected, batch_label, expected, lower, upper,
        exclude_co2, tuple(regions), groups, unmatched, raw, errors, aligned, pair_data,
        mapping, content_hashes,
    )


def _extreme(metrics, key, function, multiplier=1.):
    values = [m[key] * multiplier for m in metrics if m is not None]
    return function(values) if values else None


def evaluate_batch(batch, criteria, decisions=None):
    """Reclassify cached pair metrics without reading or aligning spectra again."""
    decisions = decisions or {}
    samples, pairs, regional, files, rescans = [], [], [], [], []
    for sample, scans in batch.groups.items():
        entries, group_error = batch.pair_data[sample]
        edges, pair_rows = [], []
        for a, b, m, error in entries:
            status, reasons = classify_pair(m, criteria)
            if error:
                reasons = reasons + [error]
            edges.append((a.filename, b.filename, status))
            row = {
                "Sample ID": sample, "Batch": batch.batch_label,
                "Replicate A": a.replicate, "Replicate B": b.replicate,
                "File A": a.filename, "File B": b.filename,
                "Similarity (%)": m["r"] * 100 if m else None,
                "RMSE (AU)": m["rmse"] if m else None,
                "NRMSE (%)": m["nrmse"] if m else None,
                "SAM (degrees)": m["sam"] if m else None,
                "Mean difference (AU)": m["mean_difference"] if m else None,
                "Points": m["points"] if m else None,
                "Pair QC": status, "Reason": "; ".join(reasons),
            }
            if sample in batch.aligned:
                axis, _ = batch.aligned[sample]
                row.update({
                    "Aligned minimum": float(axis.min()),
                    "Aligned maximum": float(axis.max()),
                    "Aligned spacing": float(np.median(np.diff(axis))),
                })
            pair_rows.append(row)
            for low, high in batch.regions:
                value = m["regional"].get((low, high)) if m else None
                limits = criteria.regional_limits.get((low, high))
                warning = ""
                if value is None:
                    warning = "Not evaluated"
                elif limits and value > limits[0]:
                    warning = "Above configured limit"
                regional.append({
                    "Sample ID": sample, "File A": a.filename, "File B": b.filename,
                    "Lower": low, "Upper": high, "RMSE (AU)": value,
                    "Actual minimum": m["regional_info"][(low, high)][0] if m else None,
                    "Actual maximum": m["regional_info"][(low, high)][1] if m else None,
                    "Points": m["regional_info"][(low, high)][2] if m else None,
                    "Pass limit (AU)": limits[0] if limits else None,
                    "Fail limit (AU)": limits[1] if limits else None,
                    "Warning": warning,
                })
        pairs.extend(pair_rows)
        d = diagnose(scans, edges, batch.expected)
        metrics = [m for _, _, m, _ in entries]
        reasons = [row["Reason"] for row in pair_rows if row["Reason"]]
        if group_error:
            reasons.append(group_error)
        reasons += [f"{key}: {value}" for key, value in group_issues(
            scans, batch.expected
        ).items() if value]
        samples.append({
            "Sample ID": sample, "Batch": batch.batch_label,
            "Replicates": len(scans), "Expected replicates": batch.expected,
            "Min similarity (%)": _extreme(metrics, "r", min, 100),
            "Max NRMSE (%)": _extreme(metrics, "nrmse", max),
            "Max RMSE (AU)": _extreme(metrics, "rmse", max),
            "Max SAM (degrees)": _extreme(metrics, "sam", max),
            "Pairs passed": d["passed"], "Expected pairs": d["expected_pairs"],
            "Sample QC": d["status"], "Suspected Replicate": d["suspected_replicate"],
            "Suspected File": d["suspected_file"] or "",
            "Review Candidate Files": "; ".join(d["review_candidates"]),
            "Diagnosis Reason": "; ".join(dict.fromkeys(reasons)),
            "Recommended Action": d["action"],
        })
        for scan in scans:
            name = scan.filename
            related = [row for row in pair_rows if name in (row["File A"], row["File B"])]
            diag = "Invalid" if name in batch.errors else d["files"][name]
            manual = decisions.get(name, {})
            action = manual.get("decision", "Pending review")
            file_row = {
                "Sample ID": sample, "Batch": batch.batch_label,
                "Replicate ID": scan.replicate, "Well": scan.well, "File Name": name,
                "File Diagnosis": diag, "Read Error": batch.errors.get(name, ""),
                "Pass pairs": sum(row["Pair QC"] == "Pass" for row in related),
                "Review pairs": sum(row["Pair QC"] == "Review" for row in related),
                "Fail pairs": sum(row["Pair QC"] == "Fail" for row in related),
                "Invalid pairs": sum(row["Pair QC"] == "Invalid" for row in related),
                "Min similarity (%)": min(
                    (row["Similarity (%)"] for row in related
                     if row["Similarity (%)"] is not None), default=None,
                ),
                "Max NRMSE (%)": max(
                    (row["NRMSE (%)"] for row in related
                     if row["NRMSE (%)"] is not None), default=None,
                ),
                "Related non-passing files": "; ".join(
                    row["File B"] if row["File A"] == name else row["File A"]
                    for row in related if row["Pair QC"] != "Pass"
                ),
                "Reason": "; ".join(row["Reason"] for row in related if row["Reason"]),
                "Manual decision": action, "Manual reason": manual.get("reason", ""),
                "Review timestamp": manual.get("timestamp", ""),
                "Recommended Action": (
                    "Keep (suggested)" if d["status"] == "Pass"
                    else d["action"]
                ),
            }
            if name in batch.raw:
                values, axis = batch.raw[name]
                file_row.update({
                    "Native points": len(values), "Native minimum": float(axis.min()),
                    "Native maximum": float(axis.max()),
                })
            files.append(file_row)
            if action == "Rescan required":
                rescans.append({
                    "Sample ID": sample, "File Name": name, "Replicate ID": scan.replicate,
                    "Type": "Confirmed rescan", "Reason": manual.get("reason", ""),
                })
            if name == d["suspected_file"] or diag == "Invalid":
                rescans.append({
                    "Sample ID": sample, "File Name": name, "Replicate ID": scan.replicate,
                    "Type": "Suggested inspection or rescan", "Reason": diag,
                })
        if d["status"] == "Fail" or (
            d["status"] == "Review" and not d["passed"]
        ):
            rescans.append({
                "Sample ID": sample, "File Name": "", "Replicate ID": None,
                "Type": "Whole sample review or rescan", "Reason": d["action"],
            })
        if batch.expected == 3 and d["status"] == "Review" and d["passed"] == 2:
            rescans.append({
                "Sample ID": sample, "File Name": "; ".join(d["review_candidates"]),
                "Replicate ID": None, "Type": "Inspect file pair", "Reason": d["action"],
            })
        for missing in d["missing"]:
            rescans.append({
                "Sample ID": sample, "File Name": "", "Replicate ID": missing,
                "Type": "Missing replicate", "Reason": "Expected ID not found",
            })
    for name in batch.unmatched:
        manual = decisions.get(name, {})
        files.append({
            "Sample ID": "", "Batch": batch.batch_label, "File Name": name,
            "File Diagnosis": "Unmatched", "Read Error": batch.errors.get(name, ""),
            "Recommended Action": "Correct filename grouping",
            "Manual decision": manual.get("decision", "Pending review"),
            "Manual reason": manual.get("reason", ""),
            "Review timestamp": manual.get("timestamp", ""),
        })
    sample_frame = pd.DataFrame(samples)
    pair_frame = pd.DataFrame(pairs)
    file_frame = pd.DataFrame(files)
    rescan_frame = pd.DataFrame(
        rescans, columns=["Sample ID", "File Name", "Replicate ID", "Type", "Reason"]
    )
    rescan_frame["Similarity threshold (%)"] = criteria.similarity
    rescan_frame["QC mode"] = "Advanced" if criteria.advanced else "USDA-inspired"
    rescan_frame["Batch"] = batch.batch_label
    statuses = sample_frame.get("Sample QC", pd.Series(dtype=str)).value_counts()
    overview = {
        "Total OPUS files": len(batch.inventory), "Identified samples": len(samples),
        "Unmatched files": len(batch.unmatched), "Read errors": len(batch.errors),
        **{status: int(statuses.get(status, 0))
           for status in ("Pass", "Review", "Fail", "Incomplete")},
        "Sample pass rate (%)": 100 * statuses.get("Pass", 0) / len(samples)
        if samples else None,
    }
    valid = sample_frame.loc[
        sample_frame["Sample QC"] != "Incomplete"
    ] if not sample_frame.empty else sample_frame
    diagnostics = []
    for column in ("Max NRMSE (%)", "Min similarity (%)"):
        values = valid.get(column, pd.Series(dtype=float)).dropna().to_numpy()
        if column == "Min similarity (%)":
            values = 1 - values / 100
        diagnostics.append({
            "Metric": column if column.startswith("Max") else "1 - Min Pearson r",
            "Valid sample groups": len(values),
            "Exploratory MAD threshold": mad_threshold(values),
            "Note": "Diagnostic only; not an acceptance limit",
        })
    settings = {
        "Directory": batch.directory, "Batch": batch.batch_label, "Pattern": batch.pattern,
        "Expected replicates": batch.expected, "Lower": batch.lower, "Upper": batch.upper,
        "Exclude CO2 globally": batch.exclude_co2, "OPUS mode": "native_npt",
        "Regions": str(batch.regions), "Criteria": str(asdict(criteria)),
        "Pearson threshold (%)": criteria.similarity, "Comparison": "strict >",
        "NRMSE denominator": "RMS of mean pair spectrum",
        "Threshold provenance": "User settings; NRMSE limits exploratory",
        "Absorbance block": "AB only",
        "Timestamp UTC": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "Overview": pd.DataFrame(list(overview.items()), columns=["Metric", "Value"]),
        "Sample QC": sample_frame, "Pairwise QC": pair_frame,
        "Regional QC": pd.DataFrame(regional), "File QC": file_frame,
        "Replicate Diagnosis": file_frame.copy(), "Rescan List": rescan_frame,
        "Review decisions": file_frame.reindex(columns=[
            "Sample ID", "File Name", "File Diagnosis", "Manual decision",
            "Manual reason", "Review timestamp",
        ]),
        "Settings": pd.DataFrame(list(settings.items()), columns=["Field", "Value"]),
        "Threshold diagnostics": pd.DataFrame(diagnostics),
    }


def report_bytes(tables):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in tables.items():
            if len(frame) > 1_048_575:
                raise ValueError(f"{name} exceeds Excel row capacity; reduce batch size.")
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            # Treat filenames/review notes as literal text, never spreadsheet formulas.
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"
    return buffer.getvalue()
