from __future__ import annotations

from pathlib import Path

from soil_mir.reporting import (
    export_final_refit,
    record_final_refit,
)
from soil_mir.services.calibration import (
    load_calibration_dataset,
    refit_final_model_only,
)
from soil_mir.services.history import (
    load_run_config,
)


def refit_saved_run_tolerance(
    run_dir: str | Path,
    *,
    property_name: str,
    method: str,
    tolerance_pct: float,
) -> dict:
    """Refit only the final all-data model for one saved run.

    The original run configuration, data paths, metadata-driven CO2 setting,
    and reference filters are reused. Outer validation is not rerun.
    """
    run_dir = Path(
        run_dir
    ).expanduser()
    run_config = load_run_config(
        run_dir
    )
    properties = list(
        run_config.get(
            "properties",
            [],
        )
    )
    methods = list(
        run_config.get(
            "methods",
            [],
        )
    )
    if property_name not in properties:
        raise ValueError(
            f"{property_name} is not part of the saved run."
        )
    if method not in methods:
        raise ValueError(
            f"{method} is not part of the saved run."
        )

    settings = dict(
        run_config.get(
            "analysis_settings",
            {},
        )
    )
    required = (
        "max_rank",
        "region_search_n_windows",
        "rmsecv_tolerance_pct",
        "sg_window",
        "sg_polyorder",
        "random_seed",
        "internal_cv_folds",
        "outer_cv_folds",
        "n_repeats",
        "validation_fraction",
        "ks_representation",
        "ks_pca_variance",
        "wn_min",
        "wn_max",
    )
    missing = [
        name
        for name in required
        if name not in settings
    ]
    if missing:
        raise ValueError(
            "Saved run configuration is missing analysis settings: "
            + ", ".join(missing)
        )

    source_tolerance = float(
        settings[
            "rmsecv_tolerance_pct"
        ]
    )
    tolerance_pct = float(
        tolerance_pct
    )
    settings[
        "rmsecv_tolerance_pct"
    ] = tolerance_pct
    settings.setdefault(
        "outer_n_jobs",
        1,
    )
    settings.setdefault(
        "inner_thread_limit",
        1,
    )
    settings.setdefault(
        "use_group_stratification",
        True,
    )

    output_dir = Path(
        run_config.get(
            "output_dir",
            run_dir.parent,
        )
    ).expanduser()
    reference_ranges = (
        run_config.get(
            "reference_ranges",
            {},
        )
        or {}
    )
    property_range = (
        reference_ranges.get(
            property_name,
            {},
        )
        or {}
    )

    dataset = load_calibration_dataset(
        run_config["spectra_dir"],
        run_config[
            "reference_excel"
        ],
        property_name,
        wn_min=float(
            settings["wn_min"]
        ),
        wn_max=float(
            settings["wn_max"]
        ),
        fallback_exclude_co2=bool(
            run_config.get(
                "fallback_exclude_co2",
                False,
            )
        ),
        cache_root=(
            output_dir
            / ".soil_mir_cache"
        ),
        ref_min=property_range.get(
            "min"
        ),
        ref_max=property_range.get(
            "max"
        ),
    )

    refit = refit_final_model_only(
        dataset,
        method=method,
        max_rank=int(
            settings["max_rank"]
        ),
        region_search_n_windows=int(
            settings[
                "region_search_n_windows"
            ]
        ),
        rmsecv_tolerance_pct=(
            tolerance_pct
        ),
        sg_window=int(
            settings["sg_window"]
        ),
        sg_polyorder=int(
            settings[
                "sg_polyorder"
            ]
        ),
        random_seed=int(
            settings["random_seed"]
        ),
        internal_cv_folds=int(
            settings[
                "internal_cv_folds"
            ]
        ),
        outer_cv_folds=int(
            settings[
                "outer_cv_folds"
            ]
        ),
        n_repeats=int(
            settings["n_repeats"]
        ),
        validation_fraction=float(
            settings[
                "validation_fraction"
            ]
        ),
        ks_representation=str(
            settings[
                "ks_representation"
            ]
        ),
        ks_pca_variance=float(
            settings[
                "ks_pca_variance"
            ]
        ),
        wn_min=float(
            settings["wn_min"]
        ),
        wn_max=float(
            settings["wn_max"]
        ),
        outer_n_jobs=int(
            settings[
                "outer_n_jobs"
            ]
        ),
        inner_thread_limit=(
            None
            if settings.get(
                "inner_thread_limit"
            )
            is None
            else int(
                settings[
                    "inner_thread_limit"
                ]
            )
        ),
        use_group_stratification=bool(
            settings[
                "use_group_stratification"
            ]
        ),
    )
    artifacts = export_final_refit(
        refit,
        run_dir,
        source_validation_tolerance_pct=(
            source_tolerance
        ),
    )
    record_final_refit(
        run_dir,
        refit,
        artifacts,
        source_validation_tolerance_pct=(
            source_tolerance
        ),
    )
    refit["artifacts"] = (
        artifacts
    )
    refit[
        "source_validation_tolerance_pct"
    ] = source_tolerance
    refit[
        "source_run_dir"
    ] = str(run_dir)
    return refit
