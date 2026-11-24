from unittest import TestCase
from unittest.mock import patch

import numpy as np

from soil_mir.io.opus import OPUS_LEGACY, crop_spectrum, read_opus_spectrum


class OpusReadingAndCropTests(TestCase):
    @patch("brukeropusreader.read_file")
    def test_declared_points_and_scale_with_legacy_compatibility(self, read_file):
        read_file.return_value = {
            "AB": [8, 6, 4, 2, 0],
            "AB Data Parameter": {"FXV": 4000, "LXV": 1000, "NPT": 4, "CSF": 0.5},
        }
        values, axis = read_opus_spectrum("test.0")
        np.testing.assert_array_equal(values, [4, 3, 2, 1])
        np.testing.assert_array_equal(axis, [4000, 3000, 2000, 1000])
        legacy_values, legacy_axis = read_opus_spectrum("test.0", opus_axis_mode=OPUS_LEGACY)
        np.testing.assert_array_equal(legacy_values, [8, 6, 4, 2, 0])
        np.testing.assert_array_equal(legacy_axis, [4000, 3250, 2500, 1750, 1000])

    def test_off_grid_crop_uses_only_retained_measurements(self):
        values, axis = crop_spectrum([99, 6, 4, 2, 99], [5, 4, 3, 2, 1], 1.5, 4.5)
        np.testing.assert_array_equal(values, [7, 6, 4, 2, 1])
        np.testing.assert_array_equal(axis, [4.5, 4, 3, 2, 1.5])

    def test_crop_rejects_range_with_fewer_than_two_measurements(self):
        with self.assertRaisesRegex(ValueError, "two measured points"):
            crop_spectrum([6, 4, 2], [3, 2, 1], 1.5, 2.5)
