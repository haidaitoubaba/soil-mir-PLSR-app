# Soil MIR PLSR App v0.2.4

## Scientific changes

- Correct Bruker OPUS wavenumber axes for new calibration runs using the selected block's declared valid point count (NPT), scaling factor (CSF), and FXV/LXV endpoints. This avoids including trailing storage padding in the measured grid.
- Enter training spectral minimum and maximum directly to four decimal places. Default: 600–4000 cm⁻¹. Calibration retains measured grid points inside the bounds, with existing property-specific CO₂ exclusion.
- Optionally crop external spectra before alignment and interpolation to the saved model grid. Either bound may be blank; at least two measured points must remain. Off-grid crop endpoints are projected from the nearest two retained measurements. The existing endpoint extrapolation limit applies after alignment.
- Prediction workbooks record model and prediction OPUS modes, crop bounds, aligned range, and endpoint extrapolation limit. Prediction filenames include microseconds.

## Compatibility

New calibration defaults to `native_npt`. Old saved bundles and run configurations without an OPUS mode use `legacy_array_length` in automatic prediction, resume, and final-only tolerance refits. Manual prediction overrides are available for diagnostics, and mismatched modes are reported. Cache version 2 separates the two modes. For scientific comparisons, retrain and predict consistently using the corrected reader; old results are not silently recalculated.

## Validation before distribution

The handoff reports local checks against 270 spectra from three laboratories. Three dedicated regression tests are included. GitLab CI must pass configuration, lint, test, Streamlit startup, and release-script checks. Representative macOS/Windows archive launch and historical-model acceptance remain manual release gates. No research spectra, reference workbooks, models, or caches are included.
