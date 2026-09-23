from pathlib import Path

import pytest

from soil_mir.services.profiles import (
    list_profiles,
    load_profile,
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
