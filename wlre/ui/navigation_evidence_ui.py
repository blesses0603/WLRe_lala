"""Explicit local export of passive navigation observations."""
import json
from tkinter import filedialog,messagebox
from wlre.services.world.navigation_evidence import export


def save(parent,snapshot):
    if not snapshot or not snapshot.get('navigation_evidence',{}).get('events'):
        messagebox.showinfo('導航驗證','尚無定位紀錄；請先登入角色後再匯出。',parent=parent)
        return False
    path=filedialog.asksaveasfilename(parent=parent,defaultextension='.json',
        initialfile='navigation_evidence_1275.json',filetypes=[('JSON','*.json')])
    if not path:return False
    try:
        document=export(snapshot)
        with open(path,'w',encoding='utf8') as stream:json.dump(document,stream,ensure_ascii=False,indent=2,allow_nan=False)
    except (OSError,ValueError) as exc:
        messagebox.showerror('匯出失敗',str(exc),parent=parent);return False
    return True
