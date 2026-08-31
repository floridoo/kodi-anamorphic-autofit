import os
import sys
import unittest


ADDON_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "service.anamorphic.autofit")
)
if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)

from logic import (  # noqa: E402
    DEFAULT_TARGET_AR,
    PROJECTOR_AR,
    aspect_ratio_from_dimensions,
    aspect_ratio_from_l5_offsets,
    calculate_view_mode,
    is_valid_target_ar,
    parse_l5_offsets,
    parse_target_ar,
)


class LogicTests(unittest.TestCase):
    def test_target_ratio_validation_and_fallback(self):
        self.assertTrue(is_valid_target_ar("2.40"))
        self.assertFalse(is_valid_target_ar("0"))
        self.assertFalse(is_valid_target_ar("nan"))
        self.assertFalse(is_valid_target_ar("inf"))
        self.assertFalse(is_valid_target_ar("1.77"))
        self.assertEqual(parse_target_ar("not-a-number"), DEFAULT_TARGET_AR)

    def test_aspect_ratio_from_dimensions_rejects_bad_values(self):
        self.assertAlmostEqual(aspect_ratio_from_dimensions("1920", "1080"), 16 / 9)
        self.assertIsNone(aspect_ratio_from_dimensions(0, 1080))
        self.assertIsNone(aspect_ratio_from_dimensions(1920, "nan"))

    def test_l5_offsets_describe_the_active_picture(self):
        self.assertEqual(parse_l5_offsets("0", "0", "280", "280"), (0, 0, 280, 280))
        self.assertAlmostEqual(
            aspect_ratio_from_l5_offsets(3840, 2160, 0, 0, 280, 280), 2.40
        )
        self.assertAlmostEqual(
            aspect_ratio_from_l5_offsets(3840, 2160, 0, 0, 0, 0), 16 / 9
        )

    def test_l5_offsets_reject_bad_or_impossible_metadata(self):
        self.assertIsNone(parse_l5_offsets("-1", "0", "0", "0"))
        self.assertIsNone(parse_l5_offsets("nan", "0", "0", "0"))
        self.assertIsNone(
            aspect_ratio_from_l5_offsets(3840, 2160, 0, 0, 1080, 1080)
        )

    def test_calculates_capped_zoom_and_pixel_ratio(self):
        view_mode = calculate_view_mode(16 / 9, 2.76, 2.40)
        self.assertAlmostEqual(view_mode["zoom"], 2.40 / (16 / 9))
        self.assertAlmostEqual(view_mode["pixelratio"], PROJECTOR_AR / 2.40)

    def test_does_not_adjust_narrow_or_non_16_9_content(self):
        self.assertIsNone(calculate_view_mode(16 / 9, 1.78, 2.40))
        self.assertIsNone(calculate_view_mode(4 / 3, 2.40, 2.40))
        self.assertIsNone(calculate_view_mode(16 / 9, 2.40, 0))


if __name__ == "__main__":
    unittest.main()
