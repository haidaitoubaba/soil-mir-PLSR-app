# Soil MIR PLSR App v0.4.0

## Cleanup before modeling

The new Cleanup workbench reviews the reference workbook and its OPUS spectra before calibration. Start a session from an Excel workbook and OPUS folder, reopen an existing Cleanup session, or reuse the inputs selected in Modeling Data.

Review PCA scores and spectra, exclude or restore records, and complete the Half A and Half B reviews. Auto Cleanup runs the review workflow on a separate session copy. New sessions use the PLSR native OPUS reader for valid point counts and absorbance scaling.

## From Cleanup to Modeling Data

1. Open **Cleanup → Export overview** and choose **Export cleaned dataset…**. The export includes a cleaned copy of the reference workbook and review records.
2. When the export completes, click **Use in PLSR** next to the export button. The app checks the workbook fingerprint and the retained scans, then carries the cleaned workbook and its original OPUS folder to **Modeling Data**.
3. Click **Inspect data** to apply the inputs. **Data Overview** lists the number of retained samples and scans for each property reviewed in Cleanup. Continue through **Configuration** and **Run** to calibrate and validate a model.

Exclusions are applied per property in the cleaned workbook. Cleanup and modeling both use the original OPUS files from their local folder.

## Navigation

- **Spectral QC** has a dedicated entry near the top of the sidebar.
- **Calibration** starts with **Cleanup**, followed by **Modeling Data**, **Configuration**, **Run**, and **Results**.
- Use **Modeling Data** directly when the reference workbook and OPUS folder are ready for modeling.

## Downloads

- macOS package — extract the archive and open `run_app.command`.
- Windows package — extract the archive and open `run_app.bat`.
- `SHA256SUMS.txt` — SHA-256 checksums for both downloads.

The launchers use Python 3.10 or newer. Internet access is required on first launch to install dependencies.
