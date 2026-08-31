# -*- coding: utf-8 -*-
"""Kodi service that applies anamorphic zoom to suitable 16:9 video."""

import json
import math
import queue
import threading
import time
import traceback

import xbmc
import xbmcaddon

from aspect_provider import CACHE_MISS, BlurayAspectRatioProvider, make_lookup_key, normalize_year
from logic import (
    DEFAULT_TARGET_AR,
    aspect_ratio_from_dimensions,
    aspect_ratio_from_l5_offsets,
    calculate_view_mode,
    is_16_9_container,
    is_valid_target_ar,
    parse_l5_offsets,
    parse_target_ar,
)


class AnamorphicPlayerMonitor(xbmc.Player):
    """Listen for playback events and apply a safe, reversible view mode."""

    L5_SAMPLE_COUNT = 3
    L5_SAMPLE_INTERVAL = 0.05
    L5_ASPECT_SOURCE = "CoreELEC Dolby Vision L5"
    BLURAY_ASPECT_SOURCE = "blu-ray.com"
    L5_HAS_LABEL = "Player.Process(video.dovi.has.l5)"
    L5_OFFSET_LABELS = (
        "Player.Process(video.dovi.l5.left.offset)",
        "Player.Process(video.dovi.l5.right.offset)",
        "Player.Process(video.dovi.l5.top.offset)",
        "Player.Process(video.dovi.l5.bottom.offset)",
    )

    def __init__(self):
        super(AnamorphicPlayerMonitor, self).__init__()
        self.addon = xbmcaddon.Addon()
        self.aspect_provider = BlurayAspectRatioProvider(logger=self.log)
        self._result_queue = queue.Queue()
        self._state_lock = threading.RLock()
        self._current_identity = None
        self._inflight = {}
        self._shutdown = threading.Event()
        self._last_applied_view_mode = None
        self.log("Service initialized")

    def log(self, msg, level=xbmc.LOGINFO):
        """Write consistently prefixed messages to Kodi's log."""
        xbmc.log(f"[service.anamorphic.autofit] {msg}", level=level)

    def execute_json_rpc(self, method, params):
        """Execute a JSON-RPC call and return its result, or ``None`` on error."""
        try:
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1,
            }
            response_text = xbmc.executeJSONRPC(json.dumps(request))
            if not response_text:
                self.log(f"Empty JSON-RPC response for {method}.", level=xbmc.LOGERROR)
                return None
            response = json.loads(response_text)
            if not isinstance(response, dict):
                self.log(f"Invalid JSON-RPC response for {method}.", level=xbmc.LOGERROR)
                return None
            if "error" in response:
                self.log(
                    f"JSON-RPC error on {method}: {response['error']}",
                    level=xbmc.LOGERROR,
                )
                return None
            return response.get("result")
        except (TypeError, ValueError) as error:
            self.log(f"Invalid JSON-RPC response for {method}: {error}", level=xbmc.LOGERROR)
        except Exception as error:
            self.log(f"Failed to execute JSON-RPC {method}: {error}", level=xbmc.LOGERROR)
        return None

    def _get_info_label(self, label):
        try:
            return (xbmc.getInfoLabel(label) or "").strip()
        except Exception as error:
            self.log(f"Could not read InfoLabel {label}: {error}", level=xbmc.LOGWARNING)
            return ""

    def _get_media_metadata(self):
        show_title = self._get_info_label("VideoPlayer.TVShowTitle")
        title = (
            show_title
            or self._get_info_label("VideoPlayer.Title")
            or self._get_info_label("Player.Title")
            or self._get_info_label("VideoPlayer.OriginalTitle")
        )
        raw_year = self._get_info_label("VideoPlayer.Year") or self._get_info_label(
            "VideoPlayer.Premiered"
        )
        year = normalize_year(raw_year)
        return title, year, bool(show_title)

    def _get_target_ar(self):
        raw_value = self.addon.getSetting("target_ar")
        if not is_valid_target_ar(raw_value):
            self.log(
                f"Invalid target_ar setting {raw_value!r}; using default {DEFAULT_TARGET_AR:.2f}.",
                level=xbmc.LOGWARNING,
            )
        return parse_target_ar(raw_value)

    def _playing_file(self):
        try:
            return self.getPlayingFile() or ""
        except Exception:
            return ""

    def _make_identity(self, player_id, title, year):
        return (player_id, self._playing_file(), title, year)

    def _select_video_stream(self, player_props):
        streams = player_props.get("videostreams") or []
        if not isinstance(streams, list) or not streams:
            return None

        current = player_props.get("currentvideostream") or {}
        current_index = current.get("index") if isinstance(current, dict) else None
        if current_index is not None:
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                stream_index = stream.get("index")
                if stream_index == current_index or str(stream_index) == str(current_index):
                    return stream
        return streams[0] if isinstance(streams[0], dict) else None

    def _read_l5_sample(self, width, height):
        """Read one validated CoreELEC L5 sample, if this build exposes it."""
        if self._get_info_label(self.L5_HAS_LABEL) != "1":
            return None

        raw_offsets = [self._get_info_label(label) for label in self.L5_OFFSET_LABELS]
        offsets = parse_l5_offsets(*raw_offsets)
        if offsets is None:
            return None

        content_ar = aspect_ratio_from_l5_offsets(width, height, *offsets)
        if content_ar is None:
            return None
        return offsets, content_ar

    def _read_l5_content_ar(self, width, height):
        """Return a stable L5 active-area result, or ``None`` if unavailable."""
        samples = []
        for index in range(self.L5_SAMPLE_COUNT):
            samples.append(self._read_l5_sample(width, height))
            if index + 1 < self.L5_SAMPLE_COUNT and self.L5_SAMPLE_INTERVAL > 0:
                time.sleep(self.L5_SAMPLE_INTERVAL)

        if not samples or any(sample is None for sample in samples):
            return None

        first_offsets, first_content_ar = samples[0]
        if any(offsets != first_offsets for offsets, _content_ar in samples[1:]):
            self.log(
                "CoreELEC Dolby Vision L5 offsets changed during startup; "
                "using the online aspect-ratio fallback.",
                level=xbmc.LOGWARNING,
            )
            return None
        return first_offsets, first_content_ar

    def _handle_av_started(self):
        self.log("onAVStarted event triggered. Analyzing video stream.")
        player_id = self.get_player_id()
        if player_id is None:
            return

        title, year, is_tv_show = self._get_media_metadata()
        identity = self._make_identity(player_id, title, year)
        with self._state_lock:
            previous_identity = self._current_identity
            self._current_identity = identity

        if previous_identity != identity:
            self._reset_last_applied_view_mode(player_id)

        self.log(
            f"Media identified via InfoLabels: Title='{title}', Year='{year}', "
            f"IsTVShow={is_tv_show}"
        )

        if not self.addon.getSettingBool("enable_autofit"):
            self.log("Addon is disabled in settings. Skipping.")
            return
        player_props = self.execute_json_rpc(
            "Player.GetProperties",
            {
                "playerid": player_id,
                "properties": ["currentvideostream", "videostreams"],
            },
        )
        if not isinstance(player_props, dict):
            self.log("Could not retrieve video stream details. Aborting.", level=xbmc.LOGWARNING)
            return

        video_stream = self._select_video_stream(player_props)
        if video_stream is None:
            self.log("No video stream was available. Aborting.", level=xbmc.LOGWARNING)
            return

        video_ar = aspect_ratio_from_dimensions(
            video_stream.get("width"), video_stream.get("height")
        )
        if video_ar is None:
            self.log(
                "Video stream width or height is invalid. Aborting.",
                level=xbmc.LOGWARNING,
            )
            return

        self.log(
            f"Video resolution: {video_stream.get('width')}x{video_stream.get('height')}, "
            f"Container AR: {video_ar:.3f}"
        )
        if not is_16_9_container(video_ar):
            self.log("Video container is not 16:9. No adjustments needed.")
            return

        l5_result = self._read_l5_content_ar(
            video_stream.get("width"), video_stream.get("height")
        )
        request = {
            "identity": identity,
            "title": title,
            "year": year,
            "video_ar": video_ar,
        }

        if l5_result is not None:
            l5_offsets, content_ar = l5_result
            request.update(
                {
                    "aspect_source": self.L5_ASPECT_SOURCE,
                    "l5_offsets": l5_offsets,
                }
            )
            self.log(
                f"Using {self.L5_ASPECT_SOURCE}: offsets="
                f"{l5_offsets[0]}/{l5_offsets[1]}/{l5_offsets[2]}/{l5_offsets[3]}, "
                f"content AR={content_ar:.3f}"
            )
            self._result_queue.put((request, content_ar))
            return

        if not title or not year:
            self.log(
                "Title or year is missing; skipping online aspect-ratio lookup.",
                level=xbmc.LOGWARNING,
            )
            return

        request["aspect_source"] = self.BLURAY_ASPECT_SOURCE
        self._submit_lookup(request)

    def onAVStarted(self):
        """Start an asynchronous lookup after Kodi has initialized the stream."""
        try:
            self._handle_av_started()
        except Exception:
            self.log(
                "Unhandled error while processing onAVStarted:\n"
                + traceback.format_exc(),
                level=xbmc.LOGERROR,
            )

    def _submit_lookup(self, request):
        key = make_lookup_key(request["title"], request["year"])
        cached = self.aspect_provider.get_cached(request["title"], request["year"])
        if cached is not CACHE_MISS:
            self._result_queue.put((request, cached))
            return

        with self._state_lock:
            pending = self._inflight.get(key)
            if pending is not None:
                pending.append(request)
                return
            self._inflight[key] = [request]

        worker = threading.Thread(
            target=self._lookup_worker,
            args=(key, request["title"], request["year"]),
            name="anamorphic-aspect-lookup",
            daemon=True,
        )
        try:
            worker.start()
        except Exception:
            with self._state_lock:
                self._inflight.pop(key, None)
            self.log("Could not start aspect-ratio lookup worker.", level=xbmc.LOGERROR)

    def _lookup_worker(self, key, title, year):
        try:
            content_ar = self.aspect_provider.lookup(
                title, year, abort_event=self._shutdown
            )
        except Exception:
            content_ar = None
            self.log(
                "Unhandled error in aspect-ratio lookup:\n" + traceback.format_exc(),
                level=xbmc.LOGERROR,
            )

        with self._state_lock:
            requests = self._inflight.pop(key, [])
        for request in requests:
            self._result_queue.put((request, content_ar))

    def process_results(self):
        """Apply completed lookup results on the Kodi service thread."""
        while True:
            try:
                request, content_ar = self._result_queue.get_nowait()
            except queue.Empty:
                return

            with self._state_lock:
                is_current = request["identity"] == self._current_identity
            if not is_current:
                self.log("Discarding a stale aspect-ratio result.")
                continue
            if content_ar is None:
                self.log(
                    f"{request.get('aspect_source', self.BLURAY_ASPECT_SOURCE)} "
                    "aspect-ratio lookup failed; leaving the current view unchanged."
                )
                continue

            view_mode = calculate_view_mode(
                request["video_ar"], content_ar, self._get_target_ar()
            )
            if view_mode is None:
                self.log(
                    f"No adjustment needed for "
                    f"{request.get('aspect_source', self.BLURAY_ASPECT_SOURCE)} "
                    f"content AR ({content_ar:.3f}) and "
                    f"container AR ({request['video_ar']:.3f})."
                )
                continue

            self._apply_view_mode(request, content_ar, view_mode)

    def _apply_view_mode(self, request, content_ar, view_mode):
        self.log(
            f"Applying anamorphic adjustment from "
            f"{request.get('aspect_source', self.BLURAY_ASPECT_SOURCE)} "
            f"for content AR {content_ar:.3f}: "
            f"zoom={view_mode['zoom']:.3f}, pixelratio={view_mode['pixelratio']:.4f}"
        )
        # Player.SetViewMode targets Kodi's current video player and accepts
        # only the viewmode object; unlike most Player methods, it has no
        # playerid parameter.
        result = self.execute_json_rpc(
            "Player.SetViewMode",
            {"viewmode": view_mode},
        )
        if result is None:
            self.log("Kodi rejected the custom view mode.", level=xbmc.LOGERROR)
            return

        with self._state_lock:
            if request["identity"] == self._current_identity:
                self._last_applied_view_mode = {
                    "player_id": request["identity"][0],
                    "identity": request["identity"],
                    "viewmode": dict(view_mode),
                }
        self.log("Custom view mode applied successfully.")

    @staticmethod
    def _same_view_mode(actual, expected):
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            return False
        try:
            return math.isclose(
                float(actual.get("zoom")),
                float(expected["zoom"]),
                rel_tol=1e-4,
                abs_tol=1e-4,
            ) and math.isclose(
                float(actual.get("pixelratio")),
                float(expected["pixelratio"]),
                rel_tol=1e-4,
                abs_tol=1e-4,
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _reset_last_applied_view_mode(self, player_id):
        with self._state_lock:
            applied = self._last_applied_view_mode
        if not applied or applied["player_id"] != player_id:
            return

        # Player.GetViewMode likewise has no parameters in Kodi's JSON-RPC API.
        current = self.execute_json_rpc("Player.GetViewMode", {})
        if current is None:
            return
        if not self._same_view_mode(current, applied["viewmode"]):
            with self._state_lock:
                if self._last_applied_view_mode is applied:
                    self._last_applied_view_mode = None
            self.log("Keeping the current view mode because it changed after auto-fit.")
            return

        result = self.execute_json_rpc(
            "Player.SetViewMode",
            {"viewmode": "normal"},
        )
        if result is None:
            self.log("Could not restore Kodi's normal view mode.", level=xbmc.LOGWARNING)
            return

        with self._state_lock:
            if self._last_applied_view_mode is applied:
                self._last_applied_view_mode = None
        self.log("Restored Kodi's normal view mode after auto-fit.")

    def onPlayBackStopped(self):
        try:
            self.log("Playback stopped.")
            player_id = self.get_player_id(log_missing=False)
            if player_id is not None:
                self._reset_last_applied_view_mode(player_id)
            with self._state_lock:
                self._current_identity = None
        except Exception:
            self.log(
                "Unhandled error while processing playback stop:\n" + traceback.format_exc(),
                level=xbmc.LOGERROR,
            )

    def onPlayBackEnded(self):
        self.onPlayBackStopped()

    def get_player_id(self, log_missing=True):
        """Return the active video player ID, if Kodi has one."""
        players = self.execute_json_rpc("Player.GetActivePlayers", {})
        if isinstance(players, list):
            for player in players:
                if isinstance(player, dict) and player.get("type") == "video":
                    player_id = player.get("playerid")
                    if player_id is not None:
                        return player_id
        if log_missing:
            self.log("No active video player found.", level=xbmc.LOGWARNING)
        return None

    def shutdown(self):
        """Stop new lookups; already-running requests are allowed to finish safely."""
        self._shutdown.set()
        with self._state_lock:
            self._current_identity = None


if __name__ == "__main__":
    player_monitor = AnamorphicPlayerMonitor()
    monitor = xbmc.Monitor()
    try:
        while not monitor.abortRequested():
            player_monitor.process_results()
            if monitor.waitForAbort(0.25):
                break
    finally:
        player_monitor.shutdown()
