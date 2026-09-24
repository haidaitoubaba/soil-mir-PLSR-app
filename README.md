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


## macOS release candidate

The repository version is `0.1.0`. GitLab CI now builds a deterministic macOS RC tar.gz archive after the
validation and quality gates pass. The tar.gz artifact contains the application source, `pyproject.toml`,
the executable `run_app.command` launcher, release instructions, and build metadata; development
tests, CI files, local environments, and research data are excluded.

This RC remains a local-first Python distribution: the target Mac needs Python 3.10+ and internet
access on first launch for dependency installation. It is not yet a signed/notarized standalone
`.app`.

Before promoting an RC to the final v0.1.0 release, complete `RELEASE_CHECKLIST.md` using the CI
ZIP artifact on a clean or representative Mac.


## Windows MVP release candidate

GitLab CI builds a deterministic Windows ZIP artifact alongside the macOS package. The Windows bundle
contains the application source, the shared launcher core, `run_app.bat`, `run_app.ps1`, build
metadata, and Windows validation instructions. Development tests, CI files, virtual environments, and
research data are excluded.

The Windows MVP remains a local-first Python distribution. The target machine needs Python 3.10+ and
internet access on first launch. The recommended user entry point is `run_app.bat`; no standalone
installer is included yet.

The current GitLab runners are Linux-based, so CI can test the shared launcher logic and inspect the
Windows package but cannot execute Windows `cmd.exe` itself. Complete
`WINDOWS_RELEASE_CHECKLIST.md` on a representative Windows machine before promoting a Windows RC.
