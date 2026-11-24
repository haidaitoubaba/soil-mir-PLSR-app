"""Independent, reference-free spectral repeatability diagnostics."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from soil_mir.io.opus import resample_spectrum, validate_wavenumbers

PATTERNS = {
    "NSSH": r"(?P<sample>.+)_(?P<replicate>[0-9]+)_(?P<well>[A-Za-z]+[0-9]+)\.[0-9]+",
    "Sample_Replicate": r"(?P<sample>.+)_(?P<replicate>[0-9]+)\.[0-9]+",
}
REGIONS = (
    (3600, 4000), (3000, 3600), (2800, 3000),
    (2300, 2400), (1500, 1800), (600, 1500), (400, 600),
)


@dataclass(frozen=True)
class Scan:
    filename: str
    sample: str
    replicate: int
    well: str = ""


@dataclass(frozen=True)
class Criteria:
    similarity: float = 99.6
    advanced: bool = False
    nrmse_pass: float = 2.0
    nrmse_fail: float = 5.0
    regional_limits: dict = field(default_factory=dict)

    def __post_init__(self):
        if not np.isfinite(self.similarity) or not 0 <= self.similarity < 100:
            raise ValueError("Similarity must be in [0, 100).")
        if not 0 < self.nrmse_pass < self.nrmse_fail < np.inf:
            raise ValueError("NRMSE thresholds must be positive, finite and ordered.")
        for region, limits in self.regional_limits.items():
            if not isinstance(region, tuple) or len(region) != 2:
                raise ValueError("Region must be a (lower, upper) tuple.")
            if not 0 < limits[0] < limits[1] < np.inf:
                raise ValueError("Regional thresholds must be positive, finite and ordered.")


def parse_filename(filename: str, pattern: str) -> Scan | None:
    """Numeric OPUS extension is never used as replicate ID."""
    if not re.search(r"\.[0-9]+$", filename):
        return None
    expression = re.compile(PATTERNS.get(pattern, pattern))
    if not {"sample", "replicate"} <= expression.groupindex.keys():
        raise ValueError("Pattern must contain named sample and replicate groups.")
    match = expression.fullmatch(filename)
    if not match:
        return None
    fields = match.groupdict()
    sample, replicate = fields["sample"], fields["replicate"]
    if not sample or not replicate or not re.fullmatch(r"[0-9]+", replicate):
        return None
    return Scan(filename, sample, int(replicate), fields.get("well") or "")


def group_filenames(filenames, pattern="Auto"):
    """Do not mix naming rules or infer sample identity from input order."""
    names = sorted(set(filenames))
    if pattern == "Auto":
        candidates = [
            (name, [parse_filename(filename, name) for filename in names])
            for name in PATTERNS
        ]
        scores = [sum(scan is not None for scan in scans) for _, scans in candidates]
        best = max(scores)
        winners = [candidate for candidate, score in zip(candidates, scores) if score == best]
        if len(winners) > 1 and winners[0][1] != winners[1][1]:
            raise ValueError("Ambiguous filename pattern; select an explicit rule.")
        pattern = winners[0][0]
    groups = defaultdict(list)
    unmatched = []
    for filename in names:
        scan = parse_filename(filename, pattern)
        if scan is None:
            unmatched.append(filename)
        else:
            groups[scan.sample].append(scan)
    return dict(groups), unmatched, pattern


def group_issues(scans, expected=3):
    if not isinstance(expected, int) or expected < 2:
        raise ValueError("Expected replicates must be an integer >= 2.")
    ids = [scan.replicate for scan in scans]
    wanted = set(range(1, expected + 1))
    missing = sorted(wanted - set(ids))
    extra = sorted(set(ids) - wanted)
    duplicate = sorted({rep for rep in ids if ids.count(rep) > 1})
    return {"missing": missing, "extra": extra, "duplicate": duplicate}


def align_group(spectra, lower=600., upper=4000.):
    """Align only within full requested coverage, never extrapolate."""
    if not np.isfinite([lower, upper]).all() or lower >= upper or not spectra:
        raise ValueError("Invalid QC range or empty group.")
    axes = {}
    steps = []
    for name, (values, raw_axis) in sorted(spectra.items()):
        axis = validate_wavenumbers(raw_axis)
        values = np.asarray(values, dtype=float)
        if values.shape != axis.shape or not np.isfinite(values).all():
            raise ValueError(f"Invalid spectrum: {name}")
        if axis.min() > lower or axis.max() < upper:
            raise ValueError(f"Requested range not fully covered: {name}")
        if axis[0] > axis[-1]:
            axis = axis[::-1]
        intervals = np.diff(axis)
        step = float(np.median(intervals))
        if not np.allclose(intervals, step, rtol=1e-5, atol=1e-8):
            raise ValueError(f"Irregular wavenumber grid: {name}")
        steps.append(step)
        axes[name] = axis
    if max(steps) > 2 * min(steps):
        raise ValueError("Resolution differs by more than 2x; review required.")
    first = next(iter(axes.values()))
    if all(np.array_equal(first, axis) for axis in axes.values()):
        grid = first[(first >= lower) & (first <= upper)]
    else:
        # Select the coarsest spacing and never oversample.
        count = int(np.floor((upper - lower) / max(steps))) + 1
        grid = np.linspace(lower, upper, count)
    if len(grid) < 2:
        raise ValueError("Insufficient points in requested range.")
    aligned = {
        name: resample_spectrum(values, axis, grid)
        for name, (values, axis) in spectra.items()
    }
    return grid, aligned


def pair_metrics(x, y, axis, *, exclude_co2=False, regions=REGIONS):
    axis = validate_wavenumbers(axis)
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (x.shape != axis.shape or y.shape != axis.shape
            or not np.isfinite(x).all() or not np.isfinite(y).all()):
        raise ValueError("Invalid paired spectra.")
    regional = {}
    regional_info = {}
    for low, high in regions:
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError("Invalid regional bounds.")
        mask = (axis >= low) & (axis <= high)
        complete = axis.min() <= low and axis.max() >= high
        # Same-grid cropping can omit less than one native step at each end.
        step = float(np.median(np.abs(np.diff(axis))))
        complete = complete or (axis.min() - low < step and high - axis.max() < step)
        regional_info[(low, high)] = (
            float(axis[mask].min()) if mask.any() else None,
            float(axis[mask].max()) if mask.any() else None,
            int(mask.sum()),
        )
        regional[(low, high)] = (
            float(np.sqrt(np.mean((x[mask] - y[mask]) ** 2)))
            if complete and mask.sum() >= 2 else None
        )
    if exclude_co2:
        keep = (axis < 2300) | (axis > 2400)
        x, y = x[keep], y[keep]
    if len(x) < 2:
        raise ValueError("Insufficient global QC points.")
    xc, yc = x - x.mean(), y - y.mean()
    denom = np.linalg.norm(xc) * np.linalg.norm(yc)
    rms_mean = float(np.sqrt(np.mean(((x + y) / 2) ** 2)))
    norm = np.linalg.norm(x) * np.linalg.norm(y)
    if min(denom, norm, rms_mean) <= 1e-12:
        raise ValueError("Constant spectrum or near-zero metric denominator.")
    delta = x - y
    rmse = float(np.sqrt(np.mean(delta**2)))
    return {
        "r": float(np.clip(np.dot(xc, yc) / denom, -1, 1)),
        "rmse": rmse,
        "nrmse": 100 * rmse / rms_mean,
        "sam": float(np.degrees(np.arccos(np.clip(np.dot(x, y) / norm, -1, 1)))),
        "mean_difference": float(delta.mean()),
        "points": len(x),
        "regional": regional,
        "regional_info": regional_info,
    }


def classify_pair(metrics, criteria):
    """Classify unrounded metrics; retain all triggered reasons."""
    if metrics is None:
        return "Invalid", ["Metrics unavailable"]
    if not np.isfinite([metrics["r"], metrics["nrmse"]]).all():
        return "Invalid", ["Non-finite metrics"]
    reasons = []
    status = "Pass"
    if metrics["r"] <= criteria.similarity / 100:
        status = "Fail"
        reasons.append("Similarity at or below threshold")
    if criteria.advanced:
        nrmse = metrics["nrmse"]
        if nrmse > criteria.nrmse_pass:
            reasons.append("NRMSE exceeds pass threshold")
            if nrmse > criteria.nrmse_fail:
                status = "Fail"
            elif status == "Pass":
                status = "Review"
        for region, (pass_limit, fail_limit) in criteria.regional_limits.items():
            value = metrics.get("regional", {}).get(region)
            if value is None or not np.isfinite(value):
                return "Invalid", reasons + [f"Region {region} unavailable"]
            if value > pass_limit:
                reasons.append(f"Region {region} exceeds pass threshold")
                if value > fail_limit:
                    status = "Fail"
                elif status == "Pass":
                    status = "Review"
    return status, reasons


def compare_strategies(scans, entries, threshold, expected=3):
    """Same raw Pearson coefficients; only the required edge sets differ.

    Reference is replicate ID 1, never the first filename or first readable scan.
    An incomplete group is not silently accepted under either strategy.
    """
    ref = [s.filename for s in scans if s.replicate == 1]
    reference = ref[0] if len(ref) == 1 else ""
    names = {s.filename for s in scans}
    wanted = {tuple(sorted(pair)) for pair in combinations(names, 2)}
    metrics = {}
    for a, b, m, _ in entries:
        value = None if m is None else m.get("r")
        metrics[tuple(sorted((a.filename, b.filename)))] = (
            float(value) if value is not None and np.isfinite(value) else None
        )
    complete = (len(scans) == len(names) == expected and not any(
        group_issues(scans, expected).values()
    ) and len(entries) == len(metrics) and set(metrics) == wanted)
    reference_edges = [key for key in metrics if reference and reference in key]
    valid = complete and all(v is not None for v in metrics.values())
    ref_valid = complete and len(reference_edges) == expected - 1 and all(
        metrics[key] is not None for key in reference_edges
    )
    ref_passes = sum(metrics[key] is not None and metrics[key] > threshold / 100
                     for key in reference_edges)
    all_passes = sum(v is not None and v > threshold / 100 for v in metrics.values())
    ref_status = ("Pass" if ref_passes == expected - 1 else "Not pass") if ref_valid else (
        "Incomplete"
    )
    all_status = ("Pass" if all_passes == len(wanted) else "Not pass") if valid else (
        "Incomplete"
    )
    comparable = valid and ref_valid
    agreement = ("Agree" if ref_status == all_status else "Disagree") if comparable else (
        "Not comparable"
    )
    ref_values = [metrics[key] for key in reference_edges if metrics[key] is not None]
    all_values = [v for v in metrics.values() if v is not None]
    return {
        "Reference file": reference,
        "USDA-style status": ref_status,
        "USDA-style pairs passed": ref_passes,
        "USDA-style expected pairs": expected - 1,
        "USDA-style min similarity (%)": 100 * min(ref_values) if ref_valid else None,
        "All-pairwise Pearson status": all_status,
        "All-pairwise Pearson pairs passed": all_passes,
        "All-pairwise expected pairs": expected * (expected - 1) // 2,
        "All-pairwise Pearson min similarity (%)": 100 * min(all_values) if valid else None,
        "Method agreement": agreement,
        "Replicate 1 suspected (Pearson)": bool(
            valid and expected == 3 and all_passes == 1 and ref_passes == 0
        ),
    }


def diagnose(scans, pairs, expected=3):
    """Return shared sample and file-level decisions from classified edges.

    Each edge is (filename_a, filename_b, status). No unique attribution for
    incomplete, invalid, or non-triple groups.
    """
    names = sorted(scan.filename for scan in scans)
    issues = group_issues(scans, expected)
    wanted = {tuple(sorted(pair)) for pair in combinations(names, 2)}
    edges = {tuple(sorted((a, b))): status for a, b, status in pairs}
    allowed = {"Pass", "Review", "Fail", "Invalid"}
    complete = (len(names) == expected and len(set(names)) == len(names)
                and not any(issues.values()) and set(edges) == wanted
                and len(pairs) == len(edges)
                and all(status in allowed - {"Invalid"} for status in edges.values()))
    passed = [edge for edge, status in edges.items() if status == "Pass"]
    nonpassing = [edge for edge, status in edges.items() if status != "Pass"]
    suspect = None
    candidates = []
    files = {name: "Undetermined" for name in names}
    if not complete:
        status = "Incomplete"
        action = "Resolve grouping or invalid input, then rerun"
        files = {name: "Review required" for name in names}
    elif len(passed) == len(wanted):
        status = "Pass"
        action = "Keep all"
        files = {name: "Consistent" for name in names}
    elif all(value == "Fail" for value in edges.values()):
        status = "Fail"
        action = "Review or rescan entire sample"
        candidates = names
    else:
        status = "Review"
        action = "Review non-passing comparisons"
        candidates = sorted({name for edge in nonpassing for name in edge})
        if expected == 3 and len(passed) == 1:
            suspect = next(name for name in names if name not in passed[0])
            candidates = [suspect]
            files = {name: "Mutually consistent" for name in names}
            files[suspect] = "Suspected"
            action = "Review or rescan suspected file"
        elif expected == 3 and len(passed) == 2:
            files = {name: ("Review candidate" if name in candidates
                            else "Not uniquely implicated") for name in names}
            action = "Inspect both files in non-passing pair"
        elif not passed:
            action = "Inspect or rescan entire sample"
    return {
        "status": status, "passed": len(passed), "expected_pairs": expected*(expected-1)//2,
        "suspected_file": suspect,
        "suspected_replicate": next((s.replicate for s in scans if s.filename == suspect), None),
        "review_candidates": candidates, "action": action, "files": files, **issues,
    }


def mad_threshold(values, k=3., minimum=20):
    """Exploratory only; never an implicit acceptance limit."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < minimum:
        return None
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        return None
    return float(median + k * 1.4826 * mad)
