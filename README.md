# Soil MIR PLSR App

Local-first Streamlit application for soil MIR PLSR calibration, nested validation, model export,
run history, and prediction.

## Current workflow

The app now provides:

1. **Data** — choose any local Bruker OPUS directory, reference workbook, and results directory. On macOS and Windows, native Browse buttons are available; successful selections are remembered as the last-used paths. Auto-detected legacy layouts are suggestions only and are never selected automatically. Property sheets are also never preselected; the user explicitly chooses which properties to inspect or model.
2. **Configuration** — select properties and validation/model-search settings.
3. **Run** — run an explicit preflight feasibility check first, review its Pass/Fail table, then start nested validation in a responsive background job. Live progress remains visible, the run can be safely cancelled at scientific checkpoints, and incomplete runs remain resumable without repeating completed property/method combinations.
4. **Results** — review outer-validation metrics, predictions, model selection, and saved artifacts.
5. **Predict** — choose a final model directly from Run History or browse to any compatible `.joblib`, then apply it to an external OPUS directory in either prediction-only or external-validation mode. External validation uses the reference worksheet's exact `File Name` → `Sample` mapping, allows only the authoritative script's ≤0.25 cm⁻¹ endpoint tolerance by default, reports validation metrics, and exports a four-sheet Excel workbook.
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

Outer validation splits can run in parallel using the legacy-compatible default of four shared-memory
workers while numerical libraries inside each worker are limited to one thread. This avoids nested
BLAS/OpenMP oversubscription while preserving deterministic split seeds and result ordering.

Each run creates a timestamped local directory containing a run manifest and, for each
property/method combination:

- `Results.xlsx`
- `Final_Model.joblib`
- `Resolved_Config.json`
- `Split_Info.json`

Run History reads those manifests, so completed analyses remain discoverable after Streamlit is
closed.

## Cross-platform launchers

The environment/bootstrap logic now lives in `scripts/launch_app.py` and is shared across platforms.
It verifies Python 3.10+, creates or repairs a project-local `.venv`, reports first-run dependency
installation progress, installs/updates dependencies when `pyproject.toml` changes, and starts
Streamlit.

On macOS, double-click `run_app.command`. On Windows, double-click `run_app.bat`; an optional
`run_app.ps1` launcher is also provided. Repeated launches reuse the same environment. Platform
wrappers contain only Python discovery and user-facing terminal behavior, so the setup logic is not
duplicated between macOS and Windows.

Developers can still launch with:

```bash
python -m streamlit run app/Home.py
```

All repository builds, dependency installation for development, linting, scientific tests, and
startup smoke tests are automated in GitLab CI.


## v0.2.0 cross-platform release candidate

The repository version is `0.2.0`. GitLab CI builds deterministic release artifacts for both
supported desktop platforms after the validation and quality gates pass:

- macOS: `soil-mir-app-v0.2.0-<label>-mac.tar.gz`
- Windows: `soil-mir-app-v0.2.0-<label>-windows.zip`

Both distributions contain the same application and scientific engine. The platform wrappers only
handle local Python discovery, virtual-environment startup, native path dialogs, browser launch, and
opening result folders.

The distributions remain local-first Python packages. Target computers need Python 3.10+ and
internet access on first launch for dependency installation. The macOS package is not a
signed/notarized standalone `.app`, and the Windows package is not a standalone installer.

Before tagging `v0.2.0`, complete the relevant checks in `RELEASE_CHECKLIST.md` and
`WINDOWS_RELEASE_CHECKLIST.md` using generated CI artifacts.
