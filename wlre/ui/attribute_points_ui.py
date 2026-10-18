"""Original LaLa attribute allocation window, separate from game Lua UI."""
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.ui.window_layout import configure_dialog
from wlre.services.battle.attribute_points import FIELDS, KEYS, MAX_BASE_ATTRIBUTE, baseline


class AttributePointWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("角色能力 · 配點")
        configure_dialog(self.window, 570, 505)
        self.base = None
        self.add = {key: 0 for key in KEYS}
        self.queued = False
        self.role = tk.StringVar(value="角色資料待同步")
        self.points = tk.StringVar(value="剩餘點數：待同步")
        self.note = tk.StringVar(value="尚未配點；確認前只會預覽，不會消耗點數。")

        body = ttk.Frame(self.window, padding=(20, 14))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="角色能力配點", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self.role).pack(anchor="w", pady=(8, 3))
        ttk.Label(body, textvariable=self.points, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        table = ttk.Frame(body)
        table.pack(fill="x", expand=True)
        self.values = {}
        self.buttons = {}
        for i, (key, _kind, label) in enumerate(FIELDS):
            line = ttk.Frame(table, padding=(4, 5))
            line.grid(row=i, column=0, sticky="ew")
            table.columnconfigure(0, weight=1)
            line.columnconfigure(1, weight=1)
            ttk.Label(line, text=label, width=14).grid(row=0, column=0, sticky="w")
            var = tk.StringVar(value="待同步")
            self.values[key] = var
            ttk.Label(line, textvariable=var).grid(row=0, column=1, sticky="e", padx=(4, 8))
            controls = []
            for col, (text, step) in enumerate((("－", -1), ("＋", 1), ("＋10", 10)), start=2):
                button = ttk.Button(line, text=text, width=4,
                                    command=lambda k=key, v=step: self.change(k, v))
                button.grid(row=0, column=col, padx=2)
                controls.append(button)
            self.buttons[key] = controls
        ttk.Label(body, textvariable=self.note, wraplength=515, style="Muted.TLabel").pack(anchor="w", pady=(10, 5))
        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(6, 0))
        self.reset_button = ttk.Button(footer, text="取消預覽", command=self.reset)
        self.reset_button.pack(side="left")
        self.confirm_button = ttk.Button(footer, text="確認配點", command=self.confirm)
        self.confirm_button.pack(side="right")
        self.render(app.snapshot)

    def change(self, key, step):
        if self.base is None or self.locked():
            return
        new = max(0, self.add[key] + step)
        spare = self.base["attribute_potential"] - sum(self.add.values()) + self.add[key]
        new = min(new, max(0, spare), max(0, MAX_BASE_ATTRIBUTE - self.base[key]))
        self.add[key] = new
        self.show_values()

    def reset(self):
        self.add = {key: 0 for key in KEYS}
        self.show_values()

    def locked(self):
        data = self.app.snapshot.get("attribute_allocation", {})
        return (self.queued or data.get("pending") or data.get("uncertain")
                or not self.app.live_active)

    def show_values(self):
        if self.base is not None:
            spent = sum(self.add.values())
            self.points.set("剩餘可分配：{}　預計使用：{}　確認後剩餘：{}".format(
                self.base["attribute_potential"], spent,
                self.base["attribute_potential"] - spent))
            for key in KEYS:
                old = self.base[key]
                amount = self.add[key]
                self.values[key].set("{}{}　→　{}".format(old, " +" + str(amount) if amount else "",
                                                       old + amount))
        enabled = self.base is not None and not self.locked()
        spare = self.base["attribute_potential"] - sum(self.add.values()) if self.base else 0
        for key, controls in self.buttons.items():
            minus, plus, plus_ten = controls
            minus.configure(state="normal" if enabled and self.add[key] > 0 else "disabled")
            can_add = enabled and spare > 0 and self.base[key] + self.add[key] < MAX_BASE_ATTRIBUTE
            plus.configure(state="normal" if can_add else "disabled")
            plus_ten.configure(state="normal" if can_add else "disabled")
        self.reset_button.configure(state="normal" if enabled and sum(self.add.values()) else "disabled")
        self.confirm_button.configure(state="normal" if enabled and sum(self.add.values()) else "disabled")

    def confirm(self):
        if self.base is None or self.locked() or not any(self.add.values()):
            return
        total = sum(self.add.values())
        if not messagebox.askyesno("確認能力配點",
                "將使用 {} 點能力點。確認後由遊戲伺服器處理，無法在此撤銷。確定送出？".format(total),
                parent=self.window):
            return
        if self.app.send({"type": "allocate_points", "baseline": dict(self.base),
                          "increments": dict(self.add)}):
            self.queued = True
            self.note.set("送出中，請等待伺服器確認；請勿重複操作。")
            self.show_values()

    def rejected(self, message):
        self.queued = False
        self.note.set("配點未送出：" + str(message))
        self.show_values()

    def render(self, state):
        player = state.get("player", {})
        stats = state.get("knowledge", {}).get("player", {}).get("stats", {})
        ready = state.get("knowledge", {}).get("player", {}).get("ready", False)
        self.role.set("{}｜等級 {}".format(player.get("name") or "角色",
                                         stats.get("level", "待同步")))
        try:
            current = baseline(stats) if ready and player.get("role_id") else None
        except ValueError:
            current = None
        if current != self.base:
            self.base = current
            self.add = {key: 0 for key in KEYS}
        allocation = state.get("attribute_allocation", {})
        if allocation.get("pending"):
            self.queued = False
        elif self.queued and current != self.base:
            self.queued = False
        if allocation.get("uncertain"):
            self.queued = False
        if not current:
            self.points.set("剩餘點數：待同步")
            for val in self.values.values():
                val.set("待同步")
            self.note.set("角色五項能力或剩餘點數尚未完整同步。")
        elif allocation.get("status"):
            self.note.set(allocation["status"])
        elif not self.queued:
            self.note.set("可預覽加減點；只有按下確認才會向伺服器送出。")
        self.show_values()
