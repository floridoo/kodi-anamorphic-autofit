# Anamorphic Auto Fit for Kodi

Anamorphic Auto Fit is a Kodi service for a 16:9 projector with an anamorphic lens and a widescreen display such as a 2.40:1 screen. It removes the extra letterbox bars that can appear when a widescreen title is stored inside a 16:9 video container.

## How it works

When video starts, the service:

1. Reads the current title, year, and active video stream from Kodi.
2. Continues only for video containers close to 16:9.
3. Looks up the title's original aspect ratio on [blu-ray.com](https://www.blu-ray.com).
4. Calculates a zoom that is capped at the configured screen aspect ratio.
5. Applies Kodi's custom zoom and pixel ratio on Kodi's service thread.

Lookups run asynchronously, are cached for repeated playback, and are discarded if the player has already moved to another item. If the title, year, stream information, or online lookup is unavailable, the service leaves the current view unchanged.

## Features

- Fully automatic background service.
- Supports movies and TV episodes when Kodi exposes suitable title/year metadata. TV episodes are searched using the series title.
- Uses the currently active video stream when multiple streams are present.
- Validates settings, stream dimensions, scraped URLs, scraped titles, and aspect-ratio values before using them.
- Restores an auto-applied view mode when playback changes, but preserves a view mode changed manually afterwards.
- Does not use a fallback aspect ratio when an online result is unavailable, avoiding unexpected cropping.

## Installation

Kodi requires `addon.xml` to be inside a folder named `service.anamorphic.autofit` at the root of the install ZIP. The GitHub repository archive is a source tree and is not itself an installable add-on ZIP.

To create an installable ZIP from a checkout, run:

```sh
zip -r service.anamorphic.autofit-1.1.0.zip service.anamorphic.autofit
```

Then in Kodi:

1. Enable **Settings -> System -> Add-ons -> Unknown sources** if necessary.
2. Open **Settings -> Add-ons -> Install from zip file**.
3. Select `service.anamorphic.autofit-1.1.0.zip`.

The service starts automatically after installation.

## Configuration

Open **Settings -> Add-ons -> My add-ons -> Services -> Anamorphic Auto Fit -> Configure**.

- **Enable Anamorphic Auto Fit** turns the service on or off.
- **Your Screen's Aspect Ratio** accepts values from `1.78` through `4.00`; `2.40` is used if the setting is invalid.

## Privacy and network behavior

For uncached lookups, the configured title and year are sent to blu-ray.com. The service does not send playback files or Kodi credentials. Network failures are logged and leave the current view mode unchanged; negative results are cached briefly to avoid repeatedly retrying an unavailable result during playback.

## Contributing

Bug reports and feature requests are welcome. Please open an issue in this GitHub repository.

## License

This project is licensed under the GPL v2.0 or later. See `service.anamorphic.autofit/addon.xml` for details.
