# Windows MVP Release Candidate Checklist

This checklist covers the Windows distribution layer only. Scientific behavior must remain identical
to the already regression-tested core.

## Automated release gate

- [ ] `pyproject.toml` and `src/soil_mir/__init__.py` report the same version.
- [ ] GitLab `ci_config_check` passes for both macOS and Windows release inputs.
- [ ] GitLab `lint` passes.
- [ ] GitLab `pytest` passes, including shared launcher and scientific regression tests.
- [ ] GitLab `streamlit_smoke` passes.
- [ ] GitLab `windows_rc_bundle` produces one `dist/*-windows.zip` artifact.
- [ ] The Windows ZIP excludes tests, Git metadata, CI configuration, local environments, and data.
- [ ] The ZIP includes `run_app.bat`, `run_app.ps1`, and `scripts/launch_app.py`.

## Windows manual gate

Run these checks from the Windows ZIP artifact, not from a development checkout.

- [ ] Extract the ZIP into a folder whose path contains spaces.
- [ ] Double-click `run_app.bat` on Windows 10 or Windows 11.
- [ ] Confirm a machine without supported Python gets a clear Python 3.10+ requirement message.
- [ ] With Python 3.10+ installed, confirm first launch creates `.venv` and installs dependencies.
- [ ] Close and relaunch; confirm the existing environment is reused.
- [ ] Confirm the app opens in the browser and all pages render.
- [ ] Select spectra, reference workbook, and results folders using the Windows file/folder dialogs.
- [ ] Repeat at least one path test using spaces and non-ASCII characters.
- [ ] Run preflight on a representative dataset.
- [ ] Complete one small validation and open its saved result folder.
- [ ] Cancel and resume one run through Run History.
- [ ] Send a saved model from Run History to Predict.
- [ ] Run prediction-only once.
- [ ] Run external validation once and verify the four-sheet workbook.
- [ ] Quit and relaunch; confirm saved runs remain discoverable.

## Current CI limitation

The project currently runs GitLab CI on Linux runners. CI fully tests the shared Python launcher logic,
builds and inspects the Windows ZIP, and verifies the Streamlit application. It cannot execute
`cmd.exe` or PowerShell as Windows itself would. The first real `run_app.bat` double-click therefore
remains a required Windows acceptance test unless a Windows GitLab runner is added later.
