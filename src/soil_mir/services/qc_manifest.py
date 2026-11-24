"""Auditable, local QC snapshots and explicit calibration selections."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from soil_mir import __version__
from soil_mir.qc import Criteria, Scan, group_filenames

SCHEMA = 1
DECISIONS = {"Pending review", "Keep", "Exclude", "Rescan required"}


def read_mapping(source, *, excel=False):
    """Read only identity columns; preserve textual identifiers and exact filenames."""
    reader = pd.read_excel if excel else pd.read_csv
    frame = reader(source, dtype=str, keep_default_na=False)
    required = {"File Name", "Sample"}
    if not required <= set(frame.columns):
        raise ValueError("Mapping needs File Name and Sample; Replicate is recommended.")
    for column in ("Lab", "Instrument", "Batch"):
        if column in frame and frame[column].nunique() > 1:
            raise ValueError(f"Mapping contains multiple {column} values. Run separate batches.")
    result = {}
    for row in frame.to_dict("records"):
        name, sample = row["File Name"], row["Sample"]
        if not name or not sample.strip() or name in result:
            raise ValueError(f"Empty or duplicate mapping identity: {name!r}")
        rep = row.get("Replicate", "").strip()
        if rep and not rep.isdigit():
            raise ValueError(f"Replicate must be numeric: {name}")
        result[name] = {"sample": sample, "replicate": int(rep) if rep else 0,
                        "well": row.get("Well", "")}
    return result


def resolve_groups(names, pattern, mapping=None):
    if mapping is None:
        return group_filenames(names, pattern)
    unknown = set(mapping) - set(names)
    if unknown:
        raise ValueError(f"Mapping references absent filenames: {sorted(unknown)[:10]}")
    groups = defaultdict(list)
    for name in sorted(mapping):
        row = mapping[name]
        groups[row["sample"]].append(Scan(name, row["sample"], row["replicate"], row["well"]))
    return dict(groups), sorted(set(names) - set(mapping)), "Explicit mapping"


def criteria_dict(criteria):
    return {
        "similarity": criteria.similarity, "advanced": criteria.advanced,
        "nrmse_pass": criteria.nrmse_pass, "nrmse_fail": criteria.nrmse_fail,
        "regional_limits": [
            [list(region), list(limits)] for region, limits in sorted(
                criteria.regional_limits.items()
            )
        ],
    }


def criteria_from_dict(payload):
    data = dict(payload)
    data["regional_limits"] = {
        tuple(region): tuple(limits) for region, limits in data.get("regional_limits", [])
    }
    return Criteria(**data)


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def manifest_id(payload):
    return hashlib.sha256(canonical({
        key: value for key, value in payload.items() if key != "manifest_id"
    }).encode("utf-8")).hexdigest()


def input_settings(batch):
    return {
        "directory": batch.directory, "pattern": batch.pattern, "batch_label": batch.batch_label,
        "expected": batch.expected, "lower": batch.lower, "upper": batch.upper,
        "exclude_co2": batch.exclude_co2, "regions": [list(r) for r in batch.regions],
        "mapping": batch.mapping, "opus_axis_mode": "native_npt",
    }


def _inventory(directory):
    # Lazy import avoids a dependency cycle.
    from soil_mir.services.spectral_qc import file_inventory

    return file_inventory(directory)


def fingerprints(batch):
    if _inventory(batch.directory) != batch.inventory:
        raise ValueError("OPUS files changed since QC; rerun before saving.")
    result = []
    for name, size, mtime in batch.inventory:
        result.append({"filename": name, "size": size, "mtime_ns": mtime,
                       "sha256": digest_file(Path(batch.directory) / name)})
    if _inventory(batch.directory) != batch.inventory:
        raise ValueError("OPUS files changed during fingerprinting; rerun QC.")
    return result


def build_manifest(batch, criteria, tables, decisions, *, freeze=False,
                   min_retained=2, allow_single=False):
    names = {row[0] for row in batch.inventory}
    if set(decisions) - names:
        raise ValueError("Review contains files outside the batch.")
    for name, decision in decisions.items():
        choice = decision.get("decision")
        if choice not in DECISIONS:
            raise ValueError(f"Invalid review decision for {name}")
        if choice != "Pending review" and not decision.get("reason", "").strip():
            raise ValueError(f"Missing explicit review reason for {name}")
    groups = {scan.filename: {"sample": scan.sample, "replicate": scan.replicate,
                             "well": scan.well}
              for scans in batch.groups.values() for scan in scans}
    statuses = dict(zip(tables["Sample QC"].get("Sample ID", []),
                        tables["Sample QC"].get("Sample QC", [])))
    file_status = dict(zip(tables["File QC"]["File Name"], tables["File QC"]["File Diagnosis"]))
    retained, excluded, pending = [], [], []
    for name in sorted(names):
        decision = decisions.get(name, {})
        choice = decision.get("decision", "Pending review")
        sample = groups.get(name, {}).get("sample")
        if choice in {"Exclude", "Rescan required"}:
            excluded.append(name)
        elif choice == "Keep":
            if sample is None or file_status[name] == "Invalid":
                raise ValueError(f"Unmatched or unreadable file cannot be approved: {name}")
            retained.append(name)
        elif statuses.get(sample) == "Pass":
            retained.append(name)  # only frozen by explicit batch confirmation
        else:
            pending.append(name)
    counts = {sample: 0 for sample in batch.groups}
    for name in retained:
        counts[groups[name]["sample"]] += 1
    if min_retained < 2:
        raise ValueError("Minimum retained replicates must be at least 2.")
    exceptions = [sample for sample, count in counts.items() if 0 < count < min_retained]
    if freeze:
        if pending:
            raise ValueError(f"{len(pending)} unresolved files; review or exclude them first.")
        if not retained:
            raise ValueError("No retained spectra.")
        for sample in exceptions:
            keep = [name for name in retained if groups[name]["sample"] == sample]
            if (not allow_single or len(keep) != 1
                    or decisions.get(keep[0], {}).get("decision") != "Keep"):
                raise ValueError(f"Insufficient retained spectra for {sample}; review the sample.")
    payload = {
        "schema": SCHEMA, "software_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input": input_settings(batch), "criteria": criteria_dict(criteria),
        "files": fingerprints(batch), "groups": groups, "decisions": decisions,
        "automatic_results": {
            name: json.loads(tables[name].to_json(orient="records", double_precision=15))
            for name in ("Sample QC", "Pairwise QC", "Regional QC", "File QC", "Rescan List")
        },
        "selection": {
            "frozen": freeze, "retained": retained, "excluded": excluded, "pending": pending,
            "retained_counts": counts, "min_retained": min_retained,
            "single_exceptions": exceptions if freeze else [],
        },
    }
    payload["manifest_id"] = manifest_id(payload)
    return payload


def save_manifest(path, payload):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
    return path


def read_manifest(path):
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("Unsupported QC manifest schema.")
    if payload.get("manifest_id") != manifest_id(payload):
        raise ValueError("QC manifest content does not match its fingerprint.")
    return payload


def validate_manifest(payload, directory, *, frozen=False):
    if payload.get("schema") != SCHEMA or payload.get("manifest_id") != manifest_id(payload):
        raise ValueError("Invalid QC manifest identity.")
    directory = str(Path(directory).expanduser().resolve())
    if directory != payload["input"]["directory"]:
        raise ValueError("QC manifest belongs to a different OPUS folder.")
    if frozen and not payload["selection"]["frozen"]:
        raise ValueError("QC selection is not frozen and approved.")
    expected = {item["filename"]: item for item in payload["files"]}
    inventory = _inventory(directory)
    if set(expected) != {name for name, _, _ in inventory}:
        raise ValueError("OPUS folder membership changed; QC review is stale.")
    for name, size, _mtime in inventory:
        row = expected[name]
        if size != row["size"] or digest_file(Path(directory) / name) != row["sha256"]:
            raise ValueError(f"OPUS file content changed: {name}")
    if _inventory(directory) != inventory:
        raise ValueError("OPUS files changed during validation.")
    return payload


def filter_reference(frame, columns, payload):
    """Filter exact file names; never replace authoritative reference Sample IDs."""
    retained = set(payload["selection"]["retained"])
    excluded = set(payload["selection"]["excluded"])
    names = frame[columns.reference_file].astype(str)
    samples = frame[columns.sample_id].astype(str)
    unknown = set(names) - retained - excluded
    if unknown:
        raise ValueError(f"Reference contains files not covered by QC: {sorted(unknown)[:5]}")
    for name, sample in zip(names, samples):
        group = payload["groups"].get(name)
        if group is not None and group["sample"] != sample:
            raise ValueError(f"QC Sample ID conflicts with reference for {name}; correct mapping.")
    filtered = frame.loc[names.isin(retained)].copy()
    if filtered.empty:
        raise ValueError("No reference rows retained by the QC selection.")
    return filtered, int((~names.isin(retained)).sum())
