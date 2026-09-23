from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import joblib
import numpy as np

from soil_mir.io.opus import read_opus_spectrum, validate_wavenumbers


CACHE_VERSION = 1


@dataclass(frozen=True)
class OpusCacheStats:
    hits: int
    misses: int
    requested: int
    cache_path: Path | None


def _file_signature(path: Path) -> dict:
    stat = path.stat()
    return {
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def cache_path_for_directory(
    cache_root: str | Path,
    spectra_dir: str | Path,
) -> Path:
    root = Path(cache_root).expanduser()
    directory = Path(spectra_dir).expanduser().resolve()
    digest = sha256(str(directory).encode("utf-8")).hexdigest()[:16]
    return root / f"opus_{digest}.joblib"


def _empty_cache(directory: Path) -> dict:
    return {
        "version": CACHE_VERSION,
        "spectra_dir": str(directory),
        "entries": {},
    }


def _load_cache(path: Path, directory: Path) -> dict:
    if not path.is_file():
        return _empty_cache(directory)
    try:
        payload = joblib.load(path)
    except Exception:
        return _empty_cache(directory)
    if (
        not isinstance(payload, dict)
        or payload.get("version") != CACHE_VERSION
        or payload.get("spectra_dir") != str(directory)
        or not isinstance(payload.get("entries"), dict)
    ):
        return _empty_cache(directory)
    return payload


def _valid_entry(entry: dict, signature: dict) -> bool:
    if not isinstance(entry, dict) or entry.get("signature") != signature:
        return False
    try:
        values = np.asarray(entry["values"], dtype=float)
        axis = validate_wavenumbers(entry["axis"])
    except Exception:
        return False
    return (
        values.ndim == 1
        and values.shape == axis.shape
        and np.isfinite(values).all()
    )


def _save_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(payload, temporary, compress=3)
    temporary.replace(path)


def load_opus_spectra_cached(
    spectra_dir: str | Path,
    filenames: list[str] | tuple[str, ...],
    cache_root: str | Path | None = None,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], OpusCacheStats]:
    directory = Path(spectra_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"OPUS directory not found: {directory}")

    requested = tuple(dict.fromkeys(str(name) for name in filenames))
    cache_path = (
        cache_path_for_directory(cache_root, directory)
        if cache_root is not None
        else None
    )
    payload = (
        _load_cache(cache_path, directory)
        if cache_path is not None
        else _empty_cache(directory)
    )

    spectra = {}
    hits = 0
    misses = 0
    changed = False

    for name in requested:
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"Referenced OPUS file not found: {path}")
        signature = _file_signature(path)
        entry = payload["entries"].get(name)

        if _valid_entry(entry, signature):
            values = np.asarray(entry["values"], dtype=float)
            axis = validate_wavenumbers(entry["axis"])
            hits += 1
        else:
            values, axis = read_opus_spectrum(path)
            payload["entries"][name] = {
                "signature": signature,
                "values": np.asarray(values, dtype=float),
                "axis": np.asarray(axis, dtype=float),
            }
            misses += 1
            changed = True

        spectra[name] = (values, axis)

    if cache_path is not None and (changed or not cache_path.is_file()):
        _save_cache(cache_path, payload)

    return spectra, OpusCacheStats(
        hits=hits,
        misses=misses,
        requested=len(requested),
        cache_path=cache_path,
    )
