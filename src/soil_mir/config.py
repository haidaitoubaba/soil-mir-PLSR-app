from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ColumnConfig:
    sample_id: str = "Sample"
    reference_file: str = "File Name"
    reference_value: str = "Reference Value"
    group: str = "Group"

    @property
    def required(self) -> tuple[str, ...]:
        return (self.sample_id, self.reference_value, self.reference_file, self.group)


@dataclass(frozen=True)
class SpectralConfig:
    wn_min: float = 600.0
    wn_max: float = 4000.0
    exclude_co2: bool = False
    co2_min: float = 2300.0
    co2_max: float = 2400.0
    sg_window: int = 11
    sg_polyorder: int = 2

    def validate(self) -> None:
        if self.wn_min >= self.wn_max:
            raise ValueError("wn_min must be less than wn_max")
        if self.co2_min >= self.co2_max:
            raise ValueError("co2_min must be less than co2_max")
        if self.sg_window < 3 or self.sg_window % 2 == 0:
            raise ValueError("Savitzky-Golay window must be an odd integer >= 3")
        if self.sg_polyorder < 0 or self.sg_polyorder >= self.sg_window:
            raise ValueError("Savitzky-Golay polynomial order must be smaller than the window")


@dataclass(frozen=True)
class ValidationConfig:
    methods: tuple[str, ...] = ("kfold",)
    max_rank: int = 15
    region_search_n_windows: int = 7
    rmsecv_tolerance_pct: float = 5.0
    random_seed: int = 42

    def validate(self) -> None:
        valid = {"kfold", "monte_carlo", "loso", "logo", "kennard_stone"}
        unknown = set(self.methods) - valid
        if unknown:
            raise ValueError(f"Unknown validation methods: {sorted(unknown)}")
        if self.max_rank < 1:
            raise ValueError("max_rank must be >= 1")
        if self.region_search_n_windows < 1:
            raise ValueError("region_search_n_windows must be >= 1")
        if self.rmsecv_tolerance_pct < 0:
            raise ValueError("rmsecv_tolerance_pct must be >= 0")


@dataclass(frozen=True)
class AnalysisConfig:
    spectra_dir: Path | None = None
    reference_excel: Path | None = None
    output_dir: Path | None = None
    columns: ColumnConfig = field(default_factory=ColumnConfig)
    spectral: SpectralConfig = field(default_factory=SpectralConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    metadata_sheet: str = "Property Metadata"

    def validate(self, check_paths: bool = True) -> None:
        self.spectral.validate()
        self.validation.validate()
        if not check_paths:
            return
        if self.spectra_dir is None or not self.spectra_dir.is_dir():
            raise FileNotFoundError(f"Spectra directory not found: {self.spectra_dir}")
        if self.reference_excel is None or not self.reference_excel.is_file():
            raise FileNotFoundError(f"Reference workbook not found: {self.reference_excel}")
