"""Read-only official database preview dialog; no game command dependency."""
import tkinter as tk
from tkinter import ttk
from wlre.services.world.navigation_preview_job import PreviewJob


class OfficialNavigationPreview:
    def __init__(self,parent,state_getter):
        self.state_getter=state_getter;self.job=PreviewJob();self.validation_error=None
        self.window=tk.Toplevel(parent);self.window.title('官方資料庫導航預覽');self.window.geometry('640x520')
        body=ttk.Frame(self.window,padding=12);body.pack(fill='both',expand=True)
        ttk.Label(body,text='讀取官方導航資料庫；預覽不會移動角色。').pack(anchor='w')
        form=ttk.Frame(body);form.pack(fill='x',pady=8)
        player=state_getter().get('player',{});self.fields=[]
        for i,(name,value) in enumerate((('地圖 ID',player.get('scene',10000)),('起點 X',player.get('x',0)),('起點 Y',player.get('y',0)),('終點 X',player.get('x',0)),('終點 Y',player.get('y',0)))):
            ttk.Label(form,text=name).grid(row=i,column=0,sticky='w')
            field=ttk.Entry(form);field.insert(0,str(value));field.grid(row=i,column=1,sticky='ew');self.fields.append(field)
        form.columnconfigure(1,weight=1)
        self.mode=ttk.Combobox(body,values=('步行','海上','飛行'),state='readonly');self.mode.set('步行');self.mode.pack(fill='x')
        self.smooth=tk.BooleanVar(value=False);ttk.Checkbutton(body,text='平面走廊平滑（斜坡會拒絕）',variable=self.smooth).pack(anchor='w')
        actions=ttk.Frame(body);actions.pack(fill='x',pady=6)
        ttk.Button(actions,text='從資料庫預覽',command=lambda:self.run(False)).pack(side='left')
        ttk.Button(actions,text='同步此地圖並預覽',command=lambda:self.run(True)).pack(side='left',padx=8)
        self.status=tk.StringVar(value='同步每個模型最多 2 個檔案／32 MiB。');ttk.Label(body,textvariable=self.status,wraplength=600).pack(fill='x')
        self.output=tk.Text(body,height=10,state='disabled');self.output.pack(fill='both',expand=True,pady=8)
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Destroy>',self.destroyed,add='+')
        self.timer=self.window.after(200,self.poll)

    def run(self,download):
        try:
            self.validation_error=None
            values=[f.get() for f in self.fields]
            self.job.start(self.state_getter(),values[0],values[1:3],values[3:5],
                           travel_mode={'步行':'land','海上':'sea','飛行':'sky'}[self.mode.get()],smooth=self.smooth.get(),download=download)
        except (ValueError,KeyError) as error:self.validation_error=str(error);self.status.set(str(error))

    def poll(self):
        value=({'status':'error','message':self.validation_error} if self.validation_error else self.job.poll(self.state_getter()));self.status.set(value['message'])
        result=value.get('result');text=''
        if result:
            text='地圖：'+str(result['logical_map'])+'\n來源：'+result.get('source_label','官方已校驗資料庫')+'\n'
            text+='\n'.join(f'{x:.2f}, {y:.2f}' for x,y in result['packet_points_xy_float'][:256])
        self.output.configure(state='normal');self.output.delete('1.0','end');self.output.insert('1.0',text);self.output.configure(state='disabled')
        self.timer=self.window.after(250,self.poll)

    def destroyed(self,event):
        if event.widget is self.window:
            self.job.close()
            if getattr(self,'timer',None):
                try:self.window.after_cancel(self.timer)
                except tk.TclError:pass

    def close(self):
        self.job.close()
        if self.timer:self.window.after_cancel(self.timer)
        self.window.destroy()
