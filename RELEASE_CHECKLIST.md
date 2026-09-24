# macOS v0.1.0 Release Candidate Checklist

This checklist freezes the current macOS MVP. Do not add product features while completing it.

## Automated release gate

- [ ] `pyproject.toml` and `src/soil_mir/__init__.py` both report `0.1.0`.
- [ ] GitLab `ci_config_check` passes.
- [ ] GitLab `lint` passes.
- [ ] GitLab `pytest` passes, including scientific regression tests.
- [ ] GitLab `streamlit_smoke` passes.
- [ ] GitLab `mac_rc_bundle` produces one `dist/*.zip` artifact.
- [ ] The ZIP excludes tests, Git metadata, CI configuration, local environments, and research data.
- [ ] `run_app.command` is stored as executable inside the ZIP.

## Clean-Mac manual gate

Run these checks from the ZIP artifact, not from the development checkout.

- [ ] Extract the ZIP into a folder whose path contains spaces.
- [ ] Confirm a Mac without Python receives the explicit Python 3.10+ requirement message.
- [ ] With Python 3.10+ installed, double-click `run_app.command`.
- [ ] Confirm first launch creates `.venv`, installs dependencies, and opens Streamlit.
- [ ] Close the app, relaunch it, and confirm the existing environment is reused.
- [ ] Select spectra, reference workbook, and results folders with Finder.
- [ ] Repeat at least one path test using non-ASCII characters in a folder name.
- [ ] Run preflight on a representative dataset.
- [ ] Complete one small validation run and open its saved result folder.
- [ ] Cancel one run at a scientific checkpoint and resume it.
- [ ] Reopen a saved run from Run History.
- [ ] Send a saved final model from Run History to Predict.
- [ ] Run prediction-only mode once.
- [ ] Run external-validation mode once and verify the four-sheet workbook.
- [ ] Quit Streamlit and confirm saved runs remain discoverable after relaunch.

## RC decision

A blocker is any issue that prevents installation/startup, changes scientific results unexpectedly,
loses/corrupts saved work, or breaks the core Data -> Configuration -> Run -> Results -> Predict
workflow.

Non-blocking cosmetic issues should be recorded for v0.2 rather than added to v0.1.0 during the
release freeze.

## Packaging scope

v0.1.0 RC is a local-first Python distribution. It requires Python 3.10+ and first-launch internet
access. A signed/notarized standalone macOS `.app` is intentionally deferred and should not be
described as part of this RC.
