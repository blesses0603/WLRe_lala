"""Outpost companion roster stays backed by authoritative server state."""
from wlre.ui.layout import scroll_table
from wlre.services.items.combat_resources import CAT


def build_companion_table(self, body):
    frame, self.roles = scroll_table(body, ('name', 'faith', 'state'),
        ('夥伴', '好友度', '狀態'), (90, 55, 60), horizontal_scrollbar=False)
    frame.grid(row=1, column=1, sticky='nsew', padx=(0, 8))


class ExpeditionTeamListMixin:
    def render_companion_rows(self, e):
        for r in sorted(e.get('roles', {}).values(), key=lambda r: r['index']):
            name = CAT['npcs'].get(str(r['npc_id']), {}).get('name', f"夥伴 {r['npc_id']}")
            self.roles.insert('', 'end', values=(name, r['faith'], '閒置' if r['state'] == 0 else '遠征中'))
