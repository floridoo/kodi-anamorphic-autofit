import xbmc
import xbmcaddon
import json
import time

class AnamorphicPlayerMonitor(xbmc.Player):
    def __init__(self):
        super(AnamorphicPlayerMonitor, self).__init__()
        self.addon = xbmcaddon.Addon()
        self.log("Service initialized (Configurable AR).")

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

    def onPlayBackStarted(self):
        """Called when Kodi starts playing a file."""
        xbmc.sleep(2000)

        if not self.addon.getSettingBool('enable_autofit'):
            self.log("Addon is disabled in settings. Skipping.")
            return

        if self.isPlayingVideo():
            self.log("Playback started. Analyzing video stream.")
            
            # --- CONFIGURATION (NOW FROM SETTINGS) ---
            try:
                # Read the target AR from the settings.xml file
                target_ar_str = self.addon.getSetting('target_ar')
                TARGET_SCREEN_AR = float(target_ar_str)
                self.log(f"Using Target Screen AR from settings: {TARGET_SCREEN_AR}")
            except (ValueError, TypeError):
                # Fallback to default if setting is invalid or empty
                TARGET_SCREEN_AR = 2.40
                self.log(f"Could not parse Target AR setting. Falling back to default: {TARGET_SCREEN_AR}", level=xbmc.LOGWARNING)

            ANAMORPHIC_PIXEL_RATIO = (16.0 / 9.0) / TARGET_SCREEN_AR

            player_id = self.get_player_id()
            if player_id is None:
                return

            item_details = self.execute_json_rpc("Player.GetItem", {"playerid": player_id, "properties": ["customproperties"]})
            if not item_details or "item" not in item_details:
                self.log("Could not get item details.", level=xbmc.LOGWARNING)
                return
            
            media_type = item_details["item"].get("customproperties", {}).get("tmdb_type")
            # self.log(json.dumps(item_details))
            self.log(f"Media type identified as: {media_type}")
            
            if media_type != "movie":
                self.log(f"Media is not a movie ('{media_type}'). No adjustments will be made.")
                return

            player_props = self.execute_json_rpc("Player.GetProperties", {"playerid": player_id, "properties": ["videostreams"]})
            if player_props and player_props.get("videostreams"):
                video_stream = player_props["videostreams"][0]
                width = video_stream.get("width")
                height = video_stream.get("height")

                if not width or not height:
                    self.log("Could not determine video resolution.", level=xbmc.LOGWARNING)
                    return

                video_ar = float(width) / float(height)
                self.log(f"Video resolution: {width}x{height}, Aspect Ratio: {video_ar:.3f}")

                if 1.77 < video_ar < 1.79:
                    self.log("16:9 video container detected. Applying anamorphic adjustments.")
                    
                    zoom_factor = TARGET_SCREEN_AR / video_ar
                    self.log(f"Calculated Zoom Factor: {zoom_factor:.3f}")
                    self.log(f"Applying Pixel Ratio: {ANAMORPHIC_PIXEL_RATIO:.4f}")

                    view_mode_params = {
                        "viewmode": {
                            "zoom": zoom_factor,
                            "pixelratio": ANAMORPHIC_PIXEL_RATIO
                        }
                    }
                    self.execute_json_rpc("Player.SetViewMode", view_mode_params)
                    self.log("Custom view mode applied successfully.")
                else:
                    self.log(f"Video is not 16:9 ({video_ar:.3f}). No adjustments needed.")
            else:
                self.log("Could not retrieve video stream details.", level=xbmc.LOGWARNING)

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
