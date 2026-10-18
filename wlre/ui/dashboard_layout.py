"""Main-window geometry, separate from session and command handling."""
from tkinter import ttk


class DashboardLayout:
    def __init__(self,root,app):
        self.body=ttk.Frame(root,padding=10)
        self.body.pack(fill='both',expand=True)
        header=ttk.Frame(self.body,padding=(8,4))
        header.pack(fill='x',pady=(0,6))
        header.columnconfigure(0,weight=1)
        self.position=ttk.Label(header,textvariable=app.world_compact,style='Heading.TLabel',width=1)
        self.position.grid(row=0,column=0,sticky='ew')
        ttk.Button(header,text='登入／選角',command=app.show_login).grid(row=0,column=2,padx=(6,0))
        ttk.Button(header,text='中斷連線',command=app.stop).grid(row=0,column=1,padx=(6,0))
        self.status=ttk.Label(header,textvariable=app.status,style='Muted.TLabel',width=1)
        self.status.grid(row=1,column=0,columnspan=1,sticky='ew',pady=(3,0))
        self.connection=ttk.Label(header,textvariable=app.connection_status,style='Muted.TLabel',anchor='e',width=43)
        self.connection.grid(row=1,column=1,columnspan=2,sticky='e',pady=(3,0))
        self.content=ttk.Frame(self.body)
        self.content.pack(fill='both',expand=True)
        self.content.columnconfigure(0,weight=1,minsize=870)
        self.content.columnconfigure(1,weight=0,minsize=380)
        self.content.rowconfigure(0,weight=1)
        self.left=ttk.Frame(self.content,width=870)
        self.left.grid(row=0,column=0,sticky='nsew',padx=(0,10))
        self.left.grid_propagate(False);self.left.pack_propagate(False)
        self.right=ttk.Frame(self.content,width=380)
        self.right.grid(row=0,column=1,sticky='nsew')
        self.right.grid_propagate(False)
