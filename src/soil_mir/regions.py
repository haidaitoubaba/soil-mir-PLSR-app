from __future__ import annotations

import numpy as np
import pandas as pd

from soil_mir.io.opus import validate_wavenumbers


def validate_tolerance(value) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("RMSECV tolerance must be a finite nonnegative percentage.")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("RMSECV tolerance must be numeric; enter 2 for 2%.") from exc
    if not np.isfinite(value) or value < 0:
        raise ValueError("RMSECV tolerance must be finite and nonnegative.")
    return value


def validate_window_count(value) -> int:
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, np.integer))
        or not 1 <= value <= 16
    ):
        raise ValueError(
            "region_search_n_windows must be an integer from 1 to 16; search grows as 2**N - 1."
        )
    return int(value)


def automatic_region_definitions(cfg: dict, axis: np.ndarray) -> tuple[dict, list[dict]]:
    count = validate_window_count(cfg.get("region_search_n_windows", 10))
    edges = np.linspace(axis.min(), axis.max(), count + 1)
    membership = np.clip(np.searchsorted(edges, axis, side="right") - 1, 0, count - 1)
    windows = []
    for index in range(count):
        points = axis[membership == index]
        if len(points) < 2:
            raise ValueError(
                f"Automatic window {index + 1} has fewer than two retained coordinates; "
                "reduce region_search_n_windows."
            )
        windows.append(
            {
                "Window": f"W{index + 1:02d}",
                "Grid Lower": float(edges[index]),
                "Grid Upper": float(edges[index + 1]),
                "Actual Lower": float(points.min()),
                "Actual Upper": float(points.max()),
                "Spectral Points": len(points),
            }
        )
    definitions = {}
    for bits in range(1, (1 << count) - 1):
        chosen = [window for i, window in enumerate(windows) if bits & (1 << i)]
        definitions[" + ".join(window["Window"] for window in chosen)] = [
            (window["Actual Lower"], window["Actual Upper"]) for window in chosen
        ]
    return definitions, windows


def prepare_region_config(cfg: dict, wavenumbers: np.ndarray) -> dict:
    axis = validate_wavenumbers(wavenumbers)
    automatic, windows = automatic_region_definitions(cfg, axis)
    definitions = {"Full range": [(cfg["wn_min"], cfg["wn_max"])], **automatic}
    regions = {}
    step = float(np.median(np.abs(np.diff(axis))))
    for name, intervals in definitions.items():
        mask = np.zeros(len(axis), dtype=bool)
        requested = []
        for interval in intervals:
            if len(interval) != 2 or not np.isfinite(interval).all():
                raise ValueError(f"Invalid interval in region {name!r}: {interval}")
            low, high = sorted(map(float, interval))
            if low == high:
                raise ValueError(f"Region {name!r} contains a zero-width interval.")
            requested.append([low, high])
            mask |= (axis >= low) & (axis <= high)
        indices = np.flatnonzero(mask)
        selected_axis = axis[indices]
        breaks = (np.diff(indices) > 1) | (np.abs(np.diff(selected_axis)) > 1.5 * step)
        segments = np.split(selected_axis, np.flatnonzero(breaks) + 1) if len(indices) else []
        lengths = [len(segment) for segment in segments]
        actual = [[float(segment[0]), float(segment[-1])] for segment in segments]
        description = "; ".join(f"{a:.6f}–{b:.6f}" for a, b in actual) or "No retained points"
        reason = (
            ""
            if lengths and min(lengths) >= cfg["sg_window"]
            else "An included interval has fewer points than sg_window."
        )
        regions[name] = {
            "indices": indices,
            "segment_lengths": lengths,
            "intervals": actual,
            "requested_intervals": requested,
            "label": description,
            "error": reason,
        }
    if all(region["error"] for region in regions.values()):
        raise ValueError("No candidate region has sufficiently long spectral intervals.")
    return dict(
        cfg,
        _regions=regions,
        _region_windows=windows,
        _search_wavenumbers=axis.copy(),
    )


def select_region(X: np.ndarray, cfg: dict, name: str) -> tuple[np.ndarray, dict]:
    region = cfg["_regions"][name]
    if region["error"]:
        raise ValueError(region["error"])
    return X[:, region["indices"]], dict(cfg, _segment_lengths=region["segment_lengths"])


def choose_with_tolerance(frame: pd.DataFrame, error_column: str, tolerance: float) -> tuple:
    tolerance = validate_tolerance(tolerance)
    eligible = frame[np.isfinite(frame[error_column]) & (frame[error_column] >= 0)].copy()
    if "Eligible" in eligible:
        eligible = eligible[eligible["Eligible"]]
    if eligible.empty:
        raise RuntimeError("No eligible finite candidate is available for selection.")
    minimum = float(eligible[error_column].min())
    threshold = minimum * (1 + tolerance / 100)
    within = eligible[eligible[error_column] <= threshold]
    best = within.sort_values(["Rank", error_column, "Preprocessing", "Region"]).iloc[0]
    increase = 100 * (float(best[error_column]) / minimum - 1) if minimum > 0 else 0.0
    return best, {
        "Tolerance (%)": tolerance,
        "Minimum RMSECV": minimum,
        "Allowed RMSECV": threshold,
        "RMSECV Increase (%)": increase,
    }
