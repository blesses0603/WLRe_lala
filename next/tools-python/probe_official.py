"""官方資源探測工具（階段 0-6）。

只做 GET 與目錄列表，限速每秒最多 2 個請求。列出官方 CDN 的目錄樹，
記錄每個檔案的列表大小、下載大小與 SHA-256，輸出 manifest.json，
並和上一版 manifest 做差異比對。

用法（在 repo 根目錄或任何地方皆可）：

    python3 -I next/tools-python/probe_official.py scan  --base-url <入口網址>
    python3 -I next/tools-python/probe_official.py diff  <舊 manifest> <新 manifest>
    python3 -I next/tools-python/probe_official.py describe <本機檔案>...

入口網址見 next/PLAN.md 第 5 節，**不寫死在程式裡**；也可用環境變數
LALA_OFFICIAL_BASE_URL 提供。轉址會跟隨，但只接受 https 且與入口同一個
上層網域（由入口網址推得，不寫死）。

下載內容與 manifest 只寫到本機快取（預設 ~/.lala-cache/official/），
不得放進 repo。describe 只輸出「欄位格式」，不輸出任何實際值。
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MANIFEST_SCHEMA = 1
USER_AGENT = 'LaLa-next-probe/0.1'
DEFAULT_CACHE = Path.home() / '.lala-cache' / 'official'
MIN_INTERVAL = 0.5            # 秒；每秒最多 2 個請求
LISTING_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_HASH_MAX_BYTES = 1024 * 1024
DEFAULT_MAX_REQUESTS = 400
DEFAULT_MAX_DEPTH = 3
# 預設不展開的資料夾：體積大、檔案多。需要時用 --include-dir 打開。
DEFAULT_SKIP_DIRS = ('AssetBundle', 'Voice', 'Lua')
# 預設不下載的檔案（仍記錄列表大小與時間）：公告圖片數量多、與資源同步無關。
DEFAULT_SKIP_FILES = ('*.png', '*.jpg')


class ProbeError(Exception):
    """探測失敗；一律拒絕，不猜測。"""


# ---------------------------------------------------------------- 網路層

class Throttle:
    """兩次請求之間至少間隔 min_interval 秒。"""

    def __init__(self, min_interval=MIN_INTERVAL, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self.last = None

    def wait(self):
        now = self.clock()
        if self.last is not None:
            remaining = self.min_interval - (now - self.last)
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self.last = now


def registrable_domain(host):
    """取主機名稱最後兩段，例如 a.b.example.net -> example.net。"""
    labels = (host or '').lower().rstrip('.').split('.')
    if len(labels) < 2 or not all(labels):
        raise ProbeError('入口網址的主機名稱無效')
    return '.'.join(labels[-2:])


def check_url(url, domain):
    """只允許 https、同一上層網域、沒有帳密／埠號／query／fragment。"""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ProbeError('網址格式無效') from exc
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https':
        raise ProbeError('只接受 https')
    if not (host == domain or host.endswith('.' + domain)):
        raise ProbeError('轉址或連結指向其他網域')
    if port is not None or parts.username or parts.password:
        raise ProbeError('網址不得含埠號或帳密')
    if parts.query or parts.fragment:
        raise ProbeError('網址不得含 query 或 fragment')
    return url


@dataclass
class Response:
    url: str            # 跟隨轉址之後的最終網址
    status: int
    content_type: str
    body: bytes
    truncated: bool     # 內容超過上限，只讀到上限


class _CheckedRedirect(HTTPRedirectHandler):
    def __init__(self, domain):
        super().__init__()
        self.domain = domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.domain)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpFetcher:
    """真正連線的 GET 實作；測試時以假的 fetcher 取代。"""

    def __init__(self, domain, throttle=None, timeout=20):
        self.domain = domain
        self.throttle = throttle or Throttle()
        self.timeout = timeout
        self.opener = build_opener(_CheckedRedirect(domain))
        self.requests = 0

    def get(self, url, limit):
        check_url(url, self.domain)
        self.throttle.wait()
        self.requests += 1
        request = Request(url, headers={'User-Agent': USER_AGENT}, method='GET')
        try:
            with self.opener.open(request, timeout=self.timeout) as stream:
                body = stream.read(limit + 1)
                final = stream.geturl()
                check_url(final, self.domain)
                return Response(final, getattr(stream, 'status', 200),
                                stream.headers.get('Content-Type', ''),
                                body[:limit], len(body) > limit)
        except HTTPError as exc:
            raise ProbeError(f'HTTP {exc.code}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProbeError(f'連線失敗：{type(exc).__name__}') from exc


# ---------------------------------------------------------------- 目錄列表

# IIS 目錄瀏覽的一列：日期 [上午/下午/AM/PM] 時間 大小或<dir> <A HREF="...">名稱</A>
_ROW = re.compile(
    r'(?P<date>\d{4}/\d{1,2}/\d{1,2})\s+(?:(?P<ampm>上午|下午|AM|PM)\s+)?'
    r'(?P<time>\d{1,2}:\d{2})(?:\s*(?P<ampm2>AM|PM))?\s+'
    r'(?P<size>&lt;dir&gt;|<dir>|\d+)\s+<A HREF="(?P<href>[^"]+)">(?P<name>[^<]*)</A>',
    re.IGNORECASE)


def listed_time(date, ampm, clock):
    """把列表的本地時間轉成 YYYY-MM-DDTHH:MM（伺服器當地時間，不含時區）。"""
    year, month, day = (int(x) for x in date.split('/'))
    hour, minute = (int(x) for x in clock.split(':'))
    if ampm in ('下午', 'PM', 'pm') and hour != 12:
        hour += 12
    elif ampm in ('上午', 'AM', 'am') and hour == 12:
        hour = 0
    return datetime(year, month, day, hour, minute).strftime('%Y-%m-%dT%H:%M')


def parse_listing(page, page_url):
    """解析 IIS 目錄頁。回傳 [{name, url, is_dir, listed_size, listed_time}]。

    認不出任何一列、或有 <A> 連結卻對不上列格式時拒絕，不猜測。
    """
    text = page.decode('utf-8', errors='strict') if isinstance(page, bytes) else page
    if '<pre>' not in text.lower():
        raise ProbeError('不是可辨識的目錄列表頁')
    rows = []
    for match in _ROW.finditer(text):
        is_dir = match['size'].lower() in ('&lt;dir&gt;', '<dir>')
        href = html.unescape(match['href'])
        url = urljoin(page_url, href)
        name = html.unescape(match['name'])
        rows.append({
            'name': name, 'url': url, 'is_dir': is_dir,
            'listed_size': None if is_dir else int(match['size']),
            'listed_time': listed_time(match['date'], match['ampm'] or match['ampm2'], match['time']),
        })
    # 「移至上層目錄」那一個連結沒有日期與大小，其餘每個連結都必須被解析到。
    anchors = len(re.findall(r'<A HREF=', text, re.IGNORECASE))
    if anchors - len(rows) > 1:
        raise ProbeError('目錄列表有無法辨識的列')
    return rows


def child_path(root_url, url):
    """root 之下的相對路徑（posix）。不在 root 之下或含 . / .. 時拒絕。"""
    root_path = urlsplit(root_url).path
    path = urlsplit(url).path
    if not root_path.endswith('/'):
        root_path += '/'
    if not path.startswith(root_path):
        raise ProbeError('連結不在入口目錄之下')
    relative = unquote(path[len(root_path):])
    parts = [p for p in relative.split('/') if p]
    if not parts or any(p in ('.', '..') or '\\' in p for p in parts):
        raise ProbeError('連結路徑不合法')
    return '/'.join(parts)


# ---------------------------------------------------------------- 掃描

def _matches(relative, patterns):
    pure = PurePosixPath(relative)
    return any(pure.match(p) or pure.name == p for p in patterns)


def scan(base_url, fetcher, *, max_depth=DEFAULT_MAX_DEPTH, hash_max_bytes=DEFAULT_HASH_MAX_BYTES,
         max_requests=DEFAULT_MAX_REQUESTS, skip_dirs=DEFAULT_SKIP_DIRS, include_dirs=(),
         skip_files=DEFAULT_SKIP_FILES, store=None, now=None):
    """掃描目錄樹，回傳 manifest dict。store(relative, body) 用來把檔案寫入快取。"""
    entry = fetcher.get(base_url, LISTING_MAX_BYTES)
    if entry.truncated or 'html' not in entry.content_type.lower():
        raise ProbeError('入口不是目錄列表頁')
    root_url = entry.url if entry.url.endswith('/') else entry.url + '/'
    entries, problems, downloads = [], [], []
    # 第一階段只列目錄（請求少），第二階段才下載檔案，避免大量圖片先用光請求額度。
    queue = [(root_url, '', 0, entry, None)]
    requests = 1
    while queue:
        dir_url, dir_rel, depth, page, dir_record = queue.pop(0)
        if page is None:
            if requests >= max_requests:
                problems.append({'path': dir_rel, 'problem': 'request_limit'})
                dir_record['status'] = 'not_listed_request_limit'
                continue
            try:
                page = fetcher.get(dir_url, LISTING_MAX_BYTES)
                requests += 1
                if page.truncated or 'html' not in page.content_type.lower():
                    raise ProbeError('不是目錄列表頁')
            except ProbeError as exc:
                requests += 1
                problems.append({'path': dir_rel, 'problem': str(exc)})
                dir_record['status'] = 'error'
                continue
        try:
            rows = parse_listing(page.body, page.url)
        except (ProbeError, UnicodeError) as exc:
            problems.append({'path': dir_rel, 'problem': f'列表解析失敗：{exc}'})
            continue
        for row in rows:
            try:
                relative = child_path(root_url, row['url'])
                check_url(row['url'], fetcher.domain)
            except ProbeError as exc:
                problems.append({'path': dir_rel + '/' + row['name'], 'problem': str(exc)})
                continue
            if row['is_dir']:
                record = {'path': relative, 'kind': 'dir', 'listed_time': row['listed_time']}
                if depth + 1 > max_depth:
                    record['status'] = 'not_listed_depth'
                elif _matches(relative, skip_dirs) and not _matches(relative, include_dirs):
                    record['status'] = 'not_listed_skipped'
                else:
                    record['status'] = 'listed'
                    queue.append((row['url'], relative, depth + 1, None, record))
                entries.append(record)
                continue
            record = {'path': relative, 'kind': 'file', 'listed_size': row['listed_size'],
                      'listed_time': row['listed_time'], 'size': None, 'sha256': None}
            if row['listed_size'] > hash_max_bytes:
                record['status'] = 'not_downloaded_size'
            elif _matches(relative, skip_files):
                record['status'] = 'not_downloaded_skipped'
            else:
                downloads.append((row['url'], record))
            entries.append(record)
    # 小檔優先：設定檔、清單通常最小也最重要。
    downloads.sort(key=lambda item: (item[1]['listed_size'], item[1]['path']))
    for url, record in downloads:
        if requests >= max_requests:
            record['status'] = 'not_downloaded_request_limit'
            continue
        try:
            response = fetcher.get(url, hash_max_bytes)
            requests += 1
            if response.truncated:
                raise ProbeError('檔案超過下載上限')
            if len(response.body) != record['listed_size']:
                # 大小對不上：不記雜湊，避免把不完整內容當成正確版本。
                raise ProbeError('下載大小與列表大小不符')
            record['size'] = len(response.body)
            record['sha256'] = hashlib.sha256(response.body).hexdigest()
            record['status'] = 'hashed'
            if store is not None:
                store(record['path'], response.body)
        except ProbeError as exc:
            requests += 1
            record['status'] = 'error'
            problems.append({'path': record['path'], 'problem': str(exc)})
    entries.sort(key=lambda item: item['path'])
    return {
        'schema': MANIFEST_SCHEMA,
        'generated_at': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'entry_url': base_url,
        'resolved_root': root_url,
        'settings': {'max_depth': max_depth, 'hash_max_bytes': hash_max_bytes,
                     'max_requests': max_requests, 'skip_dirs': list(skip_dirs),
                     'include_dirs': list(include_dirs), 'skip_files': list(skip_files)},
        'requests': requests,
        'entries': entries,
        'problems': problems,
    }


# ---------------------------------------------------------------- 差異比對

def diff_manifests(old, new):
    """以 path 為鍵比對。只有兩邊都有 sha256 才比內容，否則只比列表大小。"""
    for manifest in (old, new):
        if manifest.get('schema') != MANIFEST_SCHEMA:
            raise ProbeError('manifest schema 不符')
    before = {e['path']: e for e in old['entries'] if e['kind'] == 'file'}
    after = {e['path']: e for e in new['entries'] if e['kind'] == 'file'}
    changed, unverified, same = [], [], 0
    for path in sorted(before.keys() & after.keys()):
        a, b = before[path], after[path]
        if a.get('sha256') and b.get('sha256'):
            if a['sha256'] != b['sha256']:
                changed.append({'path': path, 'reason': 'sha256',
                                'old_size': a.get('listed_size'), 'new_size': b.get('listed_size')})
            else:
                same += 1
        elif a.get('listed_size') != b.get('listed_size'):
            changed.append({'path': path, 'reason': 'listed_size',
                            'old_size': a.get('listed_size'), 'new_size': b.get('listed_size')})
        else:
            # 沒有雜湊、大小相同：不能斷言內容沒變。
            unverified.append(path)
    dirs_before = {e['path'] for e in old['entries'] if e['kind'] == 'dir'}
    dirs_after = {e['path'] for e in new['entries'] if e['kind'] == 'dir'}
    return {
        'old_generated_at': old.get('generated_at'), 'new_generated_at': new.get('generated_at'),
        'added': sorted(after.keys() - before.keys()),
        'removed': sorted(before.keys() - after.keys()),
        'changed': changed,
        'unchanged': same,
        'size_same_unverified': unverified,
        'dirs_added': sorted(dirs_after - dirs_before),
        'dirs_removed': sorted(dirs_before - dirs_after),
    }


# ---------------------------------------------------------------- 格式描述（不輸出值）

_HEX = re.compile(r'[0-9a-fA-F]+')


def token_class(token):
    """把一個欄位值歸類成型別名稱；永遠不回傳值本身。"""
    t = token.strip()
    if t == '':
        return 'empty'
    if re.fullmatch(r'[+-]?\d+', t):
        return 'int'
    if re.fullmatch(r'[+-]?\d+\.\d+', t):
        return 'decimal'
    if re.fullmatch(r'\d+(\.\d+){2,3}', t):
        parts = t.split('.')
        return 'ipv4' if len(parts) == 4 and all(int(p) < 256 for p in parts) else 'dotted-version'
    if re.fullmatch(r'(true|false)', t, re.IGNORECASE):
        return 'bool'
    if re.fullmatch(r'[a-z][a-z0-9+.-]*://\S+', t, re.IGNORECASE):
        return 'url'
    if _HEX.fullmatch(t) and len(t) in (8, 32, 40, 64):
        return f'hex{len(t)}'
    if re.fullmatch(r'[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+', t) and re.search(r'[A-Za-z]', t):
        return 'hostname'
    if '/' in t and ' ' not in t:
        return 'path'
    if re.search(r'[一-鿿]', t):
        return f'text-cjk({len(t)})'
    return f'text({len(t)})'


def _decode_text(raw):
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8-bom'
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16-bom'
    return raw.decode('utf-8'), 'utf-8'


def _line_shape(line):
    """回傳 (分隔符號, [欄位型別…])。key=value 形式保留 key 名稱（key 不是值）。"""
    stripped = line.strip()
    key_value = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(.*)', stripped)
    if key_value and not re.match(r'[a-z]+://', stripped, re.IGNORECASE):
        return 'key=value', [key_value[1] + '=' + token_class(key_value[2])]
    for delimiter in ('\t', '|', ',', ';'):
        if delimiter in stripped:
            return repr(delimiter), [token_class(x) for x in stripped.split(delimiter)]
    if ' ' in stripped and not re.search(r'[一-鿿]', stripped):
        return "' '", [token_class(x) for x in stripped.split()]
    return 'none', [token_class(stripped)]


def describe_bytes(raw, name=''):
    """回傳檔案的結構描述（編碼、換行、各列欄位型別與次數），不含任何實際值。"""
    info = {'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    if raw.startswith(b'\x1f\x8b'):
        info['kind'] = 'gzip'
        return info
    try:
        text, encoding = _decode_text(raw)
    except UnicodeError:
        counts = [raw.count(bytes([b])) for b in range(256)]
        entropy = -sum(c / len(raw) * math.log2(c / len(raw)) for c in counts if c) if raw else 0
        info.update({'kind': 'binary', 'entropy_bits_per_byte': round(entropy, 2)})
        return info
    info['encoding'] = encoding
    info['line_ending'] = 'CRLF' if '\r\n' in text else 'LF' if '\n' in text else 'none'
    info['ends_with_newline'] = text.endswith('\n')
    stripped = text.strip()
    if stripped[:1] in '[{':
        relaxed = re.sub(r',(\s*[\]}])', r'\1', stripped)
        try:
            data = json.loads(stripped)
            info['kind'] = 'json'
        except ValueError:
            try:
                data = json.loads(relaxed)
                info['kind'] = 'json-trailing-comma'
            except ValueError:
                data = None
        if data is not None:
            info['json_shape'] = _json_shape(data)
            return info
    lines = text.splitlines()
    info['kind'] = 'text'
    info['line_count'] = len(lines)
    info['blank_lines'] = sum(1 for line in lines if not line.strip())
    patterns = {}
    for line in lines:
        if not line.strip():
            continue
        delimiter, fields = _line_shape(line)
        key = delimiter + ' :: ' + ' | '.join(fields)
        patterns[key] = patterns.get(key, 0) + 1
    info['line_patterns'] = [{'pattern': k, 'count': v}
                             for k, v in sorted(patterns.items(), key=lambda kv: -kv[1])]
    return info


def _json_shape(value):
    if isinstance(value, dict):
        return {k: _json_shape(v) for k, v in value.items()}
    if isinstance(value, list):
        shapes = []
        for item in value:
            shape = _json_shape(item)
            if shape not in shapes:
                shapes.append(shape)
        return {'list_length': len(value), 'item_shapes': shapes}
    if isinstance(value, str):
        return 'str:' + token_class(value)
    if isinstance(value, bool):
        return 'bool'
    if value is None:
        return 'null'
    return 'number:' + type(value).__name__


# ---------------------------------------------------------------- 本機快取

def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def file_store(cache_dir):
    files = (cache_dir / 'files').resolve()

    def store(relative, body):
        target = (files / relative).resolve()
        if files not in target.parents:
            raise ProbeError('快取路徑越界')
        _atomic_write(target, body)
    return store


def save_manifest(cache_dir, manifest):
    stamp = manifest['generated_at'].replace(':', '').replace('-', '')
    target = cache_dir / 'manifests' / f'manifest-{stamp}.json'
    data = json.dumps(manifest, ensure_ascii=False, indent=1).encode('utf-8')
    _atomic_write(target, data)
    _atomic_write(cache_dir / 'manifests' / 'latest.json', data)
    return target


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


# ---------------------------------------------------------------- 命令列

def summarize(manifest):
    files = [e for e in manifest['entries'] if e['kind'] == 'file']
    by_status = {}
    for e in manifest['entries']:
        by_status[e['status']] = by_status.get(e['status'], 0) + 1
    return {'files': len(files), 'dirs': len(manifest['entries']) - len(files),
            'requests': manifest['requests'], 'status_counts': by_status,
            'problems': len(manifest['problems'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description='官方資源探測工具（只做 GET，限速 2 req/s）')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan', help='列目錄、計算雜湊、輸出 manifest 並與上一版比對')
    s.add_argument('--base-url', default=os.environ.get('LALA_OFFICIAL_BASE_URL'))
    s.add_argument('--cache-dir', type=Path, default=DEFAULT_CACHE)
    s.add_argument('--max-depth', type=int, default=DEFAULT_MAX_DEPTH)
    s.add_argument('--hash-max-bytes', type=int, default=DEFAULT_HASH_MAX_BYTES)
    s.add_argument('--max-requests', type=int, default=DEFAULT_MAX_REQUESTS)
    s.add_argument('--skip-dir', action='append', default=None,
                   help=f'不展開的資料夾名稱或 glob（預設 {", ".join(DEFAULT_SKIP_DIRS)}）')
    s.add_argument('--include-dir', action='append', default=[], help='強制展開，優先於 --skip-dir')
    s.add_argument('--skip-file', action='append', default=None,
                   help=f'不下載的檔名 glob（預設 {", ".join(DEFAULT_SKIP_FILES)}）；傳 none 表示全部下載')
    s.add_argument('--previous', type=Path, help='上一版 manifest；預設用快取中的 latest.json')
    d = sub.add_parser('diff', help='比對兩份 manifest')
    d.add_argument('old', type=Path)
    d.add_argument('new', type=Path)
    x = sub.add_parser('describe', help='只輸出檔案的欄位格式，不輸出值')
    x.add_argument('files', type=Path, nargs='+')
    args = parser.parse_args(argv)

    if args.command == 'describe':
        print(json.dumps([describe_bytes(p.read_bytes(), p.name) for p in args.files],
                         ensure_ascii=False, indent=1))
        return 0
    if args.command == 'diff':
        print(json.dumps(diff_manifests(load_json(args.old), load_json(args.new)),
                         ensure_ascii=False, indent=1))
        return 0

    if not args.base_url:
        parser.error('需要 --base-url 或環境變數 LALA_OFFICIAL_BASE_URL（見 next/PLAN.md 第 5 節）')
    if not 1 <= args.max_requests <= 5000 or args.max_depth < 0 or args.hash_max_bytes < 0:
        parser.error('限制參數超出範圍')
    domain = registrable_domain(urlsplit(args.base_url).hostname)
    check_url(args.base_url, domain)
    cache_dir = args.cache_dir.expanduser()
    previous_path = args.previous or cache_dir / 'manifests' / 'latest.json'
    previous = load_json(previous_path) if previous_path.is_file() else None
    fetcher = HttpFetcher(domain)
    skip = tuple(args.skip_dir) if args.skip_dir is not None else DEFAULT_SKIP_DIRS
    skip_files = (DEFAULT_SKIP_FILES if args.skip_file is None
                  else tuple(x for x in args.skip_file if x != 'none'))
    try:
        manifest = scan(args.base_url, fetcher, max_depth=args.max_depth,
                        hash_max_bytes=args.hash_max_bytes, max_requests=args.max_requests,
                        skip_dirs=skip, include_dirs=tuple(args.include_dir), skip_files=skip_files,
                        store=file_store(cache_dir))
    except ProbeError as exc:
        print(f'探測失敗：{exc}', file=sys.stderr)
        return 2
    saved = save_manifest(cache_dir, manifest)
    report = {'manifest': str(saved), 'summary': summarize(manifest)}
    if previous is not None:
        report['diff'] = diff_manifests(previous, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if manifest['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
