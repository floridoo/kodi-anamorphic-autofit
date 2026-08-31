import os
import sys
import threading
import types
import unittest


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


if __name__ == "__main__":
    unittest.main()
