# Windows v0.2.0 Release Candidate Checklist

This checklist validates the Windows distribution for the cross-platform v0.2.0 release. Scientific
behavior must remain identical to the regression-tested core.

## Automated release gate

- [ ] `pyproject.toml` and `src/soil_mir/__init__.py` both report `0.2.0`.
- [ ] GitLab `ci_config_check` passes for macOS and Windows release inputs.
- [ ] GitLab `lint` passes.
- [ ] GitLab `pytest` passes, including shared launcher and scientific regression tests.
- [ ] GitLab `streamlit_smoke` passes.
- [ ] GitLab `windows_rc_bundle` produces one `dist/*-windows.zip` artifact.
- [ ] The Windows ZIP excludes tests, Git metadata, CI configuration, local environments, and data.
- [ ] The ZIP includes `run_app.bat`, `run_app.ps1`, and `scripts/launch_app.py`.

## Representative-Windows manual gate

Run these checks from the Windows ZIP artifact, not from a development checkout.

- [ ] Extract the ZIP into a folder whose path contains spaces.
- [ ] Double-click `run_app.bat` on Windows 10 or Windows 11.
- [ ] Confirm the launcher creates or reuses `.venv` and opens Soil MIR in the default browser.
- [ ] Select spectra, reference workbook, and results folders using the native Windows dialogs.
- [ ] Run preflight on a representative dataset.
- [ ] Complete one small validation and open its saved result folder in Explorer.
- [ ] Cancel and resume one run through Run History.
- [ ] Send a saved model from Run History to Predict.
- [ ] Run prediction-only with a normal numeric-extension OPUS directory.
- [ ] Run prediction-only with readable OPUS files that use non-numeric names/extensions.
- [ ] Run external validation once and verify the four-sheet workbook.
- [ ] Quit and relaunch; confirm saved runs remain discoverable.

## Current CI limitation

The project currently runs GitLab CI on Linux runners. CI tests the shared launcher logic, builds and
inspects the Windows ZIP, and verifies the Streamlit application. It cannot execute Windows
`cmd.exe` or PowerShell itself, so a real `run_app.bat` launch remains a required Windows
acceptance check before a Windows release is tagged.
