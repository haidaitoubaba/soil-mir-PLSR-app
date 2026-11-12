# Soil MIR PLSR v0.2.3

Cross-platform feature release: expanded regression metrics and spectral preprocessing options.

## What's new

### Three additional model metrics

- **RPD** (Ratio of Performance to Deviation): sample standard deviation of measured values
  (ddof=1) divided by RMSE.
- **MAE** (Mean Absolute Error): mean absolute difference between measured and predicted values.
- **CCC** (Lin's Concordance Correlation Coefficient): agreement accounting for both
  precision and location relative to the 1:1 line.

Results, internal model-selection summaries, Monte Carlo summaries and external-validation
reports now provide these alongside R², RMSE, RPIQ and Bias. Sample-level aggregation
continues to avoid treating technical replicate spectra as independent soils.
Undefined RPD/CCC values display as N/A. Older saved runs do not invent missing metrics.

### Seven additional preprocessing options

The search now supports 11 user-selectable methods:

1. 1st Derivative
2. 1st Deriv + SLS
3. 1st Deriv + SNV
4. 1st Deriv + MSC
5. Raw Spectra
6. SNV
7. MSC
8. SG Smoothing
9. 2nd Derivative
10. 2nd Deriv + SNV
11. 2nd Deriv + MSC

The original four methods remain selected by default, preserving established
runtime and behavior. Select additional methods under Configuration →
PLSR preprocessing candidates. Each selected candidate participates in internal
model selection and region/rank optimization.

Savitzky–Golay operations are applied independently within contiguous spectral
intervals. Second derivatives require SG polynomial order >= 2.
MSC calibration references are computed using training spectra only and saved
with final models, including across outer CV and external prediction.

### Backward compatibility

- Existing calibration models retain their original preprocessing behavior.
- Legacy saved profiles and run settings default to the original four candidates.
- New selections are persisted in saved profiles, run configurations, history reloads,
  and tolerance-only refits.

## Validation and packaging

The v0.2.3 preparation is CI-tested with regression and scientific checks.
The tagged GitLab pipeline generates and validates both archives.
Native macOS/Windows launch acceptance should be checked against the packaged artifacts.

## Requirements

- Python 3.10+
- First-launch internet access for dependency installation

## Distribution

- macOS: `soil-mir-app-v0.2.3-mac.tar.gz`
- Windows: `soil-mir-app-v0.2.3-windows.zip`

macOS is not a signed/notarized standalone .app; Windows is not a standalone installer.
