"""Collect only atlas/emoji cache bundles and their manifest-declared dependencies."""
import re,struct,json,zipfile
from pathlib import Path
from datetime import datetime

RECORD=re.compile(rb'([a-z0-9_./-]+\.bundle)(.{4})\x20\x00([0-9a-f]{32})\x08\x00([0-9a-f]{8})',re.S)

def manifest_bundles(data):
    matches=list(RECORD.finditer(data));records=[]
    for m in matches:
        if m.start()<2 or struct.unpack_from('<H',data,m.start()-2)[0]!=len(m[1]):raise ValueError('資源清單格式不同，請提供 MainPackage 的 .bytes 清單')
        pos=m.end()+8+1
        tags=struct.unpack_from('<H',data,pos)[0];pos+=2
        for _ in range(tags):
            length=struct.unpack_from('<H',data,pos)[0];pos+=2+length
        count=struct.unpack_from('<H',data,pos)[0];pos+=2
        deps=list(struct.unpack_from('<'+'I'*count,data,pos))
        records.append({'name':m[1].decode('ascii'),'hash':m[3].decode('ascii'),'dependencies':deps})
    if not records:raise ValueError('清單中找不到圖集資源')
    wanted={i for i,r in enumerate(records) if r['name']=='mainpackage_atlas.bundle' or 'emoji' in r['name']}
    if not wanted:raise ValueError('清單中沒有表情圖集')
    pending=list(wanted)
    while pending:
        for index in records[pending.pop()]['dependencies']:
            if index>=len(records):raise ValueError('資源相依索引不同，請提供 MainPackage 的 .bytes 清單')
            if index not in wanted:wanted.add(index);pending.append(index)
    return [records[i] for i in sorted(wanted)]

def version(path):
    m=re.search(r'MainPackage_(\d+)',path.name,re.I)
    return (int(m[1]) if m else 0,path.stat().st_mtime)

def collect(root,destination):
    manifests=sorted(root.rglob('MainPackage*.bytes'),key=version,reverse=True)
    if not manifests:raise ValueError('找不到 MainPackage 清單，請選擇遊戲安裝資料夾或 _Data 資料夾')
    manifest=manifests[0];bundles=manifest_bundles(manifest.read_bytes())
    hashes={r['hash'] for r in bundles};found={}
    for p in root.rglob('__data'):
        if p.parent.name in hashes:found[p.parent.name]=p
    if not found:raise ValueError('找不到對應圖集快取，請先開啟原版遊戲的聊天表情選單再重試')
    report={'manifest':manifest.name,'bundles':bundles,'included':sorted(found),'missing':sorted(hashes-set(found))}
    destination=Path(destination)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        z.write(manifest,'ManifestFiles/'+manifest.name)
        for key,path in sorted(found.items()):z.write(path,'BundleFiles/'+key+'/__data')
        z.writestr('emoji_resources_report.json',json.dumps(report,ensure_ascii=False,indent=2))
    return report

def main():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    messagebox.showinfo('收集新版表情資源','請先在原版遊戲開啟聊天表情選單，再選擇遊戲安裝資料夾。\n只收集表情圖集、相依圖集及資源清單，輸出 ZIP 至本工具旁。',parent=root)
    folder=filedialog.askdirectory(title='選擇飄流 RE 遊戲安裝資料夾',parent=root)
    if not folder:root.destroy();return
    output=Path(__file__).resolve().parents[2]/('WLRE_Emoji_Resources_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.zip')
    try:
        report=collect(Path(folder),output)
        messagebox.showinfo('完成',f'已建立：{output}\n收集 {len(report["included"])} 個圖集；尚缺 {len(report["missing"])} 個相依資源。\n請將這份 ZIP 傳回以補齊 Emoji48～52。',parent=root)
    except (OSError,ValueError,struct.error) as exc:messagebox.showerror('收集未完成',str(exc),parent=root)
    finally:root.destroy()
if __name__=='__main__':main()
