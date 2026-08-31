# -*- coding: utf-8 -*-
"""Aspect-ratio lookup and short-lived caching for blu-ray.com."""

import html
import math
import re
import threading
import time
from urllib.parse import urljoin, urlparse

try:
    import requests
    RequestException = requests.exceptions.RequestException
except ImportError:  # pragma: no cover - Kodi installs this declared dependency.
    requests = None

    class RequestException(Exception):
        """Fallback exception used when running pure parser tests without requests."""


CACHE_MISS = object()


def normalize_title(value):
    """Normalize a title for request keys and conservative page matching."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def normalize_year(value):
    """Extract a four-digit year from an InfoLabel value."""
    if value is None:
        return ""
    match = re.search(r"\b(\d{4})\b", str(value))
    return match.group(1) if match else ""


def make_lookup_key(title, year):
    return normalize_title(title), normalize_year(year)


class BlurayAspectRatioProvider:
    """Look up aspect ratios without sharing a requests session across threads."""

    SEARCH_URL = "https://www.blu-ray.com/search/quicksearch.php"
    BASE_URL = "https://www.blu-ray.com/"
    ALLOWED_HOSTS = {"blu-ray.com", "www.blu-ray.com"}
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15"
    )
    REQUEST_TIMEOUT = 10
    SUCCESS_TTL = 7 * 24 * 60 * 60
    FAILURE_TTL = 5 * 60

    def __init__(self, logger=None, session_factory=None, clock=None):
        self.logger = logger
        self.session_factory = session_factory or (requests.Session if requests else None)
        if self.session_factory is None:
            raise RuntimeError("The requests dependency is required for online lookups.")
        self.clock = clock or time.monotonic
        self._cache = {}
        self._cache_lock = threading.Lock()

    def _log(self, message):
        if self.logger is None:
            return
        try:
            self.logger(message)
        except Exception:
            # Logging must never turn a failed lookup into a service failure.
            pass

    def get_cached(self, title, year):
        """Return a cached value, ``None`` for a cached miss, or ``CACHE_MISS``."""
        key = make_lookup_key(title, year)
        if not key[0] or not key[1]:
            return None

        with self._cache_lock:
            cached = self._cache.get(key, CACHE_MISS)
            if cached is CACHE_MISS:
                return CACHE_MISS

            timestamp, value = cached
            ttl = self.SUCCESS_TTL if value is not None else self.FAILURE_TTL
            if self.clock() - timestamp < ttl:
                return value
            del self._cache[key]
            return CACHE_MISS

    def lookup(self, title, year, abort_event=None):
        """Return a scraped aspect ratio, caching both successes and failures."""
        key = make_lookup_key(title, year)
        if not key[0] or not key[1]:
            return None
        if abort_event is not None and abort_event.is_set():
            return None

        cached = self.get_cached(title, year)
        if cached is not CACHE_MISS:
            return cached

        result = self._scrape(key[0], key[1], abort_event=abort_event)
        if abort_event is None or not abort_event.is_set():
            with self._cache_lock:
                self._cache[key] = (self.clock(), result)
        return result

    def _scrape(self, title, year, abort_event=None):
        search_term = f"{title} {year}"
        self._log(f"Attempting online search with term: '{search_term}'")
        session = None
        try:
            session = self.session_factory()
            session.headers.update({"User-Agent": self.USER_AGENT})
            post_data = {
                "section": "bluraymovies",
                "userid": "-1",
                "country": "US",
                "keyword": search_term,
            }
            if self._aborted(abort_event):
                return None

            response = session.post(
                self.SEARCH_URL,
                data=post_data,
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            movie_url = self._extract_movie_url(response.text)
            if movie_url is None:
                self._log(f"Could not parse a safe result URL for '{search_term}'.")
                return None

            self._log(f"Found movie page link from search response: {movie_url}")
            if self._aborted(abort_event):
                return None

            movie_response = session.get(movie_url, timeout=self.REQUEST_TIMEOUT)
            movie_response.raise_for_status()
            final_url = getattr(movie_response, "url", None) or movie_url
            if self._safe_url(final_url) is None:
                self._log(
                    f"Rejected redirected result outside blu-ray.com for '{search_term}'."
                )
                return None

            movie_html = movie_response.text
            page_title = self._extract_page_title(movie_html)
            if page_title and not self._title_matches(title, page_title):
                self._log(
                    f"Rejected a title-mismatched result for '{search_term}': "
                    f"'{page_title}'."
                )
                return None

            aspect_ratio = self._extract_aspect_ratio(movie_html)
            if aspect_ratio is None:
                self._log(f"Could not find an aspect ratio for '{search_term}'.")
                return None

            self._log(f"Successfully scraped aspect ratio: {aspect_ratio}")
            return aspect_ratio
        except RequestException as error:
            self._log(f"A network error occurred for '{search_term}': {error}")
        except Exception as error:
            self._log(f"An unexpected scraping error occurred for '{search_term}': {error}")
        finally:
            if session is not None:
                close = getattr(session, "close", None)
                if close is not None:
                    close()

        return None

    @classmethod
    def _safe_url(cls, value):
        try:
            parsed = urlparse(urljoin(cls.BASE_URL, html.unescape(value)))
        except (TypeError, ValueError):
            return None
        if parsed.scheme not in {"http", "https"}:
            return None
        if (parsed.hostname or "").casefold() not in cls.ALLOWED_HOSTS:
            return None
        return parsed._replace(scheme="https").geturl()

    @classmethod
    def _extract_movie_url(cls, search_response):
        match = re.search(
            r"var\s+urls\s*=\s*new\s+Array\s*\(\s*"
            r"(?P<quote>['\"])(?P<url>.*?)(?P=quote)",
            search_response or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None

        raw_url = html.unescape(match.group("url"))
        raw_url = raw_url.replace("\\/", "/").replace("\\'", "'").replace('\\"', '"')
        return cls._safe_url(raw_url)

    @staticmethod
    def _clean_html(value):
        value = re.sub(
            r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
            " ",
            value or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        value = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", html.unescape(value)).strip()

    @classmethod
    def _extract_page_title(cls, movie_html):
        match = re.search(
            r"<title\b[^>]*>(.*?)</title\s*>",
            movie_html or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        return cls._clean_html(match.group(1)) if match else ""

    @classmethod
    def _title_matches(cls, requested_title, page_title):
        requested = normalize_title(requested_title)
        page = normalize_title(page_title)
        if not requested or not page:
            return True
        return requested in page or page in requested

    @classmethod
    def _extract_aspect_ratio(cls, movie_html):
        text = cls._clean_html(movie_html)
        match = re.search(
            r"\baspect\s+ratio\s*:\s*(\d+(?:\.\d+)?)\s*:\s*1\b",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) and 1.0 <= value <= 4.0 else None

    @staticmethod
    def _aborted(abort_event):
        return abort_event is not None and abort_event.is_set()
