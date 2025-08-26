# Anamorphic Auto Fit for Kodi

A smart service addon for Kodi designed for users with anamorphic projector setups and widescreen (e.g., 2.40:1) screens. This addon runs in the background and intelligently eliminates the "postage stamp" black bars that appear when playing letterboxed media.

## The Problem

If you use a 16:9 projector with an anamorphic lens to fill a 2.40:1 screen, you've likely encountered this frustrating issue:

1.  You play a movie that has a true aspect ratio of 2.40:1.
2.  However, the video file itself is encoded at 16:9 with black bars "baked into" the top and bottom (letterboxing).
3.  When your anamorphic lens stretches this 16:9 image, the result is an image with black bars on **all four sides**—a small picture in the middle of your large, cinematic screen.

Manually adjusting the zoom for every single movie is tedious and imprecise.

## The Solution: A "Smart Zoom" Service

This addon automates the process perfectly. When a video starts playing, it:

1.  **Detects Playback:** Automatically triggers when a movie or TV show begins.
2.  **Identifies the Media:** It robustly determines if you're watching a movie or a TV episode and identifies its title and year.
3.  **Finds the True Aspect Ratio:** It performs a quick search on [blu-ray.com](https://www.blu-ray.com) to find the *original, intended aspect ratio* of the content (e.g., "2.39:1", "1.85:1").
4.  **Calculates the Perfect Zoom:** It compares the content's true aspect ratio to the video file's 16:9 container and calculates the precise zoom level needed to fill your screen's width, eliminating the vertical black bars.
5.  **Applies the Fix:** The addon programmatically sets the custom zoom and pixel ratio, just as you would manually, but does so automatically in milliseconds.

The logic is smart: if a movie's aspect ratio is even wider than your screen, it will not over-zoom and crop the image. It always calculates the safest zoom level to maximize picture size without losing any content.

## Features

-   **Fully Automatic:** Runs as a background service. "Set it and forget it."
-   **Dynamic Aspect Ratio Lookup:** No fixed settings. The addon finds the correct aspect ratio for each specific movie or show online.
-   **Intelligent Zoom Calculation:** Prevents cropping of content that is wider than your screen, and correctly zooms content that is narrower.
-   **Configurable Screen Setup:** Tell the addon the exact aspect ratio of your screen for perfect calculations.
-   **Movie & TV Show Aware:** Correctly identifies TV shows and searches for the series title, not the individual episode title.
-   **Robust & Reliable:** Includes intelligent retry logic to handle timing issues during playback start on any system.
-   **Fallback Logic:** If a movie can't be found online, it falls back to sensible defaults (2.39:1 for movies, 16:9 for TV).

### Installation

Installing the addon is a straightforward process.

#### Prerequisite: Enable "Unknown Sources"

For security, Kodi blocks the installation of addons from outside its official repository by default. You must enable this setting first.

1.  From the Kodi home screen, go to **Settings** (the cog icon).
2.  Navigate to **System**.
3.  Select the **Add-ons** tab on the left.
4.  Turn on the toggle for **Unknown sources**.
5.  Read the warning and click **Yes** to accept.

#### Steps

1.  **Download the Latest Release:**
    -   Download the [**ZIP file**](https://github.com/floridoo/kodi-anamorphic-autofit/archive/refs/heads/main.zip).
    -   Transfer it to a file system accessible from Kodi

2.  **Install the Addon in Kodi:**
    -   Open Kodi.
    -   Go to **Settings** (the cog icon) **-> Add-ons**.
    -   Select **Install from zip file**.
    -   Navigate to the location where you downloaded the `.zip` file (e.g., your 'Downloads' folder).
    -   Select `kodi-anamorphic-autofit-main.zip`.
    -   Wait for the "Add-on installed" notification to appear in the top-right corner.

The service is now installed and will run automatically in the background. Remember to visit the **Configuration** section (detailed below) to tailor the addon to your specific screen setup.

## Configuration

After installing, you should configure the addon with your specific screen setup.

1.  Go to **Settings -> Add-ons -> My add-ons -> Services**.
2.  Select **Anamorphic Auto Fit**.
3.  Click on **Configure**.

You will see two settings:

-   **Enable Anamorphic Auto Fit:** A simple switch to turn the service on or off.
-   **Your Screen's Aspect Ratio:** This is the most important setting. Enter the true aspect ratio of your physical screen (e.g., `2.40`, `2.35`). This ensures the zoom calculations are perfectly tailored to your hardware.

## Contributing

Bug reports and feature requests are welcome! Please feel free to open an issue on this GitHub repository.

## License

This project is licensed under the GPL v2.0 or later. See the `addon.xml` file for details.
