import numpy as np
import pandas as pd

from legacy_modeling_reference import (
    build_cv_preprocessing_cache,
    build_cv_response_cache,
    cv_rank_path,
)
from legacy_reference import PREPROCESSING_NAMES, grouped_splits
from soil_mir.regions import (
    choose_with_tolerance,
    region_metadata,
    select_region,
)


def legacy_optimize_plsr_grouped(
    X,
    y_original,
    groups,
    strata,
    cfg,
    transform_method,
    random_state,
):
    splits, _ = grouped_splits(
        groups,
        strata,
        cfg["internal_cv_folds"],
        random_state,
    )
    responses = build_cv_response_cache(
        y_original,
        splits,
        transform_method,
    )
    records = []
    windows = tuple(
        window["Window"]
        for window in cfg["_region_windows"]
    )
    maximum_rank = int(cfg["max_rank"])

    for prep in PREPROCESSING_NAMES:
        evaluated = {}

        def evaluate(chosen):
            name = (
                "Full range"
                if len(chosen) == len(windows)
                else " + ".join(chosen)
            )
            if name in evaluated:
                return evaluated[name]
            region = cfg["_regions"][name]
            try:
                region_X, region_cfg = select_region(
                    X,
                    cfg,
                    name,
                )
                cache = build_cv_preprocessing_cache(
                    region_X,
                    splits,
                    prep,
                    region_cfg,
                )
                _, results = cv_rank_path(
                    cache,
                    y_original,
                    groups,
                    maximum_rank,
                    transform_method,
                    responses,
                )
            except Exception as exc:
                results = [
                    (None, str(exc))
                ] * maximum_rank

            scores = []
            for rank, (metrics, error) in enumerate(
                results,
                1,
            ):
                record = {
                    **region_metadata(name, region),
                    "Preprocessing": prep,
                    "Rank": rank,
                    "Windows Retained": len(chosen),
                    "RMSECV": np.nan,
                    "R2_CV": np.nan,
                    "RPIQ_CV": np.nan,
                    "Bias_CV": np.nan,
                    "Status": "Failed",
                    "Error": error,
                }
                if metrics is not None:
                    record.update(
                        RMSECV=metrics["RMSE"],
                        R2_CV=metrics["R2"],
                        RPIQ_CV=metrics["RPIQ"],
                        Bias_CV=metrics["Bias"],
                        Status="Success",
                    )
                    scores.append(metrics["RMSE"])
                records.append(record)

            evaluated[name] = (
                min(scores) if scores else np.inf
            )
            return evaluated[name]

        current = windows
        evaluate(current)
        while len(current) > 1:
            children = [
                tuple(
                    window
                    for window in current
                    if window != removed
                )
                for removed in current
            ]
            ranked = [
                (evaluate(child), child)
                for child in children
            ]
            score, current = min(
                ranked,
                key=lambda item: (item[0], item[1]),
            )
            if not np.isfinite(score):
                break

    frame = pd.DataFrame(records)
    row, decision = choose_with_tolerance(
        frame,
        "RMSECV",
        cfg.get("rmsecv_tolerance_pct", 2.0),
    )
    best = {
        **row.to_dict(),
        **decision,
        "RMSE": float(row["RMSECV"]),
        "Rank": int(row["Rank"]),
    }
    frame["Within Tolerance"] = (
        np.isfinite(frame["RMSECV"])
        & (
            frame["RMSECV"]
            <= decision["Allowed RMSECV"]
        )
    )
    frame["Selected"] = False
    frame.loc[row.name, "Selected"] = True
    frame["Tolerance (%)"] = decision["Tolerance (%)"]
    return frame, best
