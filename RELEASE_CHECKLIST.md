# macOS v0.2.0 Release Candidate Checklist

This checklist validates the macOS distribution for the cross-platform v0.2.0 release. Do not add
product features while completing it.

## Automated release gate

- [ ] `pyproject.toml` and `src/soil_mir/__init__.py` both report `0.2.0`.
- [ ] GitLab `ci_config_check` passes.
- [ ] GitLab `lint` passes.
- [ ] GitLab `pytest` passes, including scientific regression tests.
- [ ] GitLab `streamlit_smoke` passes.
- [ ] GitLab `mac_rc_bundle` produces one `dist/*-mac.tar.gz` artifact.
- [ ] The tar.gz archive excludes tests, Git metadata, CI configuration, local environments, and research data.
- [ ] `run_app.command` is stored as executable inside the tar.gz archive.

## Representative-Mac manual gate

Run these checks from the generated tar.gz artifact, not from the development checkout.

- [ ] Extract the tar.gz archive into a folder whose path contains spaces.
- [ ] With Python 3.10+ installed, double-click `run_app.command`.
- [ ] Confirm the launcher creates or reuses `.venv` and opens Soil MIR in the default browser.
- [ ] Select spectra, reference workbook, and results folders with Finder.
- [ ] Run preflight on a representative dataset.
- [ ] Complete one small validation run and open its saved result folder.
- [ ] Confirm Run History can reopen a saved run and send a final model to Predict.
- [ ] Run prediction-only mode once.
- [ ] Run external-validation mode once and verify the four-sheet workbook.
- [ ] Quit and relaunch; confirm saved runs remain discoverable.

## Release decision

A blocker is any issue that prevents installation/startup, changes scientific results unexpectedly,
loses/corrupts saved work, or breaks the core Data -> Configuration -> Run -> Results -> Predict
workflow.

The macOS distribution remains local-first and Python-based. It requires Python 3.10+ and
first-launch internet access. A signed/notarized standalone macOS `.app` is not part of v0.2.0.
