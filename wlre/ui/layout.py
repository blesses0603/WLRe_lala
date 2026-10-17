"""Shared spacing, headers and scrollable tables for desktop views."""
from tkinter import ttk

SPACE=8


def heading(parent,title,subtitle=None):
    frame=ttk.Frame(parent)
    frame.pack(fill='x',pady=(0,SPACE))
    ttk.Label(frame,text=title,style='Heading.TLabel').pack(anchor='w')
    if subtitle:
        label=ttk.Label(frame,text=subtitle,style='Muted.TLabel',wraplength=700)
        label.pack(fill='x',pady=(3,0))
        label.bind('<Configure>',lambda e:label.configure(wraplength=max(80,e.width)))
    return frame


def scroll_table(parent,columns,headings,widths,height=4,show='headings',scrollbars=True):
    frame=ttk.Frame(parent)
    frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    tree=ttk.Treeview(frame,columns=columns,show=show,height=height,selectmode='browse')
    for key,title,width in zip(columns,headings,widths):
        tree.heading(key,text=title);tree.column(key,width=width,minwidth=44)
    tree.grid(row=0,column=0,sticky='nsew')
    if scrollbars:
        vertical=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew')
    return frame,tree
