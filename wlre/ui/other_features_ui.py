"""Other functions window; automation remains owned by the network thread."""
from tkinter import ttk
from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.ui.guild_actions_ui import GuildActionsPanel
from wlre.ui.star_ark_ui import StarArkPanel


class OtherFeaturesPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=12)
        self.tabs=RoundedNotebook(self,icons=True)
        self.tabs.pack(fill='both',expand=True)
        self.ark_panel=StarArkPanel(self.tabs,app)
        self.guild_panel=GuildActionsPanel(self.tabs,app)
        self.tabs.add(self.ark_panel,text='方舟')
        self.tabs.add(self.guild_panel,text='組織')

    def render(self,state):
        self.ark_panel.render(state)
        self.guild_panel.render(state)
