"""Import a user-extracted 1262 TalkData_C TextAsset into LaLa's optional index.

Usage:
    python -m tools.resources.import_npc_talks TalkData_C.bytes --output npc_talk_1262.json.gz

This tool does not extract/modify the installed game or claim that an
arbitrary input file comes from an official package. Keep its SHA256 as
provenance and independently verify the source before distributing it.
"""
import argparse
import gzip
import json
from pathlib import Path

from wlre.services.world.npc_talk import make_catalog, MAX_BINARY_BYTES


def convert(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_file() or source.stat().st_size > MAX_BINARY_BYTES:
        raise ValueError('TalkData_C 檔案不存在或超出安全上限')
    data = make_catalog(source.read_bytes())
    if destination.exists():
        raise FileExistsError('拒絕覆寫已存在的資料檔案')
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with gzip.open(destination, 'xb') as stream:
        stream.write(payload)
    return len(data['records']), data['source_sha256']


def main():
    parser = argparse.ArgumentParser(description='依官方 1262 Lua 轉換 TalkData_C')
    parser.add_argument('input', help='已獨立核對的 TalkData_C TextAsset 原始 bytes')
    parser.add_argument('--output', required=True, help='輸出 .json.gz（不覆寫）')
    args = parser.parse_args()
    count, checksum = convert(args.input, args.output)
    print(f'匯出 {count} 筆 TalkData_C；輸入 SHA256：{checksum}')


if __name__ == '__main__':
    main()
