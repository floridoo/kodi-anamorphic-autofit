# -*- coding: utf-8 -*-
# Final version of the Anamorphic Auto Fit service addon.
# This addon automatically adjusts the zoom and pixel ratio for anamorphic projector setups
# by dynamically scraping the true aspect ratio of playing media.

import xbmc
import xbmcaddon
import json
import time
import re
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError

class AnamorphicPlayerMonitor(xbmc.Player):
    """
    A custom Kodi Player class that listens for playback events and triggers
    the anamorphic adjustment logic.
    """
    def __init__(self):
        super(AnamorphicPlayerMonitor, self).__init__()
        self.addon = xbmcaddon.Addon()
        self.log("Service initialized (Final Version with Comments).")

    def log(self, msg, level=xbmc.LOGINFO):
        """
A helper function for consistent and identifiable logging. All log messages
        from this addon will be prefixed with '[service.anamorphic.autofit]'.
        """
        xbmc.log(f"[service.anamorphic.autofit] {msg}", level=level)

    def execute_json_rpc(self, method, params):
        """
A centralized wrapper for executing Kodi's JSON-RPC commands.
        This handles the request creation, JSON conversion, and error logging
        for all API interactions.
        """
        try:
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1
            }
            response_str = xbmc.executeJSONRPC(json.dumps(request))
            response = json.loads(response_str)
            if "error" in response:
                self.log(f"JSON-RPC Error on {method}: {response['error']}", level=xbmc.LOGERROR)
                return None
            return response.get("result")
        except Exception as e:
            self.log(f"Failed to execute JSON-RPC {method}: {e}", level=xbmc.LOGERROR)
            return None

    def _get_aspect_ratio_from_bluray_com(self, title, year):
        """
        Searches blu-ray.com for a given title and year, follows the first
        search result, and scrapes the aspect ratio from the media's page.
        """
        if not title or not year:
            self.log("Title or year is missing, cannot perform web search.")
            return None

        search_term = f"{title} {year}"
        self.log(f"Searching online for aspect ratio of: {search_term}")

        try:
            # quote_plus is used to safely encode the search term for a URL.
            search_url = f"https://www.blu-ray.com/search/?quicksearch=1&quicksearch_country=US&quicksearch_keyword={quote_plus(search_term)}&section=all"
            # A User-Agent header is crucial to mimic a real web browser,
            # preventing the server from blocking our automated request.
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
            
            req = Request(search_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                search_html = response.read().decode('utf-8', errors='ignore')

            # NON-OBVIOUS CHOICE: This regex was chosen because the class names on the
            # search result links were unreliable. However, the URL structure itself
            # ('/movies/.../<id>/') is very consistent. This regex finds the first
            # full link matching that pattern, making it robust against site style changes.
            match = re.search(r'<a .*?href="(https://www.blu-ray.com/movies/.+?/\d+/)"', search_html)
            if not match:
                self.log(f"No movie link found in search results for '{search_term}'.")
                return None
            
            movie_url = match.group(1)
            self.log(f"Found movie page link: {movie_url}")

            # Now, fetch the content of the actual movie page.
            req = Request(movie_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                movie_html = response.read().decode('utf-8', errors='ignore')

            # This regex specifically looks for the "Aspect ratio: X.XX:1" text on the page.
            ar_match = re.search(r'Aspect ratio:\s*(\d+\.\d{2}):1', movie_html)
            if not ar_match:
                self.log("Could not find 'Aspect ratio' tag on the movie page.")
                return None

            aspect_ratio = float(ar_match.group(1))
            self.log(f"Successfully scraped aspect ratio: {aspect_ratio}")
            return aspect_ratio

        # This broad error handling ensures that any network failure (timeout,
        # server error, etc.) will be caught gracefully and will not crash the addon.
        except (URLError, HTTPError, TimeoutError) as e:
            self.log(f"Network error while scraping blu-ray.com: {e}", level=xbmc.LOGERROR)
            return None
        except Exception as e:
            self.log(f"An unexpected error occurred during web scraping: {e}", level=xbmc.LOGERROR)
            return None

    def onPlayBackStarted(self):
        """
        The main logic function, triggered when Kodi reports that playback has started.
        """
        # NON-OBVIOUS CHOICE: We increased this from 5 to 10 based on real-world
        # feedback that on some systems, the player can take a few seconds to
        # fully initialize. This provides a generous window for it to become ready.
        MAX_RETRIES = 10
        RETRY_DELAY_MS = 500

        # --- CRITICAL FIX: The `isPlayingVideo()` Retry Loop ---
        # NON-OBVIOUS CHOICE: The onPlayBackStarted event can fire milliseconds
        # *before* Kodi's internal player state is set to "playing". A simple check
        # would fail intermittently. This loop actively polls the player state,
        # making the addon timing-independent and far more reliable.
        player_is_ready = False
        for attempt in range(MAX_RETRIES):
            if self.isPlayingVideo():
                player_is_ready = True
                self.log(f"Player state is active on attempt {attempt + 1}. Proceeding.")
                break
            self.log(f"Attempt {attempt + 1}/{MAX_RETRIES}: Player is not yet active. Retrying...")
            xbmc.sleep(RETRY_DELAY_MS)
        
        if not player_is_ready:
            self.log("Player did not become active after all retries. Aborting adjustment.", level=xbmc.LOGERROR)
            return

        # --- Main logic starts now that we know the player is fully active ---
        self.log("Playback started. Analyzing video stream.")

        if not self.addon.getSettingBool('enable_autofit'):
            self.log("Addon is disabled in settings. Skipping.")
            return
            
        try:
            target_ar_str = self.addon.getSetting('target_ar')
            TARGET_SCREEN_AR = float(target_ar_str)
            self.log(f"Using Target Screen AR from settings: {TARGET_SCREEN_AR}")
        except (ValueError, TypeError):
            TARGET_SCREEN_AR = 2.40
            self.log(f"Could not parse Target AR setting. Falling back to default: {TARGET_SCREEN_AR}", level=xbmc.LOGWARNING)

        player_id = self.get_player_id()
        if player_id is None: return

        # --- Second Retry Loop for Stream Details ---
        # This provides a second layer of defense. Even if the player is "active",
        # the detailed stream properties (like resolution) might take a few more
        # moments to become available. This loop waits for that specific data.
        player_props = None
        for attempt in range(MAX_RETRIES):
            player_props = self.execute_json_rpc("Player.GetProperties", {"playerid": player_id, "properties": ["videostreams"]})
            if player_props and player_props.get("videostreams"):
                if player_props["videostreams"][0].get("width", 0) > 0:
                    self.log(f"Successfully got video stream info on attempt {attempt + 1}.")
                    break
            self.log(f"Attempt {attempt + 1}/{MAX_RETRIES}: Video stream details not yet available. Retrying...")
            xbmc.sleep(RETRY_DELAY_MS)
        else: # This 'else' belongs to the 'for' loop and runs if it completes without a 'break'.
            self.log("Failed to get video stream details after all retries. Aborting adjustment.", level=xbmc.LOGERROR)
            return

        # NON-OBVIOUS CHOICE: The 'properties' array is intentionally limited.
        # Requesting default properties like "label" or "type" can cause an
        # "Invalid params" error in modern Kodi versions (like Omega). We only
        # request the non-default properties we absolutely need.
        item_details = self.execute_json_rpc("Player.GetItem", {"playerid": player_id, "properties": ["showtitle", "premiered", "customproperties"]})
        if not item_details or "item" not in item_details:
            self.log("Could not get item details.", level=xbmc.LOGWARNING)
            return
        
        item = item_details["item"]
        
        # --- Hierarchical Media Type Determination ---
        # NON-OBVIOUS CHOICE: This logic provides the best of both worlds. It
        # prioritizes the specific `tmdb_type` if available (from a scraper),
        # but gracefully falls back to Kodi's built-in `item.type` if the
        # custom property doesn't exist, which is common for TV shows.
        custom_props = item.get("customproperties", {})
        tmdb_type = custom_props.get("tmdb_type")
        builtin_type = item.get("type") # e.g., 'movie', 'episode'
        final_media_type = tmdb_type or builtin_type # Python idiom for "use the first one that isn't None"
        
        if tmdb_type:
            self.log(f"Media type determined from tmdb_type: '{final_media_type}'")
        else:
            self.log(f"tmdb_type not found. Using fallback item.type: '{final_media_type}'")

        # Based on the determined type, we choose the correct title for searching.
        search_title = None
        if final_media_type in ['tvshow', 'episode']:
            search_title = item.get("showtitle") # The name of the whole series.
            self.log(f"Media is a TV Show/Episode. Using show title for search: '{search_title}'")
        else: # Default to movie logic.
            search_title = item.get("label") # The name of the movie.
            self.log(f"Media is a Movie. Using item label for search: '{search_title}'")
        
        # Robustly get the year from multiple possible sources.
        year = custom_props.get("premiered.year")
        if not year:
            premiered_date = item.get("premiered")
            if premiered_date and len(premiered_date) >= 4:
                year = premiered_date[:4]

        content_ar = self._get_aspect_ratio_from_bluray_com(search_title, year)
        final_ar = None

        if content_ar:
            self.log(f"Using successfully scraped AR: {content_ar}")
            final_ar = content_ar
        else:
            self.log("Using fallback AR logic based on media type.")
            if final_media_type == 'movie':
                final_ar = 2.39
                self.log(f"Fallback for movie: Assuming AR is {final_ar}")
            else: # Covers 'episode', 'tvshow', and None
                final_ar = 16.0 / 9.0 # 1.777...
                self.log(f"Fallback for TV Show (media type is '{final_media_type}'): Assuming AR is {final_ar:.3f}")

        if not final_ar:
            return

        video_stream = player_props["videostreams"][0]
        width, height = video_stream.get("width"), video_stream.get("height")
        video_ar = float(width) / float(height)
        self.log(f"Video resolution: {width}x{height}, Container AR: {video_ar:.3f}")

        # This is the main trigger condition: the video file must be 16:9, and the
        # actual content must be wider (indicating black bars).
        if 1.77 < video_ar < 1.79 and final_ar > video_ar + 0.01:
            self.log("16:9 container with wider content detected. Applying anamorphic adjustments.")
            
            # --- CRITICAL FIX: The Smart Zoom Calculation ---
            # NON-OBVIOUS CHOICE: This is the core of the smart zoom. We use the
            # smaller of the two values (the movie's AR vs. your screen's AR).
            # This prevents two problems:
            # 1. Cropping the sides off a movie that is WIDER than your screen.
            # 2. Over-zooming a movie that is NARROWER than your screen, cropping the top/bottom.
            effective_ar = min(final_ar, TARGET_SCREEN_AR)
            self.log(f"Using effective AR for zoom: {effective_ar:.3f} (min of Content AR {final_ar:.3f} and Screen AR {TARGET_SCREEN_AR:.3f})")
            
            zoom_factor = effective_ar / video_ar
            ANAMORPHIC_PIXEL_RATIO = (16.0 / 9.0) / TARGET_SCREEN_AR

            self.log(f"Calculated Zoom Factor: {zoom_factor:.3f}")
            self.log(f"Applying Pixel Ratio: {ANAMORPHIC_PIXEL_RATIO:.4f}")

            # NON-OBVIOUS CHOICE: For Kodi Omega and later, SetViewMode takes a
            # single parameter: a dictionary named 'viewmode'. It no longer accepts
            # a playerid, as it acts on the active player implicitly.
            view_mode_params = {"viewmode": {"zoom": zoom_factor, "pixelratio": ANAMORPHIC_PIXEL_RATIO}}
            self.execute_json_rpc("Player.SetViewMode", view_mode_params)
            self.log("Custom view mode applied successfully.")
        else:
            self.log(f"No adjustment needed. Container AR: {video_ar:.3f}, Content AR: {final_ar:.3f}")

    def onPlayBackStopped(self):
        self.log("Playback stopped.")
        # No action is needed here because the new SetViewMode method only
        # affects the current playback session and doesn't change global settings.
        pass

    def onPlayBackEnded(self):
        self.onPlayBackStopped()

    def get_player_id(self):
        """Finds the active video player ID."""
        players = self.execute_json_rpc("Player.GetActivePlayers", {})
        if players:
            for player in players:
                if player["type"] == "video":
                    return player["playerid"]
        self.log("No active video player found.", level=xbmc.LOGWARNING)
        return None

if __name__ == '__main__':
    monitor = xbmc.Monitor()
    player_monitor = AnamorphicPlayerMonitor()
    player_monitor.log("Service started and waiting for playback.")

    # A monitor loop is required for a service addon to keep it running.
    while not monitor.abortRequested():
        if monitor.waitForAbort(10):
            break
