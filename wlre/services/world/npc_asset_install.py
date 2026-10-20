"""Install verified 1262 NPC text assets without extracting arbitrary archive paths."""
import argparse
import gzip
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

from wlre.paths import RESOURCE_ROOT

ASSETS = {
 'npc_talk_1262.json.gz': ('f47212c1e46cf44f323756ff724813e81990c945587c8b966efdb7fd5ed69599',886406,'TalkData_C','df9d98d268cc8cb26a109f50aee90405eefe2328c5862447f9297cb67ead45be',29873),
 'npc_text_1262.json.gz': ('b99d65a0c2b6c37ab9ddbbae276c102c49560ec8d54bdda27296e2ebddc32f1d',757105,'TextData_C','5b2d0a7e4e5048a629630e490c8c1e1bb1498f840b754087d59de28951d9aaf0',39901),
 'npc_battle_talk_1262.json.gz': ('f592a9e07feebe29383a946130625f45a58bd22e3a68efb225770599e8d11f14',653,'NpcTalkData_C','9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8',16),
}
MAX_UNCOMPRESSED=16*1024*1024


def read_verified(zip_path, expected=ASSETS):
    """All-or-nothing verification before writing; avoid path traversal."""
    result={}
    with ZipFile(zip_path) as archive:
        if len(archive.infolist()) > 32:
            raise ValueError('索引包檔案數量不合理')
        for name,(digest,size,source,source_digest,count) in expected.items():
            info=archive.getinfo('wlre/resources/'+name)
            if info.file_size != size:
                raise ValueError(name+': 檔案長度不正確')
            raw=archive.read(info)
            if hashlib.sha256(raw).hexdigest()!=digest:
                raise ValueError(name+': SHA-256 核對失敗')
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                content=stream.read(MAX_UNCOMPRESSED+1)
            if len(content)>MAX_UNCOMPRESSED:
                raise ValueError(name+': 解壓縮超過限制')
            obj=json.loads(content.decode('utf-8'))
            if (not isinstance(obj,dict) or obj.get('version')!=1262
                or obj.get('source')!=source
                or obj.get('source_sha256')!=source_digest
                or not isinstance(obj.get('records'),dict)
                or len(obj['records'])!=count):
                raise ValueError(name+': 版本／來源／筆數不符')
            result[name]=raw
    return result


def install(zip_path,destination=None,check=False,replace=False,expected=ASSETS):
    data=read_verified(zip_path,expected)
    if check: return {name:len(raw) for name,raw in data.items()}
    target=Path(destination) if destination is not None else RESOURCE_ROOT
    if not target.is_dir():
        raise FileNotFoundError('找不到 LaLa 資源目錄：'+str(target))
    conflicts=[name for name in data if (target/name).exists()]
    if conflicts and not replace:
        raise FileExistsError('已存在資源（需 --replace 才覆寫）：'+', '.join(conflicts))
    pending=[]
    try:
        for name,raw in data.items():
            with tempfile.NamedTemporaryFile(mode='wb',delete=False,dir=target,
                                             prefix='.npc_import_',suffix='.tmp') as fh:
                fh.write(raw)
                pending.append((Path(fh.name),target/name))
        for tmp,final in pending:
            os.replace(tmp,final)
    finally:
        for tmp,_ in pending:
            if tmp.exists():tmp.unlink()
    return {name:len(raw) for name,raw in data.items()}


def main():
    parser=argparse.ArgumentParser(description='核對並匯入 1262 NPC 繁中資料包')
    parser.add_argument('archive',help='WLRE_1262_NPC_繁中資料索引包.zip 路徑')
    parser.add_argument('--check',action='store_true',help='只驗證不寫入')
    parser.add_argument('--replace',action='store_true',help='確認覆寫舊有資源')
    args=parser.parse_args()
    result=install(args.archive,check=args.check,replace=args.replace)
    print('驗證通過'+('（不寫入）' if args.check else '；安裝完成'))
    for name,size in result.items():
        print(f'  {name}: {size:,} bytes')


if __name__=='__main__':
    main()
