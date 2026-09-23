import pytest

from soil_mir.services.prediction import (
    load_model_bundle,
    sample_key_from_opus_filename,
)


def test_sample_key_from_numeric_opus_extension():
    assert (
        sample_key_from_opus_filename("202-46EF.2")
        == "202-46EF"
    )


def test_sample_key_preserves_non_opus_name():
    assert (
        sample_key_from_opus_filename("example.txt")
        == "example.txt"
    )


def test_invalid_model_bundle_is_rejected(tmp_path):
    import joblib

    path = tmp_path / "bad.joblib"
    joblib.dump(
        {"property_name": "STC"},
        path,
    )

    with pytest.raises(
        ValueError,
        match="missing required keys",
    ):
        load_model_bundle(path)
