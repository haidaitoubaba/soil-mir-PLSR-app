# Soil MIR PLSR v0.2.2

Patch release focused on validation-design control and safer local run-history management.

## Changes

### Explicit optional Group stratification control

- Configuration now includes **Use Group for stratification when available**.
- The setting is enabled by default, preserving v0.2.1 behavior.
- When enabled, K-fold uses Group-aware stratification when complete Group metadata is feasible; otherwise it falls back to sample-level K-fold.
- When enabled, Monte Carlo uses Group-based stratification when complete Group metadata is feasible; otherwise it falls back to ordinary sample-level holdout.
- When disabled, K-fold always uses shuffled sample-level K-fold even when Group metadata is present.
- When disabled, Monte Carlo always uses ordinary sample-level random holdout even when Group metadata is present.
- Non-LOGO inner CV follows the same Group setting.
- LOSO and Kennard–Stone remain unaffected by the toggle.
- LOGO always requires and uses complete Group metadata regardless of the toggle.
- The setting is saved in configuration profiles, run configuration, run-history reloads, and final-only refits.
- Preflight and Results now distinguish whether Group stratification was requested and whether it was actually used for outer validation and inner CV.

### Run History deletion

- Run History now provides **Delete this run** for completed, completed-with-errors, failed, and cancelled runs.
- Deletion requires a second explicit **Delete permanently** confirmation.
- Deleting a run removes its entire local run directory, including results workbooks, models, plots, reports, refits, configuration files, and resume/checkpoint information.
- Running runs are protected from deletion.
- Deletion is restricted to validated run directories that are direct children of the selected Results directory.
- The run manifest must match the target directory before deletion is allowed.
- Relevant in-memory session references are cleared after deletion.

## Validation

The release is covered by 155 automated tests.

New regression coverage includes:

- Group-enabled versus Group-disabled K-fold behavior;
- Group-enabled versus Group-disabled Monte Carlo behavior;
- non-LOGO inner-CV Group handling;
- LOGO remaining Group-required regardless of the toggle;
- persistence and backward-compatible defaults for the new Group setting;
- preflight reporting of outer and inner Group use;
- deletion of finished Run History entries;
- protection of running runs;
- path-safety and manifest-integrity checks for destructive deletion;
- explicit two-step confirmation in the Run History UI.

Release CI also checks linting, Streamlit startup, and deterministic macOS and Windows bundle generation.

## Requirements

- Python 3.10+
- Internet access on first launch to install dependencies

## Distribution

- macOS: `soil-mir-app-v0.2.2-mac.tar.gz`
- Windows: `soil-mir-app-v0.2.2-windows.zip`

The macOS package is not yet a signed/notarized standalone `.app`. The Windows package is not yet a standalone installer.
