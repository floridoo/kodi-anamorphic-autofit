import os
import sys
import unittest


ADDON_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "service.anamorphic.autofit")
)
if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)

from aspect_provider import CACHE_MISS, BlurayAspectRatioProvider  # noqa: E402


class FakeResponse:
    def __init__(self, text, url=None):
        self.text = text
        self.url = url

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, search_text, movie_text, movie_url="https://www.blu-ray.com/movies/example"):
        self.headers = {}
        self.search_text = search_text
        self.movie_text = movie_text
        self.movie_url = movie_url
        self.post_count = 0
        self.get_count = 0
        self.closed = False

    def post(self, url, data, timeout):
        self.post_count += 1
        return FakeResponse(self.search_text, url=url)

    def get(self, url, timeout):
        self.get_count += 1
        return FakeResponse(self.movie_text, url=self.movie_url)

    def close(self):
        self.closed = True


class FakeClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


class AspectProviderTests(unittest.TestCase):
    def provider_for(self, movie_text):
        search_text = "var urls = new Array('/movies/example')"
        sessions = []

        def factory():
            session = FakeSession(search_text, movie_text)
            sessions.append(session)
            return session

        clock = FakeClock()
        provider = BlurayAspectRatioProvider(session_factory=factory, clock=clock)
        return provider, clock, sessions

    def test_scrapes_html_with_variable_precision_and_caches_success(self):
        provider, clock, sessions = self.provider_for(
            """
            <html><head><title>Example (2020) - Blu-ray.com</title></head>
            <body><script>Aspect ratio: 9.99:1</script>
            <div>Aspect ratio: <strong>2.390</strong>:1</div></body></html>
            """
        )

        self.assertEqual(provider.lookup("  Example ", "2020-01-01"), 2.39)
        self.assertEqual(provider.lookup("example", "2020"), 2.39)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].closed)
        self.assertIsNot(provider.get_cached("example", "2020"), CACHE_MISS)
        self.assertEqual(clock.value, 0)

    def test_caches_negative_result_briefly(self):
        provider, clock, sessions = self.provider_for(
            "<title>Example (2020)</title><div>No aspect data</div>"
        )

        self.assertIsNone(provider.lookup("Example", "2020"))
        self.assertIsNone(provider.lookup("Example", "2020"))
        self.assertEqual(len(sessions), 1)

        clock.value = provider.FAILURE_TTL + 1
        self.assertIsNone(provider.lookup("Example", "2020"))
        self.assertEqual(len(sessions), 2)

    def test_rejects_external_result_urls(self):
        self.assertIsNone(
            BlurayAspectRatioProvider._extract_movie_url(
                "var urls = new Array('https://example.invalid/movie')"
            )
        )

    def test_rejects_clear_title_mismatch(self):
        provider, _clock, sessions = self.provider_for(
            "<title>Different Movie (2020)</title><div>Aspect ratio: 2.39:1</div>"
        )
        self.assertIsNone(provider.lookup("Example", "2020"))
        self.assertEqual(len(sessions), 1)


if __name__ == "__main__":
    unittest.main()
