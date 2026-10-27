"""probe_official.py 的離線測試：不連網，用假的 fetcher 與合成的 IIS 列表頁。

執行：python3 -I -m unittest discover -s next/tools-python -p 'test_*.py'
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_official as probe  # noqa: E402

ROOT = 'https://cdn.example.net/WLN/TW/'


def row(date, ampm, clock, size, href, name):
    size_text = '&lt;dir&gt;' if size is None else str(size)
    return f'{date} {ampm} {clock}        {size_text} <A HREF="{href}">{name}</A><br>'


def page(path, rows):
    body = ''.join(rows)
    return (f'<html><head><title>x - {path}</title></head><body><H1>x</H1><hr>\n\n'
            f'<pre><A HREF="/WLN/">[移至上層目錄]</A><br><br>{body}</pre><hr></body></html>'
            ).encode('utf-8')


class FakeFetcher:
    def __init__(self, pages, redirect=None):
        self.pages = pages          # url -> (content_type, body)
        self.redirect = redirect    # 入口 -> 最終網址
        self.domain = 'example.net'
        self.calls = []

    def get(self, url, limit):
        self.calls.append(url)
        final = self.redirect.get(url, url) if self.redirect else url
        if final not in self.pages:
            raise probe.ProbeError('HTTP 404')
        content_type, body = self.pages[final]
        return probe.Response(final, 200, content_type, body[:limit], len(body) > limit)


CONFIG = b'Version=1\r\nDebug=false\r\n'
DAT = b'[\r\n{"ExeVer":"1.1.3","DataVer":"1.3.21"},\r\n]'


def sample_site(config=CONFIG):
    html = 'text/html; charset=UTF-8'
    return {
        ROOT: (html, page('/WLN/TW/', [
            row('2026/10/22', '上午', '08:37', None, '/WLN/TW/1.3.21/', '1.3.21'),
            row('2026/10/15', '下午', '11:19', len(DAT), '/WLN/TW/ResourcePath_PC.dat',
                'ResourcePath_PC.dat'),
            row('2026/10/27', '上午', '01:50', None, '/WLN/TW/Voice/', 'Voice'),
        ])),
        ROOT + '1.3.21/': (html, page('/WLN/TW/1.3.21/', [
            row('2026/10/22', '上午', '08:37', None, '/WLN/TW/1.3.21/ResourcesPC/', 'ResourcesPC'),
            row('2026/10/22', '下午', '12:05', 5000, '/WLN/TW/1.3.21/Big.png', 'Big.png'),
        ])),
        ROOT + '1.3.21/ResourcesPC/': (html, page('/WLN/TW/1.3.21/ResourcesPC/', [
            row('2026/10/22', '上午', '12:10', None, '/WLN/TW/1.3.21/ResourcesPC/AssetBundle/',
                'AssetBundle'),
            row('2026/10/22', '上午', '08:37', len(config), '/WLN/TW/1.3.21/ResourcesPC/Config.txt',
                'Config.txt'),
        ])),
        ROOT + 'ResourcePath_PC.dat': ('*/*', DAT),
        ROOT + '1.3.21/ResourcesPC/Config.txt': ('text/plain', config),
    }


class ListingTests(unittest.TestCase):
    def test_parses_dirs_files_and_12_hour_clock(self):
        rows = probe.parse_listing(sample_site()[ROOT][1], ROOT)
        self.assertEqual([r['name'] for r in rows], ['1.3.21', 'ResourcePath_PC.dat', 'Voice'])
        self.assertTrue(rows[0]['is_dir'])
        self.assertIsNone(rows[0]['listed_size'])
        self.assertEqual(rows[1]['listed_size'], len(DAT))
        self.assertEqual(rows[1]['listed_time'], '2026-10-15T23:19')   # 下午 11:19
        self.assertEqual(rows[0]['listed_time'], '2026-10-22T08:37')

    def test_noon_and_midnight(self):
        self.assertEqual(probe.listed_time('2026/1/2', '下午', '12:05'), '2026-01-02T12:05')
        self.assertEqual(probe.listed_time('2026/1/2', '上午', '12:10'), '2026-01-02T00:10')

    def test_unrecognized_page_is_rejected(self):
        with self.assertRaises(probe.ProbeError):
            probe.parse_listing(b'<html><body>hello</body></html>', ROOT)

    def test_unparsed_anchor_rows_are_rejected(self):
        broken = page('/WLN/TW/', ['xx <A HREF="/WLN/TW/a">a</A><br>',
                                   'yy <A HREF="/WLN/TW/b">b</A><br>'])
        with self.assertRaises(probe.ProbeError):
            probe.parse_listing(broken, ROOT)


class UrlPolicyTests(unittest.TestCase):
    def test_domain_is_derived_not_hard_coded(self):
        self.assertEqual(probe.registrable_domain('a.b.example.net'), 'example.net')

    def test_rejects_unsafe_urls(self):
        for url in ('http://cdn.example.net/x', 'https://evil.net/x',
                    'https://cdn.example.net:8443/x', 'https://u:p@cdn.example.net/x',
                    'https://cdn.example.net/x?a=1', 'https://cdn.example.net/x#f',
                    'https://example.net.evil.net/x'):
            with self.subTest(url=url), self.assertRaises(probe.ProbeError):
                probe.check_url(url, 'example.net')
        probe.check_url('https://src.example.net/WLN/TW/', 'example.net')

    def test_child_path_rejects_escape(self):
        self.assertEqual(probe.child_path(ROOT, ROOT + '1.3.21/Config.txt'), '1.3.21/Config.txt')
        for url in ('https://cdn.example.net/WLN/Other/x', ROOT + '%2e%2e/x', ROOT):
            with self.subTest(url=url), self.assertRaises(probe.ProbeError):
                probe.child_path(ROOT, url)


class ThrottleTests(unittest.TestCase):
    def test_at_most_two_requests_per_second(self):
        now = [0.0]
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds
        throttle = probe.Throttle(0.5, clock=lambda: now[0], sleep=sleep)
        for _ in range(5):
            throttle.wait()
        self.assertEqual(slept, [0.5, 0.5, 0.5, 0.5])
        self.assertEqual(now[0], 2.0)


class ScanTests(unittest.TestCase):
    def scan(self, site, **kwargs):
        fetcher = FakeFetcher(site, **{k: kwargs.pop(k) for k in ('redirect',) if k in kwargs})
        stored = {}
        manifest = probe.scan(ROOT, fetcher, store=lambda p, b: stored.__setitem__(p, b),
                              hash_max_bytes=1024, **kwargs)
        return manifest, stored, fetcher

    def test_records_size_and_sha256_and_skips(self):
        manifest, stored, fetcher = self.scan(sample_site())
        entries = {e['path']: e for e in manifest['entries']}
        dat = entries['ResourcePath_PC.dat']
        self.assertEqual(dat['status'], 'hashed')
        self.assertEqual(dat['size'], len(DAT))
        self.assertEqual(dat['sha256'], hashlib.sha256(DAT).hexdigest())
        self.assertEqual(entries['1.3.21/Big.png']['status'], 'not_downloaded_size')
        self.assertIsNone(entries['1.3.21/Big.png']['sha256'])
        self.assertEqual(entries['Voice']['status'], 'not_listed_skipped')
        self.assertEqual(entries['1.3.21/ResourcesPC/AssetBundle']['status'], 'not_listed_skipped')
        self.assertEqual(set(stored), {'ResourcePath_PC.dat', '1.3.21/ResourcesPC/Config.txt'})
        self.assertNotIn(ROOT + 'Voice/', fetcher.calls)
        self.assertEqual(manifest['problems'], [])

    def test_follows_redirect_and_uses_final_root(self):
        final = 'https://src.example.net/WLN/TW/'
        site = {k.replace(ROOT, final): v for k, v in sample_site().items()}
        site = {k: (t, b.replace(b'cdn.example.net', b'src.example.net')) for k, (t, b) in site.items()}
        manifest, _, _ = self.scan(site, redirect={ROOT: final})
        self.assertEqual(manifest['resolved_root'], final)
        self.assertEqual(manifest['entry_url'], ROOT)
        self.assertIn('ResourcePath_PC.dat', {e['path'] for e in manifest['entries']})

    def test_size_mismatch_is_not_hashed(self):
        site = sample_site()
        site[ROOT + 'ResourcePath_PC.dat'] = ('*/*', DAT + b'x')
        manifest, stored, _ = self.scan(site)
        dat = {e['path']: e for e in manifest['entries']}['ResourcePath_PC.dat']
        self.assertEqual(dat['status'], 'error')
        self.assertIsNone(dat['sha256'])
        self.assertNotIn('ResourcePath_PC.dat', stored)
        self.assertTrue(manifest['problems'])

    def test_depth_and_request_limits(self):
        manifest, _, _ = self.scan(sample_site(), max_depth=1)
        statuses = {e['path']: e['status'] for e in manifest['entries']}
        self.assertEqual(statuses['1.3.21/ResourcesPC'], 'not_listed_depth')
        manifest, _, fetcher = self.scan(sample_site(), max_requests=2)
        self.assertLessEqual(len(fetcher.calls), 2)

    def test_request_limit_marks_dir_once(self):
        manifest, _, _ = self.scan(sample_site(), max_requests=2)
        paths = [e['path'] for e in manifest['entries']]
        self.assertEqual(len(paths), len(set(paths)))
        statuses = {e['path']: e['status'] for e in manifest['entries']}
        self.assertEqual(statuses['1.3.21/ResourcesPC'], 'not_listed_request_limit')

    def test_lists_all_dirs_before_downloading_smallest_first(self):
        _, _, fetcher = self.scan(sample_site())
        listings = [c for c in fetcher.calls if c.endswith('/')]
        files = [c for c in fetcher.calls if not c.endswith('/')]
        self.assertEqual(fetcher.calls, listings + files)
        self.assertEqual(files, [ROOT + '1.3.21/ResourcesPC/Config.txt', ROOT + 'ResourcePath_PC.dat'])

    def test_images_skipped_by_default_but_listed(self):
        site = sample_site()
        site[ROOT + '1.3.21/'] = ('text/html', page('/WLN/TW/1.3.21/', [
            row('2026/10/22', '上午', '08:37', 10, '/WLN/TW/1.3.21/AnPic001.png', 'AnPic001.png')]))
        manifest, _, fetcher = self.scan(site)
        pic = {e['path']: e for e in manifest['entries']}['1.3.21/AnPic001.png']
        self.assertEqual((pic['status'], pic['listed_size']), ('not_downloaded_skipped', 10))
        self.assertNotIn(ROOT + '1.3.21/AnPic001.png', fetcher.calls)

    def test_include_dir_overrides_skip(self):
        site = sample_site()
        site[ROOT + 'Voice/'] = ('text/html', page('/WLN/TW/Voice/', []))
        manifest, _, fetcher = self.scan(site, include_dirs=('Voice',))
        self.assertIn(ROOT + 'Voice/', fetcher.calls)

    def test_non_listing_entry_is_rejected(self):
        site = sample_site()
        site[ROOT] = ('text/plain', b'hello')
        with self.assertRaises(probe.ProbeError):
            self.scan(site)


class DiffTests(unittest.TestCase):
    def test_added_removed_changed_unverified(self):
        old, _, _ = ScanTests.scan(self, sample_site())
        new, _, _ = ScanTests.scan(self, sample_site(config=b'Version=2\r\nDebug=false\r\n'))
        new['entries'] = [e for e in new['entries'] if e['path'] != 'ResourcePath_PC.dat']
        new['entries'].append({'path': 'New.txt', 'kind': 'file', 'listed_size': 3,
                               'sha256': None, 'status': 'not_downloaded_size'})
        result = probe.diff_manifests(old, new)
        self.assertEqual(result['added'], ['New.txt'])
        self.assertEqual(result['removed'], ['ResourcePath_PC.dat'])
        self.assertEqual([c['path'] for c in result['changed']], ['1.3.21/ResourcesPC/Config.txt'])
        self.assertEqual(result['changed'][0]['reason'], 'sha256')
        self.assertEqual(result['size_same_unverified'], ['1.3.21/Big.png'])

    def test_schema_mismatch_is_rejected(self):
        with self.assertRaises(probe.ProbeError):
            probe.diff_manifests({'schema': 99, 'entries': []}, {'schema': 1, 'entries': []})


class DescribeTests(unittest.TestCase):
    def test_never_outputs_values(self):
        secret = b'10.1.2.3,7001,\xe4\xbc\xba\xe6\x9c\x8d\xe5\x99\xa8\xe4\xb8\x80\r\ngame.example.net,7002,abc\r\n'
        info = probe.describe_bytes(secret, 'ServerList.txt')
        text = json.dumps(info, ensure_ascii=False)
        for value in ('10.1.2.3', '7001', 'game.example.net', '伺服器一', 'abc'):
            self.assertNotIn(value, text)
        patterns = [p['pattern'] for p in info['line_patterns']]
        self.assertIn("',' :: ipv4 | int | text-cjk(4)", patterns)
        self.assertIn("',' :: hostname | int | text(3)", patterns)
        self.assertEqual(info['line_ending'], 'CRLF')

    def test_key_value_keeps_key_names_only(self):
        info = probe.describe_bytes(CONFIG, 'Config.txt')
        patterns = [p['pattern'] for p in info['line_patterns']]
        self.assertEqual(patterns, ['key=value :: Version=int', 'key=value :: Debug=bool'])

    def test_json_with_trailing_comma(self):
        info = probe.describe_bytes(DAT, 'ResourcePath_PC.dat')
        self.assertEqual(info['kind'], 'json-trailing-comma')
        self.assertEqual(info['json_shape'], {'list_length': 1, 'item_shapes': [
            {'ExeVer': 'str:dotted-version', 'DataVer': 'str:dotted-version'}]})

    def test_json_number_and_digit_string_are_distinct(self):
        info = probe.describe_bytes(b'[{"a":1,"b":"2","c":true,"d":null}]')
        self.assertEqual(info['json_shape']['item_shapes'],
                         [{'a': 'number:int', 'b': 'str:int', 'c': 'bool', 'd': 'null'}])

    def test_hash_columns(self):
        line = ('Lua/a.lua|' + 'a' * 32 + '|120\n').encode()
        info = probe.describe_bytes(line)
        self.assertEqual(info['line_patterns'][0]['pattern'], "'|' :: path | hex32 | int")


class CacheTests(unittest.TestCase):
    def test_store_rejects_escape_and_saves_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            store = probe.file_store(cache)
            store('a/b.txt', b'x')
            self.assertEqual((cache / 'files/a/b.txt').read_bytes(), b'x')
            with self.assertRaises(probe.ProbeError):
                store('../escape.txt', b'x')
            manifest = {'schema': 1, 'generated_at': '2026-10-27T01:02:03Z', 'entries': []}
            saved = probe.save_manifest(cache, manifest)
            self.assertEqual(saved.name, 'manifest-20261027T010203Z.json')
            self.assertEqual(probe.load_json(cache / 'manifests/latest.json'), manifest)


if __name__ == '__main__':
    unittest.main()
