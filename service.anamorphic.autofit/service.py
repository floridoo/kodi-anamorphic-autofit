import xbmc
import xbmcaddon
import json
import time
import re
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError

class AnamorphicPlayerMonitor(xbmc.Player):
    def __init__(self):
        super(AnamorphicPlayerMonitor, self).__init__()
        self.addon = xbmcaddon.Addon()
        self.log("Service initialized (Regex/RPC Fix).")

    def log(self, msg, level=xbmc.LOGINFO):
        """Helper function for logging."""
        xbmc.log(f"[service.anamorphic.autofit] {msg}", level=level)

    def execute_json_rpc(self, method, params):
        """Helper function to execute a JSON-RPC command."""
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
        Searches blu-ray.com for a given title and year, and scrapes the
        aspect ratio from the movie's page.
        """
        if not title or not year:
            self.log("Title or year is missing, cannot perform web search.")
            return None

        search_term = f"{title} {year}"
        self.log(f"Searching online for aspect ratio of: {search_term}")

        try:
            search_url = f"https://www.blu-ray.com/search/?quicksearch=1&quicksearch_country=US&quicksearch_keyword={quote_plus(search_term)}&section=all"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
            
            req = Request(search_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                search_html = response.read().decode('utf-8', errors='ignore')

            match = re.search(r'<a .*?href="(https://www.blu-ray.com/movies/.+?/\d+/)"', search_html)
            if not match:
                self.log(f"No movie link found in search results for '{search_term}'.")
                return None
            
            movie_url = match.group(1)
            self.log(f"Found movie page link: {movie_url}")

            req = Request(movie_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                movie_html = response.read().decode('utf-8', errors='ignore')

            ar_match = re.search(r'Aspect ratio:\s*(\d+\.\d{2}):1', movie_html)
            if not ar_match:
                self.log("Could not find 'Aspect ratio' tag on the movie page.")
                return None

            aspect_ratio = float(ar_match.group(1))
            self.log(f"Successfully scraped aspect ratio: {aspect_ratio}")
            return aspect_ratio

        except (URLError, HTTPError, TimeoutError) as e:
            self.log(f"Network error while scraping blu-ray.com: {e}", level=xbmc.LOGERROR)
            return None
        except Exception as e:
            self.log(f"An unexpected error occurred during web scraping: {e}", level=xbmc.LOGERROR)
            return None

    def onPlayBackStarted(self):
        """Called when Kodi starts playing a file."""
        xbmc.sleep(2000)

        if not self.addon.getSettingBool('enable_autofit'):
            self.log("Addon is disabled in settings. Skipping.")
            return

        if self.isPlayingVideo():
            self.log("Playback started. Analyzing video stream.")
            
            try:
                target_ar_str = self.addon.getSetting('target_ar')
                TARGET_SCREEN_AR = float(target_ar_str)
                self.log(f"Using Target Screen AR from settings: {TARGET_SCREEN_AR}")
            except (ValueError, TypeError):
                TARGET_SCREEN_AR = 2.40
                self.log(f"Could not parse Target AR setting. Falling back to default: {TARGET_SCREEN_AR}", level=xbmc.LOGWARNING)

            player_id = self.get_player_id()
            if player_id is None: return

            item_details = self.execute_json_rpc("Player.GetItem", {"playerid": player_id, "properties": ["premiered", "customproperties"]})
            if not item_details or "item" not in item_details:
                self.log("Could not get item details.", level=xbmc.LOGWARNING)
                return
            
            item = item_details["item"]
            
            title = item.get("label")
            custom_props = item.get("customproperties", {})
            media_type = custom_props.get("tmdb_type")
            
            year = custom_props.get("premiered.year")
            if not year:
                premiered_date = item.get("premiered")
                if premiered_date and len(premiered_date) >= 4:
                    year = premiered_date[:4]

            content_ar = self._get_aspect_ratio_from_bluray_com(title, year)
            final_ar = None

            if content_ar:
                self.log(f"Using successfully scraped AR: {content_ar}")
                final_ar = content_ar
            else:
                self.log("Using fallback AR logic based on media type.")
                if media_type == 'movie':
                    final_ar = 2.39
                    self.log(f"Fallback for movie: Assuming AR is {final_ar}")
                elif media_type in ['tvshow', 'episode']:
                    final_ar = 16.0 / 9.0
                    self.log(f"Fallback for TV Show: Assuming AR is {final_ar:.3f}")
                else:
                    self.log(f"Media type '{media_type}' is not recognized for fallback. No adjustments will be made.")

            if not final_ar:
                return

            player_props = self.execute_json_rpc("Player.GetProperties", {"playerid": player_id, "properties": ["videostreams"]})
            if player_props and player_props.get("videostreams"):
                video_stream = player_props["videostreams"][0]
                width, height = video_stream.get("width"), video_stream.get("height")

                if not width or not height:
                    self.log("Could not determine video resolution.", level=xbmc.LOGWARNING)
                    return

                video_ar = float(width) / float(height)
                self.log(f"Video resolution: {width}x{height}, Container AR: {video_ar:.3f}")

                if 1.77 < video_ar < 1.79 and final_ar > video_ar + 0.01:
                    self.log("16:9 container with wider content detected. Applying anamorphic adjustments.")
                    
                    effective_ar = min(final_ar, TARGET_SCREEN_AR)
                    self.log(f"Using effective AR for zoom: {effective_ar:.3f} (min of Content AR {final_ar:.3f} and Screen AR {TARGET_SCREEN_AR:.3f})")
                    
                    zoom_factor = effective_ar / video_ar
                    ANAMORPHIC_PIXEL_RATIO = (16.0 / 9.0) / TARGET_SCREEN_AR

                    self.log(f"Calculated Zoom Factor: {zoom_factor:.3f}")
                    self.log(f"Applying Pixel Ratio: {ANAMORPHIC_PIXEL_RATIO:.4f}")

                    view_mode_params = {"viewmode": {"zoom": zoom_factor, "pixelratio": ANAMORPHIC_PIXEL_RATIO}}
                    self.execute_json_rpc("Player.SetViewMode", view_mode_params)
                    self.log("Custom view mode applied successfully.")
                else:
                    self.log(f"No adjustment needed. Container AR: {video_ar:.3f}, Content AR: {final_ar:.3f}")

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
    monitor = xbmc.Monitor()
    player_monitor = AnamorphicPlayerMonitor()
    player_monitor.log("Service started and waiting for playback.")

    while not monitor.abortRequested():
        if monitor.waitForAbort(10):
            break
