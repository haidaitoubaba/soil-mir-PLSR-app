from pathlib import Path

import pytest

from soil_mir.services.profiles import (
    delete_profile,
    list_profiles,
    load_profile,
    profile_widget_updates,
    save_profile,
)


def test_profile_round_trip(tmp_path: Path):
    settings = {
        "soil_mir_selected_properties": [
            "202_STC",
            "202_STN",
        ],
        "soil_mir_max_rank": 15,
        "soil_mir_validation_methods": [
            "kfold",
        ],
        "soil_mir_wn_range": [
            600,
            4000,
        ],
    }

    path = save_profile(
        tmp_path,
        "STC STN nested",
        settings,
    )
    loaded = load_profile(path)

    assert path.name == "STC_STN_nested.json"
    assert loaded == settings
    assert list(list_profiles(tmp_path)) == [
        "STC_STN_nested"
    ]


def test_invalid_profile_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(
        '{"version": 999, "settings": {}}',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported",
    ):
        load_profile(path)


def test_blank_profile_name_is_rejected(tmp_path: Path):
    with pytest.raises(
        ValueError,
        match="letters or numbers",
    ):
        save_profile(
            tmp_path,
            "!!!",
            {},
        )



def test_profile_widget_updates_restore_all_saved_controls():
    settings = {
        "soil_mir_selected_properties": ["202_STC"],
        "soil_mir_wn_range": [650, 3950],
        "soil_mir_exclude_co2": True,
        "soil_mir_max_rank": 9,
        "soil_mir_validation_methods": ["kfold"],
        "soil_mir_region_windows": 5,
        "soil_mir_tolerance": 2.5,
        "soil_mir_sg_window": 9,
        "soil_mir_sg_polyorder": 2,
        "soil_mir_random_seed": 77,
        "soil_mir_internal_cv_folds": 8,
        "soil_mir_outer_cv_folds": 4,
        "soil_mir_n_repeats": 12,
        "soil_mir_validation_fraction": 0.25,
        "soil_mir_ks_representation": "pca",
        "soil_mir_ks_pca_variance": 0.95,
        "soil_mir_outer_n_jobs": 4,
        "soil_mir_inner_thread_limit": 1,
        "soil_mir_reference_ranges": {
            "202_STC": {
                "min": 0.1,
                "max": 30.0,
            }
        },
    }

    updates = profile_widget_updates(
        settings,
        ["202_STC", "202_STN"],
    )

    assert updates["cfg_selected_properties"] == ["202_STC"]
    assert updates["cfg_wn_range"] == (650, 3950)
    assert updates["cfg_max_rank"] == 9
    assert updates["cfg_region_windows"] == 5
    assert updates["cfg_internal_cv_folds"] == 8
    assert updates["cfg_outer_cv_folds"] == 4
    assert updates["cfg_outer_n_jobs"] == 4
    assert updates["cfg_inner_thread_limit"] == 1
    assert updates["ref_min_202_STC"] == "0.1"
    assert updates["ref_max_202_STC"] == "30.0"
    assert updates["ref_min_202_STN"] == ""
    assert updates["ref_max_202_STN"] == ""



def test_delete_profile_removes_only_selected_profile(
    tmp_path: Path,
):
    first = save_profile(
        tmp_path,
        "first",
        {"soil_mir_max_rank": 5},
    )
    second = save_profile(
        tmp_path,
        "second",
        {"soil_mir_max_rank": 10},
    )
    history_dir = tmp_path / "20260924_010203"
    history_dir.mkdir()
    history_file = history_dir / "Run_Manifest.json"
    history_file.write_text(
        '{"status":"completed"}',
        encoding="utf-8",
    )

    deleted = delete_profile(
        tmp_path,
        "first",
    )

    assert deleted == first
    assert not first.exists()
    assert second.exists()
    assert history_file.exists()
    assert list(list_profiles(tmp_path)) == [
        "second"
    ]


def test_delete_missing_profile_is_rejected(
    tmp_path: Path,
):
    with pytest.raises(
        FileNotFoundError,
        match="Configuration profile not found",
    ):
        delete_profile(
            tmp_path,
            "missing",
        )
