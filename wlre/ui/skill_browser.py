"""Game-style read-only skill browsing; casting remains SkillView's command."""
import tkinter as tk
from copy import deepcopy
from tkinter import ttk
from PIL import Image, ImageTk
from wlre.ui.theme import group
from wlre.ui.skill_browser_model import (CATEGORIES, actor_key, skill_key, matches,
                                         detail_text, level_text)
from wlre.services.items.combat_resources import CAT, skill_rows
from wlre.services.world.character_portraits import PortraitProvider
from wlre.ui.skill_icons import SkillIcons, icon_name


class SkillBrowser(ttk.Frame):
    def __init__(self, parent, on_cast):
        super().__init__(parent, padding=6)
        self.state = {}; self.actors = []; self.rows = {}; self.skill_map = {}
        self.query = ''; self.live = False; self.closed = False; self.photos = {}
        self.provider = PortraitProvider(); self.portrait_job = None; self.portrait_revisions = {}
        self.render_signature = None
        self.icons = SkillIcons(self, self.icon_ready); self.skill_photos = {}; self.detail_photo = None
        self.selected_actor = None; self.selected_skill = None
        self.category = tk.StringVar(value='全部')
        self.columnconfigure(0, minsize=145); self.columnconfigure(1, weight=4, minsize=300)
        self.columnconfigure(2, weight=3, minsize=300); self.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.configure('SkillList.Treeview', rowheight=52)
        style.configure('SkillActors.Treeview', rowheight=58)
        side = group(self, text='角色與夥伴', padding=6)
        side.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        self.actor_list = ttk.Treeview(side, show='tree', selectmode='browse',
                                       style='SkillActors.Treeview', height=5)
        self.actor_list.column('#0', width=140, minwidth=90)
        self.actor_list.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(side, command=self.actor_list.yview)
        scrollbar.pack(side='right', fill='y'); self.actor_list.configure(yscrollcommand=scrollbar.set)
        self.actor_list.bind('<<TreeviewSelect>>', self.pick_actor)
        middle = group(self, text='特技詳細資料', padding=10)
        middle.grid(row=0, column=1, sticky='nsew', padx=(0, 6))
        head = ttk.Frame(middle); head.pack(fill='x')
        self.icon = ttk.Label(head, text='特技', width=6, anchor='center')
        self.icon.pack(side='left', padx=(0, 8))
        labels = ttk.Frame(head); labels.pack(side='left', fill='x', expand=True)
        self.title = ttk.Label(labels, text='選擇一項特技', style='Heading.TLabel', wraplength=220)
        self.title.pack(anchor='w')
        self.level = ttk.Label(labels, text=''); self.level.pack(anchor='w', pady=3)
        self.cost = ttk.Label(middle, text='', style='Muted.TLabel'); self.cost.pack(anchor='w', pady=6)
        self.progress = ttk.Label(middle, text='', style='Muted.TLabel')
        self.progress.pack(anchor='w', pady=(0, 8))
        # Text has its own scrollbar, so long official descriptions cannot hide buttons.
        details = ttk.Frame(middle); details.pack(fill='both', expand=True)
        self.details = tk.Text(details, wrap='word', width=24, height=8, relief='flat', font='TkDefaultFont',
                               borderwidth=0, state='disabled', padx=6, pady=6)
        scroll = ttk.Scrollbar(details, command=self.details.yview)
        scroll.pack(side='right', fill='y'); self.details.configure(yscrollcommand=scroll.set)
        self.details.pack(fill='both', expand=True)
        self.cast = ttk.Button(middle, text='施放選取特技（戰鬥內）', command=on_cast, state='disabled')
        self.cast.pack(fill='x', pady=(8, 3))
        ttk.Label(middle, text='點選僅查看，不會自動施放或升級。', style='Muted.TLabel',
                  wraplength=290).pack(anchor='w')
        right = group(self, text='已確認特技', padding=6)
        right.grid(row=0, column=2, sticky='nsew')
        filters = ttk.Frame(right); filters.pack(fill='x', pady=(0, 5))
        for index, category in enumerate(CATEGORIES):
            ttk.Radiobutton(filters, text=category, value=category, variable=self.category,
                            command=self.render_skills).grid(row=index // 3, column=index % 3, sticky='w')
        self.count = ttk.Label(right, text='', style='Muted.TLabel'); self.count.pack(anchor='w')
        body = ttk.Frame(right); body.pack(fill='both', expand=True)
        self.list = ttk.Treeview(body, columns=('level', 'sp'), show='tree headings',
                                selectmode='browse', style='SkillList.Treeview', height=5)
        self.list.heading('#0', text='特技'); self.list.column('#0', width=145, minwidth=110)
        self.list.heading('level', text='等級'); self.list.column('level', width=65, minwidth=55, stretch=False)
        self.list.heading('sp', text='SP'); self.list.column('sp', width=45, minwidth=40, stretch=False)
        bar = ttk.Scrollbar(body, command=self.list.yview); bar.pack(side='right', fill='y')
        self.list.configure(yscrollcommand=bar.set); self.list.pack(fill='both', expand=True)
        self.list.bind('<<TreeviewSelect>>', self.pick_skill)
        self.bind('<Destroy>', self.close, add='+')

    def render(self, state, actors, query, live):
        if self.closed: return
        self.state, self.actors, self.query, self.live = state, actors, query, live
        keys = [actor_key(actor) for actor in actors]
        selected = self.selected_actor if self.selected_actor in keys else (keys[0] if keys else None)
        for key in self.actor_list.get_children():
            if key not in keys:
                self.actor_list.delete(key)
                self.photos.pop(key, None); self.portrait_revisions.pop(key, None)
        for actor in actors:
            key = actor_key(actor)
            level = actor.get('level', '?')
            label = actor.get('name', '') or ('角色' if not actor.get('npc_index') else '夥伴')
            if actor.get('npc_index'): label = f"#{actor['npc_index']} {label}"
            text = f'{label}\nLv.{level}'
            if self.actor_list.exists(key):
                if self.actor_list.item(key, 'text') != text: self.actor_list.item(key, text=text)
                self.actor_list.move(key, '', 'end')
            else:
                self.actor_list.insert('', 'end', iid=key, text=text)
        self.selected_actor = selected
        if selected: self.actor_list.selection_set(selected)
        self.refresh_portraits(); self.render_skills()

    def refresh_portraits(self):
        if self.closed: return
        if self.portrait_job is not None:
            self.after_cancel(self.portrait_job); self.portrait_job = None
        for actor in self.actors:
            key = actor_key(actor); view = self.state; kind = 'player'
            if actor.get('npc_index'):
                kind = 'companion'
                knowledge = self.state.get('knowledge', {})
                slot = str(actor['npc_index'])
                profile = knowledge.get('companions', {}).get(slot)
                view = dict(self.state, knowledge=dict(knowledge, active_npc_id=actor['pid'],
                            companions={slot: profile} if profile else {}))
            result = self.provider.request(view, kind, 40)
            revision = result.get('revision')
            if revision is not None and self.portrait_revisions.get(key) == revision:
                continue
            self.portrait_revisions[key] = revision
            pixels = result.get('image')
            if not isinstance(pixels, Image.Image):
                self.actor_list.item(key, image=''); self.photos.pop(key, None); continue
            photo = ImageTk.PhotoImage(pixels, master=self)
            self.photos[key] = photo; self.actor_list.item(key, image=photo)
        self.photos = {k:v for k,v in self.photos.items() if self.actor_list.exists(k)}
        self.portrait_job = self.after(1000, self.refresh_portraits)

    def pick_actor(self, event=None):
        selected = self.actor_list.selection()
        if selected and selected[0] != self.selected_actor:
            self.selected_actor = selected[0]; self.selected_skill = None; self.render_skills()

    def render_skills(self):
        if self.closed: return
        actor = next((a for a in self.actors if actor_key(a) == self.selected_actor), None)
        entries = [(row, CAT['skills'].get(str(row['id']), {})) for row in skill_rows(self.state, actor)
                   if matches(row, actor, self.query, self.category.get())] if actor else []
        signature = (self.selected_actor, actor, entries, self.live, self.state.get('battle', {}).get('active', False))
        if signature == self.render_signature:
            return
        self.render_signature = deepcopy(signature)
        previous = self.selected_skill
        self.list.delete(*self.list.get_children()); self.rows = {}; self.skill_map = {}; self.skill_photos = {}
        for row, data in entries:
            key = skill_key(actor, row['id'])
            self.rows[key] = (row, data); self.skill_map[key] = (actor, row['id'])
            limit = data.get('LvLimit')
            level = 'MAX' if type(limit) is int and limit > 0 and row['level'] >= limit else f"Lv.{row['level']}"
            photo = self.icons.get(data, 40)
            if photo is not None: self.skill_photos[key] = photo
            self.list.insert('', 'end', iid=key, text=row['name'], image=photo or '',
                             values=(level, row['sp'] if row['sp'] is not None else '?'))
        keys = list(self.rows)
        self.selected_skill = previous if previous in self.rows else (keys[0] if keys else None)
        self.count.configure(text=f'{len(keys)} 項特技' if keys else '沒有符合條件的已確認特技')
        if self.selected_skill: self.list.selection_set(self.selected_skill); self.list.see(self.selected_skill)
        self.show_detail()

    def icon_ready(self, icon_key, photo):
        if self.closed or photo is None: return
        name, size = icon_key
        if size == 40:
            for key, (_row, data) in self.rows.items():
                if icon_name(data) == name and self.list.exists(key):
                    self.skill_photos[key] = photo
                    self.list.item(key, image=photo)
        elif size == 64:
            entry = self.rows.get(self.selected_skill)
            if entry is not None and icon_name(entry[1]) == name:
                self.detail_photo = photo
                self.icon.configure(image=photo, text='')

    def pick_skill(self, event=None):
        selected = self.list.selection()
        if selected and selected[0] in self.rows:
            self.selected_skill = selected[0]; self.show_detail()

    def show_detail(self):
        entry = self.rows.get(self.selected_skill)
        self.details.configure(state='normal'); self.details.delete('1.0', 'end')
        if entry is None:
            self.title.configure(text='選擇一項特技'); self.level.configure(text=''); self.cost.configure(text='')
            self.progress.configure(text=''); self.cast.configure(state='disabled')
            self.icon.configure(image='', text='特技'); self.detail_photo = None
            self.details.insert('end', '僅列出伺服器已確認的已學／裝備附帶特技。\n尚未同步或搜尋無結果時，不會猜測技能。')
        else:
            row, data = entry
            self.detail_photo = self.icons.get(data, 64)
            self.icon.configure(image=self.detail_photo or '', text='' if self.detail_photo else '圖示\n待同步')
            self.title.configure(text=row['name']); self.level.configure(text=level_text(row, data))
            self.cost.configure(text=f"{row['category']}   SP：{row['sp'] if row['sp'] is not None else '待同步'}")
            limit = data.get('LvLimit')
            self.progress.configure(text='已達等級上限' if type(limit) is int and limit > 0 and row['level'] >= limit else '技能等級以伺服器回報為準')
            active = self.state.get('battle', {}).get('active', False)
            self.cast.configure(state='normal' if self.live and active and not row.get('reasons') else 'disabled')
            self.details.insert('end', detail_text(row, data, self.live, active))
        self.details.configure(state='disabled'); self.details.yview_moveto(0)

    def close(self, event):
        if event.widget is not self or self.closed: return
        self.closed = True
        if self.portrait_job is not None:
            self.after_cancel(self.portrait_job); self.portrait_job = None
        self.provider.close(); self.photos.clear(); self.icons.close(); self.skill_photos.clear()
