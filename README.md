# Soil MIR PLSR App

Local-first Streamlit application for soil MIR PLSR calibration, nested validation, model export,
run history, and prediction.

## Current workflow

The app now provides:

1. **Data** — choose a local Bruker OPUS directory, reference workbook, and results directory.
2. **Configuration** — select properties and validation/model-search settings.
3. **Run** — execute nested validation and a separate all-data final model refit.
4. **Results** — review outer-validation metrics, predictions, model selection, and saved artifacts.
5. **Predict** — apply a saved final `.joblib` model to a new OPUS directory.
6. **Run History** — reopen persistent summaries and saved artifacts from earlier runs.

The full research dataset is intentionally **not** committed to Git. GitLab CI uses small
representative fixtures, while the local app reads the full spectra and reference files directly
from the user's computer.

## Scientific behavior

The refactored engine is protected by regression tests against frozen functions from the legacy
script. Covered behavior includes response transforms, derivative/SLS/SNV/MSC preprocessing,
group-aware splitting, PLS rank paths, RMSECV tolerance selection, backward spectral-region
optimization, final model fitting, external prediction, and nested validation.

Validation metrics shown in Results come from outer predictions. The final exported model is
selected and refit separately using all eligible calibration samples.

## Local performance and persistence

Parsed OPUS spectra are cached locally using file size and modification-time signatures. Unchanged
files can therefore be reused across STC/STN analyses without bypassing any property-specific
filtering, preprocessing, model selection, or validation.

Each run creates a timestamped local directory containing a run manifest and, for each
property/method combination:

- `Results.xlsx`
- `Final_Model.joblib`
- `Resolved_Config.json`
- `Split_Info.json`

Run History reads those manifests, so completed analyses remain discoverable after Streamlit is
closed.

## Mac launcher

On macOS, `run_app.command` is the local launcher. It creates a project-local `.venv` when needed,
installs/updates the app dependencies when `pyproject.toml` changes, and starts Streamlit. After the
first setup, repeated launches reuse the same environment.

Developers can still launch with:

```bash
python -m streamlit run app/Home.py
```

All repository builds, dependency installation for development, linting, scientific tests, and
startup smoke tests are automated in GitLab CI.
