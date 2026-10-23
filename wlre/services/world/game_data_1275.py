"""Offline, read-only verification of the user's 1275 game data archive.

This is NOT a runtime 1275 protocol/quest compatibility declaration. Source
index is pinned; no downloaded code, game binaries or guessed IDs are used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

VERSION = 1275
MANIFEST_SHA256 = 'a069027a05aa332c57048164a61b839896c12926bfe93dfd2b52daf5c58d0dc4'
MAX_MANIFEST = 160 * 1024
MAX_ENTRY = 16 * 1024 * 1024
MAX_FILES = 168
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
TABLE_NAME = re.compile(r'[A-Za-z0-9_]+\Z')


def _valid_manifest(data):
    if (type(data) is not dict or data.get('schema_version') != 1
            or data.get('official_resource_revision') != VERSION
            or data.get('base_resource_revision') != 1262
            or not isinstance(data.get('files'), dict)
            or len(data['files']) != 163
            or not isinstance(data.get('changed_bundles'), list)
            or len(data['changed_bundles']) != 59
            or not isinstance(data.get('new_main_assets'), list)
            or len(data['new_main_assets']) != 63):
        raise ValueError('1275 檔案清單版本或統計資訊無效')
    tables, indexes = set(), 0
    for name, item in data['files'].items():
        if not isinstance(name, str) or not isinstance(item, dict):
            raise ValueError('1275 檔案名稱或索引格式不正確')
        if (type(item.get('bytes')) is not int or not 0 < item['bytes'] <= MAX_ENTRY
                or not isinstance(item.get('sha256'), str)
                or not HEX64.fullmatch(item['sha256'])):
            raise ValueError('1275 檔案大小或 SHA-256 不正確')
        if item.get('kind') == 'raw_table':
            table, bundle = item.get('table'), item.get('bundle')
            if (not isinstance(table, str) or not TABLE_NAME.fullmatch(table)
                    or not isinstance(bundle, str)
                    or not re.fullmatch(r'datapackage_data_[a-z]\.bundle', bundle)
                    or name != f'tables/{bundle}/{table}.bytes' or table in tables):
                raise ValueError('1275 資料表名稱／Bundle 不合法或重複')
            tables.add(table)
        elif item.get('kind') == 'read_only_index':
            if not re.fullmatch(r'indexes/npc_(?:talk|text|item_data)_1275\.json\.gz', name):
                raise ValueError('1275 索引檔名稱不合法')
            indexes += 1
        else:
            raise ValueError('未知 1275 資料分類')
    if len(tables) != 160 or indexes != 3:
        raise ValueError('1275 資料表或索引檔數量不符')
    bundles = set()
    for row in data['changed_bundles']:
        if (not isinstance(row, dict) or row.get('package') not in ('DataPackage','MainPackage')
                or row.get('status') not in ('內容異動','新增')
                or not isinstance(row.get('name'), str)
                or not row['name'].endswith('.bundle')
                or not isinstance(row.get('new_hash'), str)
                or not re.fullmatch(r'[0-9a-f]{32}', row['new_hash'])
                or row['name'] in bundles):
            raise ValueError('Bundle 差異記錄不合法')
        bundles.add(row['name'])
    return data


def read_manifest(archive: ZipFile):
    """Always pin the complete manifest before accepting any external bytes."""
    info = archive.getinfo('manifest.json')
    if info.file_size > MAX_MANIFEST:
        raise ValueError('1275 Manifest 超出限制')
    raw = archive.read(info)
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError('1275 Manifest SHA-256 不符')
    return _valid_manifest(json.loads(raw.decode('utf-8')))


def verify_archive(path):
    """Read every member once; no ZIP extraction or game installation changes."""
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES or len(infos) != len(set(v.filename for v in infos)):
            raise ValueError('壓縮包內有重複檔案或數量異常')
        manifest = read_manifest(archive)
        expected = set(manifest['files']) | {'manifest.json', '使用說明.txt'}
        if set(archive.namelist()) != expected:
            raise ValueError('壓縮包缺漏或含未知檔案')
        for name, file in manifest['files'].items():
            info = archive.getinfo(name)
            if info.is_dir() or info.file_size != file['bytes']:
                raise ValueError(f'{name}：檔案長度不符')
            digest = hashlib.sha256()
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != file['sha256']:
                raise ValueError(f'{name}：SHA-256 不符')
        return {'revision': VERSION, 'verified_files': len(manifest['files']),
                'tables': 160, 'indexes': 3, 'changed_bundles': 59,
                'new_main_assets': 63, 'manifest_sha256': MANIFEST_SHA256}


def read_table(path, table):
    """Explicit offline access, never used by NPC interaction or trade dispatch."""
    if not isinstance(table, str) or not TABLE_NAME.fullmatch(table):
        raise ValueError('資料表名稱不合法')
    verify_archive(path)
    with ZipFile(path) as archive:
        manifest = read_manifest(archive)
        matches = [name for name, info in manifest['files'].items()
                   if info.get('kind') == 'raw_table' and info['table'] == table]
        if len(matches) != 1:
            raise KeyError('1275 不存在此資料表：' + table)
        return archive.read(matches[0])


def main():
    parser = argparse.ArgumentParser(description='1275 全部 160 張 DataPackage 資料表離線校驗')
    parser.add_argument('archive', type=Path, help='WLRE_LaLa_1275_全資源差異與校驗包.zip')
    parser.add_argument('--table', help='額外確認並讀取特定資料表，例如 DailyTaskData_C')
    args = parser.parse_args()
    result = verify_archive(args.archive)
    if args.table:
        result['selected_table'] = args.table
        result['selected_table_bytes'] = len(read_table(args.archive, args.table))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('這是官方資料離線驗證；LaLa 的 1275 線上相容性尚未宣告通過。')


if __name__ == '__main__':
    main()
