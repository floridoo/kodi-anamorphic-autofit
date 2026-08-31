# -*- coding: utf-8 -*-
"""Pure aspect-ratio calculations used by the Kodi service.

Keeping these calculations independent of Kodi makes the safety checks easy to
test and prevents malformed settings or media metadata from reaching Kodi's
view-mode API.
"""

import math


DEFAULT_TARGET_AR = 2.40
PROJECTOR_AR = 16.0 / 9.0
MIN_TARGET_AR = 1.78
MAX_TARGET_AR = 4.0
CONTAINER_AR_MIN = 1.77
CONTAINER_AR_MAX = 1.79
CONTENT_AR_TOLERANCE = 0.01


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def is_valid_target_ar(value):
    """Return whether *value* is a usable physical screen aspect ratio."""
    number = _finite_positive(value)
    return number is not None and MIN_TARGET_AR <= number <= MAX_TARGET_AR


def parse_target_ar(value, default=DEFAULT_TARGET_AR):
    """Parse a screen aspect ratio, falling back to a safe default."""
    if is_valid_target_ar(value):
        return float(value)
    return float(default)


def aspect_ratio_from_dimensions(width, height):
    """Return width / height, or ``None`` for invalid stream dimensions."""
    width_number = _finite_positive(width)
    height_number = _finite_positive(height)
    if width_number is None or height_number is None:
        return None
    return width_number / height_number


def is_16_9_container(aspect_ratio):
    """Return whether an encoded video is close enough to a 16:9 container."""
    number = _finite_positive(aspect_ratio)
    return number is not None and CONTAINER_AR_MIN < number < CONTAINER_AR_MAX


def calculate_view_mode(video_ar, content_ar, target_ar):
    """Calculate Kodi's custom view-mode values, or return ``None``.

    The zoom is limited to the configured screen ratio. This preserves the
    existing behavior for content wider than the screen while avoiding a
    division-by-zero or non-finite value for bad metadata/settings.
    """
    video_number = _finite_positive(video_ar)
    content_number = _finite_positive(content_ar)
    target_number = _finite_positive(target_ar)

    if (
        video_number is None
        or content_number is None
        or target_number is None
        or not is_valid_target_ar(target_number)
        or not is_16_9_container(video_number)
        or content_number <= video_number + CONTENT_AR_TOLERANCE
    ):
        return None

    effective_ar = min(content_number, target_number)
    if effective_ar <= video_number:
        return None

    zoom = effective_ar / video_number
    pixelratio = PROJECTOR_AR / target_number
    if not math.isfinite(zoom) or not math.isfinite(pixelratio):
        return None

    return {"zoom": zoom, "pixelratio": pixelratio}
