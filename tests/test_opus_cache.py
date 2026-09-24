import os
from pathlib import Path

import numpy as np

from soil_mir.io import cache as opus_cache


def _fake_reader(path):
    path = Path(path)
    value = float(path.suffix[1:])
    axis = np.linspace(600, 4000, 16)
    return np.full(16, value), axis


def test_opus_cache_reuses_unchanged_files(tmp_path, monkeypatch):
    spectra = tmp_path / "spectra"
    cache_root = tmp_path / "cache"
    spectra.mkdir()
    (spectra / "sample.0").write_bytes(b"a")
    (spectra / "sample.1").write_bytes(b"b")

    calls = []

    def reader(path):
        calls.append(Path(path).name)
        return _fake_reader(path)

    monkeypatch.setattr(opus_cache, "read_opus_spectrum", reader)

    first, first_stats = opus_cache.load_opus_spectra_cached(
        spectra,
        ["sample.0", "sample.1"],
        cache_root=cache_root,
    )
    second, second_stats = opus_cache.load_opus_spectra_cached(
        spectra,
        ["sample.0", "sample.1"],
        cache_root=cache_root,
    )

    assert first_stats.hits == 0
    assert first_stats.misses == 2
    assert second_stats.hits == 2
    assert second_stats.misses == 0
    assert calls == ["sample.0", "sample.1"]
    np.testing.assert_array_equal(
        first["sample.0"][0],
        second["sample.0"][0],
    )


def test_opus_cache_invalidates_changed_file(tmp_path, monkeypatch):
    spectra = tmp_path / "spectra"
    cache_root = tmp_path / "cache"
    spectra.mkdir()
    target = spectra / "sample.0"
    target.write_bytes(b"a")

    calls = []

    def reader(path):
        calls.append(Path(path).name)
        return _fake_reader(path)

    monkeypatch.setattr(opus_cache, "read_opus_spectrum", reader)

    opus_cache.load_opus_spectra_cached(
        spectra,
        ["sample.0"],
        cache_root=cache_root,
    )

    target.write_bytes(b"changed")
    stat = target.stat()
    os.utime(
        target,
        ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000),
    )

    _, stats = opus_cache.load_opus_spectra_cached(
        spectra,
        ["sample.0"],
        cache_root=cache_root,
    )

    assert stats.hits == 0
    assert stats.misses == 1
    assert calls == ["sample.0", "sample.0"]


def test_cache_path_is_stable_per_directory(tmp_path):
    root = tmp_path / "cache"
    one = opus_cache.cache_path_for_directory(
        root,
        tmp_path / "spectra_a",
    )
    two = opus_cache.cache_path_for_directory(
        root,
        tmp_path / "spectra_a",
    )
    other = opus_cache.cache_path_for_directory(
        root,
        tmp_path / "spectra_b",
    )

    assert one == two
    assert one != other
