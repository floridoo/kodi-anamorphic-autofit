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
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

class AnamorphicPlayerMonitor(xbmc.Player):
    """
    A custom Kodi Player class that listens for playback events and triggers
    the anamorphic adjustment logic.
    """
    def __init__(self):
        super(AnamorphicPlayerMonitor, self).__init__()
        self.addon = xbmcaddon.Addon()
        self.log("Service initialized")

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
        Searches blu-ray.com and scrapes the aspect ratio. It uses an efficient
        POST request and requires both a title and a year for accuracy.
        """
        if not title or not year:
            self.log("Title or year is missing. Bailing out of web search for accuracy.", level=xbmc.LOGWARNING)
            return None

        search_term = f"{title} {year}"

        # A User-Agent header is crucial to mimic a real web browser,
        # preventing the server from blocking our automated request.
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        self.log(f"Attempting online search with term: '{search_term}'")
        try:
            # NON-OBVIOUS CHOICE: This uses a direct POST request to the search API,
            # which returns a small, fast, and easy-to-parse JavaScript snippet
            # instead of a full HTML page. This is much more efficient.
            post_url = 'https://www.blu-ray.com/search/quicksearch.php'
            post_data = {
                'section': 'bluraymovies',
                'userid': '-1',
                'country': 'US',
                'keyword': search_term
            }
            # The data must be URL-encoded and then converted to bytes for the request.
            encoded_data = urlencode(post_data).encode('utf-8')
            
            req = Request(post_url, data=encoded_data, headers=headers)
            with urlopen(req, timeout=10) as response:
                search_response = response.read().decode('utf-8', errors='ignore')

            # NON-OBVIOUS CHOICE: We parse the raw JavaScript to find the first URL
            # in the 'urls' array. This is more robust than parsing HTML tags.
            # It looks for `var urls = new Array('...url...')` and captures the URL.
            match = re.search(r"var urls = new Array\('([^']+)'", search_response)
            if not match:
                self.log(f"Could not parse JS URL array for search term: '{search_term}'.")
                return None
            
            movie_url = match.group(1)
            self.log(f"Found movie page link from JS response: {movie_url}")

            # Now, fetch the content of the actual movie page.
            req = Request(movie_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                movie_html = response.read().decode('utf-8', errors='ignore')

            # This regex specifically looks for the "Aspect ratio: X.XX:1" text on the page.
            ar_match = re.search(r'Aspect ratio:\s*(\d+\.\d{2}):1', movie_html)
            if not ar_match:
                self.log(f"Could not find 'Aspect ratio' tag for search term: '{search_term}'.")
                return None

            aspect_ratio = float(ar_match.group(1))
            self.log(f"Successfully scraped aspect ratio: {aspect_ratio}")
            return aspect_ratio # Success! Exit the function with the result.

        # This broad error handling ensures that any network failure (timeout,
        # server error, etc.) will be caught gracefully and will not crash the addon.
        except (URLError, HTTPError, TimeoutError) as e:
            self.log(f"Network error while searching for '{search_term}': {e}", level=xbmc.LOGERROR)
        except Exception as e:
            self.log(f"An unexpected error occurred during web scraping for '{search_term}': {e}", level=xbmc.LOGERROR)
        
        self.log(f"Search attempt failed for '{search_term}'.")
        return None
    
    def onAVStarted(self):
        """
        The main logic function.
        NON-OBVIOUS CHOICE: This is triggered by onAVStarted, not onPlayBackStarted.
        onAVStarted fires when the first video frame is rendered, which guarantees
        that the player is fully initialized and video stream details are available.
        This completely eliminates timing issues and the need for unreliable retry loops.
        """
        self.log("onAVStarted event triggered. Analyzing video stream.")

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

        # --- UNIVERSAL METADATA LOGIC (InfoLabels) ---
        # NON-OBVIOUS CHOICE: This is the most robust method. We read the same InfoLabels
        # that the skin uses. By the time onAVStarted fires, Kodi's player state has
        # been updated by any running metadata addons, making this data accurate.
        is_tv_show = bool(xbmc.getInfoLabel('VideoPlayer.TVShowTitle'))
        search_title = xbmc.getInfoLabel('VideoPlayer.TVShowTitle') or xbmc.getInfoLabel('Player.Title')
        year = xbmc.getInfoLabel('VideoPlayer.Year')

        self.log(f"Media identified via InfoLabels: Title='{search_title}', Year='{year}', IsTVShow={is_tv_show}")
        
        player_id = self.get_player_id()
        if player_id is None: return

        # Get video stream properties to check the container aspect ratio.
        player_props = self.execute_json_rpc("Player.GetProperties", {"playerid": player_id, "properties": ["videostreams"]})
        if not (player_props and player_props.get("videostreams")):
            self.log("Could not retrieve video stream details. Aborting.", level=xbmc.LOGWARNING)
            return

        video_stream = player_props["videostreams"][0]
        width, height = video_stream.get("width"), video_stream.get("height")

        if not width or not height:
            self.log("Video stream width or height is missing. Aborting.", level=xbmc.LOGWARNING)
            return

        video_ar = float(width) / float(height)
        self.log(f"Video resolution: {width}x{height}, Container AR: {video_ar:.3f}")

        # --- Early Exit Optimization ---
        if not (1.77 < video_ar < 1.79):
            self.log("Video container is not 16:9. No adjustments needed. Bailing out early.")
            return

        content_ar = self._get_aspect_ratio_from_bluray_com(search_title, year)

        # If scraping fails, bail out. No fallback is used.
        if not content_ar:
            self.log("Could not scrape aspect ratio, and no fallback is configured. No adjustments will be made.")
            return

        # The final trigger condition.
        if content_ar > video_ar + 0.01:
            self.log("16:9 container with wider content detected. Applying anamorphic adjustments.")
            
            # --- CRITICAL FIX: The Smart Zoom Calculation ---
            effective_ar = min(content_ar, TARGET_SCREEN_AR)
            self.log(f"Using effective AR for zoom: {effective_ar:.3f} (min of Content AR {content_ar:.3f} and Screen AR {TARGET_SCREEN_AR:.3f})")
            
            zoom_factor = effective_ar / video_ar
            ANAMORPHIC_PIXEL_RATIO = (16.0 / 9.0) / TARGET_SCREEN_AR

            self.log(f"Calculated Zoom Factor: {zoom_factor:.3f}")
            self.log(f"Applying Pixel Ratio: {ANAMORPHIC_PIXEL_RATIO:.4f}")

            view_mode_params = {"viewmode": {"zoom": zoom_factor, "pixelratio": ANAMORPHIC_PIXEL_RATIO}}
            self.execute_json_rpc("Player.SetViewMode", view_mode_params)
            self.log("Custom view mode applied successfully.")
        else:
            self.log(f"No adjustment needed. Content AR ({content_ar:.3f}) is not wider than Container AR ({video_ar:.3f}).")

    def onPlayBackStopped(self):
        self.log("Playback stopped.")
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
    player_monitor = AnamorphicPlayerMonitor()
    
    # The monitor loop's only job is to keep the addon running.
    # All logic is now handled by the event-driven Player class.
    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(10):
            break
            
    del player_monitor
