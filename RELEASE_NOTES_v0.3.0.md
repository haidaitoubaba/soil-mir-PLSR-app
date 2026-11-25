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

- Read the full native OPUS absorbance range and use the shared measured interval by default, with an explicit strict manual mode. Never extrapolate; report requested and effective bounds.
- Separate read failures from input validation errors and show N/A when no samples are evaluable.
- Correct the sidebar label to Spectral QC.

## RC3 review workflow

- Advanced regional settings, low-wavenumber diagnostic window, visual-only preprocessing.
- Simplified replicate diagnoses and explicit batch application of unambiguous recommendations.
- Separate agreed spectra, review decisions and rescan exports; no original files modified.

- Dual evaluation: first-replicate Pearson versus full pairwise Pearson, with method agreement,
  comparable-group pass rates and threshold sensitivity exports; active all-pair review unchanged.

## RC4 review and file export

- Optional review reasons throughout; shared editable decision tables in sample and export views.
- Export original OPUS copies by saved review decision, with verified hashes, separate decision
  subfolders, CSV index and export settings; never changes original files or freezes selection.

## RC5 review clarity and undo

- Clarify read-only USDA-style pair membership and explicitly label unreviewed files.
- Clear all saved review decisions with confirmation and undo up to 20 saved transactions
  within the same QC session and criteria. Original spectra and saved exports are unchanged.

- Default UI: Routine QC / USDA-style reference acceptance; all-pairwise remains selectable.
- Conservative and best-pair screening, sample-level rescan lists, explicit policy metadata.

- Predict: automatic compatibility checks and endpoint tolerance (default 10 cm^-1 guardrail),
  explicit approval beyond 0.25 cm^-1, manual mode, per-file coverage and grid audit exports.
