import pytest

from soil_mir.config import AnalysisConfig, SpectralConfig, ValidationConfig


def test_default_config_valid_without_paths():
    AnalysisConfig().validate(check_paths=False)


def test_sg_window_must_be_odd():
    with pytest.raises(ValueError, match="odd"):
        SpectralConfig(sg_window=10).validate()


def test_validation_method_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown"):
        ValidationConfig(methods=("unknown",)).validate()
