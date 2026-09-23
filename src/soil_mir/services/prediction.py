from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from soil_mir.io.opus import (
    list_opus_files,
    read_opus_spectrum,
    resample_spectrum,
)
from soil_mir.modeling import predict_model_bundle


REQUIRED_MODEL_KEYS = {
    "preprocessing_state",
    "pls_model",
    "wavenumbers",
    "response_transform",
    "response_transform_parameter",
    "property_name",
}


def load_model_bundle(model_path: str | Path) -> dict:
    path = Path(model_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(
            f"Model file not found: {path}"
        )
    bundle = joblib.load(path)
    if not isinstance(bundle, dict):
        raise ValueError(
            "The selected file is not a Soil MIR model bundle."
        )
    missing = REQUIRED_MODEL_KEYS - set(bundle)
    if missing:
        raise ValueError(
            "Model bundle is missing required keys: "
            f"{sorted(missing)}"
        )
    return bundle


def sample_key_from_opus_filename(filename: str) -> str:
    path = Path(filename)
    if path.suffix[1:].isdigit():
        return path.stem
    return path.name


def predict_opus_directory(
    model_path: str | Path,
    spectra_dir: str | Path,
) -> dict:
    bundle = load_model_bundle(model_path)
    files = list_opus_files(spectra_dir)
    if not files:
        raise ValueError(
            "No numeric-extension OPUS files were found."
        )

    target_source_axis = None
    rows = []

    for path in files:
        values, axis = read_opus_spectrum(path)
        if target_source_axis is None:
            target_source_axis = axis
            aligned = values
        else:
            aligned = resample_spectrum(
                values,
                axis,
                target_source_axis,
            )
        rows.append(aligned)

    matrix = np.vstack(rows)
    predictions = predict_model_bundle(
        bundle,
        matrix,
        target_source_axis,
    )

    file_predictions = pd.DataFrame(
        {
            "File Name": [path.name for path in files],
            "Sample": [
                sample_key_from_opus_filename(path.name)
                for path in files
            ],
            "Predicted": predictions,
        }
    )
    sample_predictions = (
        file_predictions.groupby("Sample", as_index=False)
        .agg(
            Predicted=("Predicted", "mean"),
            Spectra=("Predicted", "size"),
        )
    )

    return {
        "bundle": bundle,
        "file_predictions": file_predictions,
        "sample_predictions": sample_predictions,
    }
