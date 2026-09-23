from pathlib import Path

import brukeropusreader

from soil_mir.io.opus import inspect_opus_directory


def test_science_dependency_is_installable():
    assert brukeropusreader is not None


def test_opus_directory_detection_uses_numeric_extensions(tmp_path: Path):
    (tmp_path / "sample_1.0").write_bytes(b"not parsed in this unit test")
    (tmp_path / "sample_1.1").write_bytes(b"not parsed in this unit test")
    (tmp_path / "notes.txt").write_text("ignore me")
    summary = inspect_opus_directory(tmp_path)
    assert summary.file_count == 2
    assert summary.filenames == ("sample_1.0", "sample_1.1")
