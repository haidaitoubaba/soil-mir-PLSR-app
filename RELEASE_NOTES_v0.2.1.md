# Soil MIR PLSR v0.2.1

Patch release focused on reference-data flexibility and validation-specific handling of `Group`.

## Changes

- `Group` is now optional during Data inspection and calibration-data loading.
- Reference sheets require only `Sample`, `File Name`, and `Reference Value`.
- K-fold Cross-Validation works without `Group`; complete Group metadata is used for balancing when feasible.
- Monte Carlo Repeated Holdout works without `Group`; complete Group metadata is used for stratification when feasible.
- LOSO and Kennard–Stone no longer depend on `Group`.
- LOGO still requires complete, non-missing `Group` metadata and now reports this requirement during preflight.
- Partially missing Group metadata no longer causes valid reference rows or samples to be silently dropped.
- Data acceptance and preflight now report Group availability as Complete, Partial, or Not provided.
- Existing split behavior is preserved when complete Group metadata is supplied.

## Validation

The release is covered by 141 automated tests, including new regression tests for:

- reference workbooks with no Group column;
- partially missing Group values;
- non-LOGO validation without Group;
- LOGO rejection when Group metadata is unavailable.

Release CI also checks linting, Streamlit startup, and deterministic macOS and Windows bundle generation.

## Requirements

- Python 3.10+
- Internet access on first launch to install dependencies

## Distribution

- macOS: `soil-mir-app-v0.2.1-mac.tar.gz`
- Windows: `soil-mir-app-v0.2.1-windows.zip`

The macOS package is not yet a signed/notarized standalone `.app`. The Windows package is not yet a standalone installer.
