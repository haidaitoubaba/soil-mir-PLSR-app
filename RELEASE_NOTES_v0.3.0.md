# v0.3.0 — Spectral Quality Control

- Standalone reference-free OPUS replicate QC, auto filename grouping and optional explicit mapping.
- Editable Pearson threshold (default strict >99.6%), advanced exploratory NRMSE and regional QC.
- All-pair diagnostics, exact suspect filenames, raw overlays, differences and rescan lists.
- Local Excel reports and JSON review snapshots with SHA-256 input validation.
- Explicit opt-in frozen calibration selection; existing reference Sample identity is preserved.
- Original files and legacy model/prediction paths are unchanged.

Scientific acceptance on real spectra and desktop acceptance on macOS/Windows remain required
before promoting a release candidate. The NRMSE limits are exploratory and the Pearson
implementation is not asserted to reproduce OPUS Quick Compare.

## RC2 acceptance fixes

- Use the shared measured interval within 600–4000 cm⁻¹ by default, with an explicit strict manual mode. Never extrapolate; report requested and effective bounds.
- Separate read failures from input validation errors and show N/A when no samples are evaluable.
- Correct the sidebar label to Spectral QC.
