# Soil MIR PLSR App

Local-first Streamlit application for the Soil MIR PLSR workflow.

## Current milestone: M1

This first implementation establishes the safe foundation for the app:

- reusable scientific/application package under `src/soil_mir`;
- local data inspection for OPUS folders and Excel reference workbooks;
- first Streamlit Home and Data pages;
- a real-data CI fixture focused only on `202_STC` and `202_STN`;
- automated GitLab CI for linting, tests, real OPUS parsing, and Streamlit startup.

The full research dataset is intentionally **not** committed to Git. The local app will operate on
full local folders, while CI uses a small representative fixture.

## Local workflow

When running locally, the app asks for:

1. the directory containing Bruker OPUS files;
2. the reference Excel workbook;
3. the property sheets to inspect/use.

The scientific modelling engine will be migrated from the legacy script incrementally, protected by
regression tests so UI refactoring does not silently change scientific behavior.
