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

Validation metrics shown in Results are R², RMSE, RPIQ, Bias, RPD, MAE, and
Lin's CCC, calculated from sample-level outer predictions. RPD uses the sample
standard deviation (ddof=1) of measured values divided by RMSE, and MAE and CCC
are computed on the original response scale. The same seven metrics are reported
for external validation. Undefined RPD/CCC values are shown as N/A.
For older saved runs, new metrics are not backfilled until validation is rerun. The final exported model is
selected and refit separately using all eligible calibration samples.

## Local performance and persistence

Parsed OPUS spectra are cached locally using file size and modification-time signatures. Unchanged
files can therefore be reused across STC/STN analyses without bypassing any property-specific
filtering, preprocessing, model selection, or validation.

The PLSR preprocessing search supports 11 selectable methods: the four legacy
first-derivative methods, Raw Spectra, SNV, MSC, SG Smoothing, Second Derivative,
Second Derivative + SNV, and Second Derivative + MSC. Legacy profiles and
saved runs continue to search the original four methods until other options
are explicitly selected. Savitzky-Golay settings apply to smoothing and both
derivative orders; SG operations are performed separately per contiguous
spectral interval. Each MSC reference is fitted on calibration rows only.

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


## v0.2.3 cross-platform release

Version `0.2.3` adds three complementary model performance metrics and seven additional
PLSR preprocessing candidates while preserving existing validation designs and saved
model compatibility.

- **Metrics**: RPD, MAE and Lin's Concordance Correlation Coefficient (CCC) join
  R², RMSE, RPIQ and Bias in Results, Monte Carlo summaries, and external validation.
  Older result files are still readable; missing new metrics show as N/A until rerun.
- **Preprocessing**: Raw Spectra, SNV, MSC, SG Smoothing, 2nd Derivative,
  2nd Deriv + SNV, and 2nd Deriv + MSC supplement the four original
  first-derivative options, for 11 supported methods in total.
- **Configuration**: users may select a subset of preprocessing candidates to
  evaluate within grouped nested CV. The four original methods remain selected
  by default, preventing unexpected growth in search time. Selection is saved
  in profiles, run history, and final-only refits.
- **Scientific safeguards**: SG processing respects disjoint spectral intervals;
  MSC references use training spectra only. Legacy model bundles and historical
  runs are supported.
- **Automated checks**: 187 tests passed on the previously merged feature commit;
  release-preparation changes undergo their own CI checks before tagging.

Release archives are created **only** by the GitLab `v0.2.3` tag pipeline:

- macOS: `soil-mir-app-v0.2.3-mac.tar.gz`
- Windows: `soil-mir-app-v0.2.3-windows.zip`

Both remain local-first Python distributions that require Python 3.10+ and
first-launch internet access. The macOS archive is not a signed/notarized `.app`;
the Windows archive is not a native installer. Representative Windows and macOS
manual acceptance checks are described in `WINDOWS_RELEASE_CHECKLIST.md` and
`RELEASE_CHECKLIST.md` and cannot be replaced by Linux-only CI.
