from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalDataLayout:
    data_dir: Path
    spectra_dir: Path
    reference_excel: Path
    output_dir: Path
    source: str


def _layout_from_data_dir(
    data_dir: Path,
    *,
    source: str,
) -> LocalDataLayout | None:
    data_dir = data_dir.expanduser()
    spectra_dir = data_dir / "spectra" / "Complete"
    reference_excel = (
        data_dir
        / "reference"
        / "reference_value_ZL_trt.xlsx"
    )
    if not spectra_dir.is_dir() or not reference_excel.is_file():
        return None

    return LocalDataLayout(
        data_dir=data_dir,
        spectra_dir=spectra_dir,
        reference_excel=reference_excel,
        output_dir=data_dir / "soil_mir_results",
        source=source,
    )


def detect_local_data_layout(
    *,
    home: str | Path | None = None,
    cwd: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> LocalDataLayout | None:
    environment = os.environ if environ is None else environ
    candidates: list[tuple[str, Path]] = []

    configured = environment.get(
        "SOIL_MIR_DATA_DIR",
        "",
    ).strip()
    if configured:
        candidates.append(
            (
                "SOIL_MIR_DATA_DIR",
                Path(configured),
            )
        )

    working = Path.cwd() if cwd is None else Path(cwd)
    candidates.append(
        ("project data directory", working / "data")
    )

    home_path = Path.home() if home is None else Path(home)
    candidates.append(
        (
            "legacy Downloads directory",
            home_path
            / "Downloads"
            / "Python Code for Zheya"
            / "Python code for MIR"
            / "data",
        )
    )

    seen = set()
    for source, candidate in candidates:
        resolved = candidate.expanduser()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)

        layout = _layout_from_data_dir(
            resolved,
            source=source,
        )
        if layout is not None:
            return layout

    return None
