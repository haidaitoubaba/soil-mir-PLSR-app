# Soil MIR 202 CI fixture

This fixture is derived from the user's real 202 field data and is intentionally limited to
`202_STC` and `202_STN`.

Design:

- 24 unique soil samples;
- all 12 groups represented;
- 2 samples per group;
- 3 reference/spectral replicate filenames per sample in the reduced reference workbook;
- the exact same sample set for STC and STN;
- three real OPUS files from one selected sample for parser smoke testing;
- `model_matrix.csv` contains one replicate-averaged spectrum per sample, downsampled to 256
  wavenumber locations for fast CI tests.

The full research dataset must remain outside Git.
