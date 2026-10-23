"""Optional, independently verified 1275 read-only NPC data indexes.

Deliberately NOT wired to 1262 EventData or NPC shop commands: 1275 Eve
indexes must be verified independently before any interaction can be enabled.
The user's game assets are distributed separately, never committed as code.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile

VERSION = 1275
MAX_INDEX_ZIP_FILES = 8
MAX_COMPRESSED = 2 * 1024 * 1024
MAX_UNCOMPRESSED = 16 * 1024 * 1024
# name -> (source table, expected extracted-table SHA256, gzip SHA256, gzip bytes, row count)
INDEXES = {
    'npc_talk_1275.json.gz': (
        'TalkData_C', 'e111fe662cb6909aa9df650c4a9735a828440cbed3c6c5794381bd1721e2fbbb',
        '4e0c0540b9d9cdff5922557e4a3b296e833cc1150ea8b68acbf248639e66a0d7', 888002, 29890),
    'npc_text_1275.json.gz': (
        'TextData_C', '5c61277ec3044616938db58750cba116e623f66e01f33aef4f98a72d88204ea4',
        '8793d442c6228ebcc6e03139fcf2f5c4002e8745e0ff2b6c2aabfd8bbf77f0bf', 759116, 39947),
    'npc_item_data_1275.json.gz': (
        'ItemData_C', '98a9b90494c1ba20d9b29a5bd4d453bab7540c7a8529551717719d4fc8ee73e8',
        '7f1874e930b8455a5cdda2c3abb3d1c61bc82478f05ece693fb25f19d73a512a', 113067, 11304),
}


def verify_index(name: str, content: bytes) -> dict:
    """Validate signed-off local extraction digest, size, schema and bounds."""
    if name not in INDEXES or not isinstance(content, bytes):
        raise ValueError('未知或無效的 1275 資料索引')
    source, source_sha, digest, size, count = INDEXES[name]
    if len(content) != size or len(content) > MAX_COMPRESSED:
        raise ValueError(name + '：壓縮檔大小不符')
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(name + '：SHA-256 與官方提取後索引不符')
    with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
        raw = stream.read(MAX_UNCOMPRESSED + 1)
    if len(raw) > MAX_UNCOMPRESSED:
        raise ValueError(name + '：解壓縮超過限制')
    document = json.loads(raw.decode('utf-8'))
    if (not isinstance(document, dict) or document.get('version') != VERSION
            or document.get('source') != source
            or document.get('source_sha256') != source_sha
            or document.get('record_count') != count
            or not isinstance(document.get('records'), dict)
            or len(document['records']) != count):
        raise ValueError(name + '：資料版本、來源或紀錄數不符')
    for key, row in document['records'].items():
        if (not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key
                or not 0 <= int(key) <= (65535 if source != 'TextData_C' else 0xffffffff)):
            raise ValueError(name + '：資料 ID 不合法')
        if source == 'TalkData_C':
            if (not isinstance(row, dict) or set(row) != {'text', 'voice_id'}
                    or not isinstance(row['text'], str) or len(row['text']) > 16384
                    or type(row['voice_id']) is not int or not 0 <= row['voice_id'] <= 65535):
                raise ValueError(name + '：對話內容不合法')
        elif source == 'TextData_C':
            if not isinstance(row, str) or len(row) > 8192:
                raise ValueError(name + '：文字內容不合法')
        else:
            if (not isinstance(row, dict)
                    or set(row) != {'name', 'price', 'sell_price', 'restrict', 'open_used', 'need_level'}
                    or not isinstance(row['name'], str) or not 0 < len(row['name']) <= 512
                    or any(type(row[field]) is not int for field in
                           ('price', 'sell_price', 'restrict', 'open_used', 'need_level'))
                    or not 0 <= row['price'] <= 0xffffffff
                    or not 0 <= row['sell_price'] <= 0xffffffff
                    or not 0 <= row['restrict'] <= 65535
                    or not 0 <= row['open_used'] <= 255
                    or not 0 <= row['need_level'] <= 255):
                raise ValueError(name + '：物品資料內容不合法')
    return document


def read_verified(archive: Path) -> dict[str, bytes]:
    """Load exact expected members; never extract attacker-controlled paths."""
    result = {}
    with ZipFile(archive) as z:
        if len(z.infolist()) > MAX_INDEX_ZIP_FILES:
            raise ValueError('1275 索引包檔案數超過限制')
        for name in INDEXES:
            info = z.getinfo('wlre/resources/' + name)
            if info.is_dir() or info.file_size > MAX_COMPRESSED:
                raise ValueError(name + '：無效 ZIP 條目')
            raw = z.read(info)
            verify_index(name, raw)
            result[name] = raw
    return result


def install(archive: Path, destination: Path, *, check_only=True) -> dict[str, int]:
    """Verify all files before installing; NEVER overwrite 1262 indexes."""
    files = read_verified(archive)
    sizes = {name: len(value) for name, value in files.items()}
    if check_only:
        return sizes
    root = Path(destination)
    if not root.is_dir():
        raise FileNotFoundError('LaLa 資源目錄不存在：' + str(root))
    if any((root/name).exists() for name in files):
        raise FileExistsError('1275 索引已存在，拒絕覆寫；請先人工檢查版本')
    created = []
    temporary = []
    try:
        for name, value in files.items():
            with tempfile.NamedTemporaryFile(dir=root, prefix='.wlre1275_', suffix='.tmp',
                                             delete=False) as stream:
                stream.write(value)
                temporary.append((Path(stream.name), root/name))
        for temp, dest in temporary:
            if dest.exists():
                raise FileExistsError('偵測到資料檔衝突，拒絕覆寫：'+dest.name)
            os.link(temp, dest)
            created.append(dest)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        for temp, _ in temporary:
            temp.unlink(missing_ok=True)
    return sizes


def load_read_only(name: str, root: Path) -> dict:
    """Standalone data reader. Does not authorize packets or replace 1262 Eve."""
    return verify_index(name, (Path(root) / name).read_bytes())['records']


def main():
    parser = argparse.ArgumentParser(description='驗證並選擇性安裝 1275 唯讀 NPC 來源索引')
    parser.add_argument('archive', type=Path, help='WLRE_1275_索引包.zip')
    parser.add_argument('--destination', type=Path, help='LaLa 專案的 wlre/resources 目錄')
    parser.add_argument('--install', action='store_true', help='實際安裝，預設僅驗證')
    args = parser.parse_args()
    if args.install and args.destination is None:
        parser.error('--install 必須明確指定 --destination')
    counts = install(args.archive, args.destination or Path('.'), check_only=not args.install)
    for name, size in counts.items():
        print(f'驗證通過：{name} ({size:,} bytes)')
    print('1275 索引' + ('已安裝，但未切換 NPC 互動資料來源' if args.install else '檢驗完成，未寫入'))


if __name__ == '__main__':
    main()
