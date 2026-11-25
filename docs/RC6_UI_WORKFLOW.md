# RC6 workflow and UI release candidate

The seven existing pages retain their scientific services and use conditional
subsections instead of rendering all workspaces simultaneously. Input drafts
are separate from applied configuration; subsection navigation retains ordinary
widget values. QC decisions remain attached to the original batch and review
revision. Prediction compatibility and extrapolation confirmation are scoped to
the selected model and current external input identities.

Run names are optional display aliases stored in a separate
`.soil_mir_run_alias.json` sidecar in each run folder. Existing Run IDs,
manifests and model artifacts are unchanged. Model catalog choices represent
actual available artifacts. Final-only refit previews label source validation
metrics as such, not independent validation of the refitted model. Manual
.joblib files are still supported; only load models from trusted sources.

Automated tests exercise section state, review state, legacy history and model
identity. The actual Mac/Windows user acceptance, browser flicker behavior,
large local data and cross-instrument scientific acceptance remain separate
release gates. File identities use resolved paths, size and modification time,
not full cryptographic content hashes. No formal release promotion before
explicit user acceptance.
