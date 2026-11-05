import unittest
from wlre.services.official_source import selected_host


class OfficialSourceTests(unittest.TestCase):
    def test_only_observed_official_origins_are_selectable(self):
        for host in ('wlreftp.chinesegamer.net', 'wlreftpsrc.chinesegamer.net'):
            self.assertEqual(selected_host({'WLRE_OFFICIAL_RESOURCE_HOST': host}), host)

    def test_default_preserves_existing_installation(self):
        self.assertEqual(selected_host({}), 'wlreftp.chinesegamer.net')

    def test_arbitrary_or_credentialed_hosts_are_rejected(self):
        for host in ('', 'evil.example', 'https://wlreftpsrc.chinesegamer.net',
                     'user@wlreftpsrc.chinesegamer.net', 'wlreftpsrc.chinesegamer.net:443',
                     'wlreftpsrc.chinesegamer.net/path'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                selected_host({'WLRE_OFFICIAL_RESOURCE_HOST': host})

    def test_metadata_accepts_official_generic_mime_with_same_body_validation(self):
        import io
        from wlre.services.official_version import fetch_bytes, RESOURCE_MAP_URL
        class Response(io.BytesIO):
            status = 200
            def geturl(self):
                return RESOURCE_MAP_URL
        def opener(request, timeout):
            self.assertEqual(request.get_header('Accept'), '*/*')
            return Response(b'[]')
        self.assertEqual(fetch_bytes(RESOURCE_MAP_URL, opener=opener, cache_bust=False), b'[]')
