# Soil MIR 202 CI fixture

This fixture is derived from the user's real 202 field data and is intentionally limited to
`202_STC` and `202_STN`.

Design:

- 24 unique soil samples;
- all 12 groups represented;
- 2 samples per group;
- 3 reference/spectral replicate filenames per sample in the reduced reference workbook;
- the exact same sample set for STC and STN;
- only the reduced reference workbook and manifest are committed at this stage.

The full research dataset and raw OPUS binaries remain outside Git. Real OPUS parsing against the
uploaded research spectra will be added as a dedicated regression layer after the core engine is
extracted, rather than putting the complete dataset into normal repository history.
