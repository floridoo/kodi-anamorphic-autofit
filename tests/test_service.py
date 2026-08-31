import os
import queue
import sys
import threading
import types
import unittest
from unittest.mock import Mock


ADDON_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "service.anamorphic.autofit")
)
if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)


class FakePlayer:
    def __init__(self):
        pass


fake_xbmc = types.ModuleType("xbmc")
fake_xbmc.Player = FakePlayer
fake_xbmc.LOGINFO = 1
fake_xbmc.LOGWARNING = 2
fake_xbmc.LOGERROR = 3
fake_xbmc.log = lambda *args, **kwargs: None
fake_xbmc.getInfoLabel = lambda label: ""
fake_xbmc.executeJSONRPC = lambda request: "{}"

fake_xbmcaddon = types.ModuleType("xbmcaddon")
fake_xbmcaddon.Addon = lambda: None

sys.modules.setdefault("xbmc", fake_xbmc)
sys.modules.setdefault("xbmcaddon", fake_xbmcaddon)

from service import AnamorphicPlayerMonitor  # noqa: E402


class ServiceHelperTests(unittest.TestCase):
    def make_monitor(self):
        monitor = object.__new__(AnamorphicPlayerMonitor)
        monitor._state_lock = threading.RLock()
        monitor._last_applied_view_mode = None
        monitor._current_identity = None
        monitor._result_queue = queue.Queue()
        monitor.log = lambda *args, **kwargs: None
        return monitor

    def test_selects_current_video_stream(self):
        monitor = self.make_monitor()
        stream = monitor._select_video_stream(
            {
                "videostreams": [
                    {"index": 0, "width": 1920, "height": 1080},
                    {"index": 1, "width": 3840, "height": 2160},
                ],
                "currentvideostream": {"index": 1},
            }
        )
        self.assertEqual(stream["width"], 3840)

    def test_resets_only_when_kodi_still_has_addons_view_mode(self):
        monitor = self.make_monitor()
        expected = {"zoom": 1.35, "pixelratio": 0.74}
        monitor._last_applied_view_mode = {"player_id": 1, "viewmode": expected}
        calls = []

        def rpc(method, params):
            calls.append((method, params))
            if method == "Player.GetViewMode":
                return dict(expected)
            return "OK"

        monitor.execute_json_rpc = rpc
        monitor._reset_last_applied_view_mode(1)

        self.assertEqual(calls[0], ("Player.GetViewMode", {}))
        self.assertEqual(calls[-1], ("Player.SetViewMode", {"viewmode": "normal"}))
        self.assertIsNone(monitor._last_applied_view_mode)

    def test_preserves_a_manually_changed_view_mode(self):
        monitor = self.make_monitor()
        expected = {"zoom": 1.35, "pixelratio": 0.74}
        monitor._last_applied_view_mode = {"player_id": 1, "viewmode": expected}
        calls = []

        def rpc(method, params):
            calls.append((method, params))
            return {"zoom": 1.10, "pixelratio": 1.0} if method == "Player.GetViewMode" else "OK"

        monitor.execute_json_rpc = rpc
        monitor._reset_last_applied_view_mode(1)

        self.assertEqual([method for method, _params in calls], ["Player.GetViewMode"])
        self.assertIsNone(monitor._last_applied_view_mode)

    def test_reads_stable_l5_aspect_ratio(self):
        monitor = self.make_monitor()
        monitor.L5_SAMPLE_INTERVAL = 0
        labels = {
            monitor.L5_HAS_LABEL: "1",
            monitor.L5_OFFSET_LABELS[0]: "0",
            monitor.L5_OFFSET_LABELS[1]: "0",
            monitor.L5_OFFSET_LABELS[2]: "280",
            monitor.L5_OFFSET_LABELS[3]: "280",
        }
        monitor._get_info_label = lambda label: labels.get(label, "")

        result = monitor._read_l5_content_ar(3840, 2160)

        self.assertEqual(result[0], (0, 0, 280, 280))
        self.assertAlmostEqual(result[1], 2.40)

    def test_rejects_unstable_l5_aspect_ratio(self):
        monitor = self.make_monitor()
        monitor.L5_SAMPLE_INTERVAL = 0
        samples = [
            {"top": "280", "bottom": "280"},
            {"top": "276", "bottom": "276"},
            {"top": "280", "bottom": "280"},
        ]
        sample_index = [0]

        def get_label(label):
            sample = samples[sample_index[0]]
            if label == monitor.L5_HAS_LABEL:
                return "1"
            if label == monitor.L5_OFFSET_LABELS[0] or label == monitor.L5_OFFSET_LABELS[1]:
                value = "0"
            elif label == monitor.L5_OFFSET_LABELS[2]:
                value = sample["top"]
            else:
                value = sample["bottom"]
                sample_index[0] += 1
            return value

        monitor._get_info_label = get_label

        self.assertIsNone(monitor._read_l5_content_ar(3840, 2160))

    def test_uses_l5_without_title_or_year(self):
        monitor = self.make_monitor()

        class FakeAddon:
            def getSettingBool(self, name):
                return name == "enable_autofit"

        monitor.addon = FakeAddon()
        monitor.get_player_id = lambda: 1
        monitor._get_media_metadata = lambda: ("", "", False)
        monitor._make_identity = lambda player_id, title, year: (player_id, "file", title, year)
        monitor._reset_last_applied_view_mode = lambda player_id: None
        monitor._read_l5_content_ar = lambda width, height: (
            (0, 0, 280, 280),
            2.40,
        )
        monitor.execute_json_rpc = lambda method, params: {
            "currentvideostream": {"index": 0},
            "videostreams": [{"index": 0, "width": 3840, "height": 2160}],
        }
        monitor._submit_lookup = Mock()

        monitor._handle_av_started()

        request, content_ar = monitor._result_queue.get_nowait()
        self.assertEqual(request["aspect_source"], monitor.L5_ASPECT_SOURCE)
        self.assertAlmostEqual(content_ar, 2.40)
        monitor._submit_lookup.assert_not_called()

    def test_falls_back_to_bluray_when_l5_is_unavailable(self):
        monitor = self.make_monitor()

        class FakeAddon:
            def getSettingBool(self, name):
                return name == "enable_autofit"

        monitor.addon = FakeAddon()
        monitor.get_player_id = lambda: 1
        monitor._get_media_metadata = lambda: ("Example", "2020", False)
        monitor._make_identity = lambda player_id, title, year: (player_id, "file", title, year)
        monitor._reset_last_applied_view_mode = lambda player_id: None
        monitor._read_l5_content_ar = lambda width, height: None
        monitor.execute_json_rpc = lambda method, params: {
            "currentvideostream": {"index": 0},
            "videostreams": [{"index": 0, "width": 3840, "height": 2160}],
        }
        monitor._submit_lookup = Mock()

        monitor._handle_av_started()

        request = monitor._submit_lookup.call_args[0][0]
        self.assertEqual(request["aspect_source"], monitor.BLURAY_ASPECT_SOURCE)


if __name__ == "__main__":
    unittest.main()
